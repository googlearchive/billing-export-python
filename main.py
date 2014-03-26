#!/usr/bin/python

# Copyright 2014 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#            http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""View billing export data.

An app engine application for parsing, displaing and triggering alerts from
cloud platform billing export data.

For more information on billing export see

https://support.google.com/cloud/answer/4524336?hl=en

"""

from datetime import date, datetime, timedelta
import json
import logging
import re
import sys
import os

import jinja2
import webapp2
import gviz_api
import httplib2
import cloudstorage as gcs
from cloudstorage import common as gcs_common
from protorpc import messages
from google.appengine.api import app_identity
from google.appengine.ext import deferred
from google.appengine.api import mail
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext.ndb import msgprop

import config


def UseLocalGCS():
    """Use the local GCS stub, great for testing locally.."""
    gcs_common.set_access_token(None)


def UseRemoteGCS():
    """Use remote GCS via a signed certificate."""
    logging.debug('Using remote gcs.')
    try:
        from oauth2client.client import SignedJwtAssertionCredentials
    except ImportError:
        logging.error('For local testing with remote GCS, install pycrypto.')
        return
    http_object = httplib2.Http(timeout=60)
    service_account = config.service_account
    private_key_pem_file = config.private_key_pem_file
    scope = 'https://www.googleapis.com/auth/devstorage.full_control'
    private_key = file(private_key_pem_file, 'rb').read()
    certificate = SignedJwtAssertionCredentials(service_account,
                                                private_key,
                                                scope)
    certificate.refresh(http_object)
    gcs_common.set_access_token(certificate.access_token)


# Do convolutions to speak to remote cloud storage even when on a local
# devserver. If you want to communicate to remote GCS, rather then use local
# GCS stubs, set this value in config.py to true. It requires setting:
# config.service_account and config.private_key_pem_file from a project service
# account.
#
if config.use_remote_gcs_when_local:
    UseRemoteGCS()

# Bucket containing billing export data.
BUCKET = config.bucket
# Email template.
TEMPLATE_ENV = jinja2.Environment(loader=jinja2.FileSystemLoader('.'),
                                  autoescape=True)
EMAIL_TEMPLATE = TEMPLATE_ENV.get_template('project_email.html')


class ChartData(ndb.Model):

    """Cache the resulting TableData object parsed from the json files."""
    data_table = ndb.PickleProperty()


class Projects(ndb.Model):

    """Cache a list of all project exports in the bucket."""
    projects = ndb.PickleProperty()


class AlertTrigger(messages.Enum):

    """What condition the alert will trigger under."""
    RELATIVE_CHANGE = 0
    TOTAL_CHANGE = 1
    TOTAL_AMOUNT = 2


class AlertRange(messages.Enum):

    """Compared to previous time."""
    ONE_DAY = 1
    ONE_WEEK = 7
    ONE_MONTH = 30
    ONE_YEAR = 365


class Alert(ndb.Model):

    """When to notify on price changes."""
    name = ndb.StringProperty()
    project = ndb.StringProperty()  # None if it should apply to all projects
    range = msgprop.EnumProperty(AlertRange)
    trigger = msgprop.EnumProperty(AlertTrigger)
    trigger_value = ndb.FloatProperty()  # dollar amount or percentage
    # product/sku or null if target is TOTAL
    target_value = ndb.StringProperty()
    # put everything into one entity group.
    entity_group = ndb.Key('AlertEntityGroup', 1)

    def isAlertTriggered(self, project, current_date):
        """Return true if an alert should trigger."""

        # See if the project matches.
        if self.project is not None and self.project != project:
            return False

        # billing data for the current date.
        current_dtd = GetDataTableData(project, current_date)
        current_target_value = current_dtd.GetTargetAmount(self.target_value)
        logging.debug('\ncurrent_dtd.rows=' + repr(current_dtd.rows) +
                      '\ncurrent_dtd.columns=' + repr(current_dtd.columns) +
                      '\ncurrent_target_value=' + repr(current_target_value))
        # if the alert trigger is based on a past billing data,
        # lookup the past billing data.
        resulting_target_value = current_target_value
        if self.trigger != AlertTrigger.TOTAL_AMOUNT:
            elapsed_range = timedelta(-self.range.number)
            past_date = current_date + elapsed_range
            past_dtd = GetDataTableData(project, past_date)
            past_target_value = past_dtd.GetTargetAmount(self.target_value)
            # calculate the difference between the past and current billing
            # data.
            if self.trigger == AlertTrigger.TOTAL_CHANGE:
                resulting_target_value = current_target_value - \
                    past_target_value
            else:  # must be RELATIVE_CHANGE
                if past_target_value == 0:
                    resulting_target_value = sys.float_info.max
                else:
                    resulting_target_value = (
                        (current_target_value - past_target_value) /
                        past_target_value) * 100
            logging.debug('relative_change or total_change alert :\n' +
                          repr(self) + '\ncurrent_target_value=' +
                          str(current_target_value) +
                          '\npast_target_value=' + str(past_target_value) +
                          '\npast_dtd.rows=' + repr(past_dtd.rows) +
                          '\npast_dtd.columns=' + repr(past_dtd.columns))
        is_triggered = False

        # is the difference/total over the alert's threshold?
        if self.trigger_value < 0:
            if resulting_target_value < self.trigger_value:
                is_triggered = True
        else:
            if resulting_target_value > self.trigger_value:
                is_triggered = True
        logging.debug('Evaluating ' + repr(self) + ' resulting_target_value='
                      + repr(resulting_target_value) + ' and is_triggered=' +
                      str(is_triggered))
        return is_triggered

    @classmethod
    def forProject(cls, project_name):
        """Returns the alerts created for supplied project."""
        alert_keys = []
        alert_keys = Alert.query(
            Alert.project == project_name,
            ancestor=Alert.entity_group).fetch(keys_only=True)
        alerts = ndb.get_multi(alert_keys)
        return alerts

    def to_dict(self):
        """Easier json serialization."""
        value = super(Alert, self).to_dict()
        if self.key is not None:
            value['key'] = self.key.id()
        return value


def EnumPropertyHandler(obj):
    """Serialize datetime objects."""
    return obj.name if isinstance(obj, messages.Enum) else obj


def GetCanonicalLineItem(line_item):
    """Simplify product and sku names."""
    return line_item.replace('com.google.cloud/services/', '')


def AddCloudProductSums(line_items, date_hash):
    """Synthesize product specific totals in supplied line_items and date_hash.

    Args:
      line_items: a list of sku names that were charged to the project.
      date_hash: a map of date objects to a list of charges for each line_item.
    Returns:
      Will add new 'Cloud/<product> elements to the supplied line_items list,
      and product total to the date_hash values returns nothing.
    """
    line_item_product = [li.split('/')[0] for li in line_items]
    for _, row in date_hash.iteritems():
        product_totals = {li.split('/')[0]: 0 for li in line_items}
        for i, cost in enumerate(row):
            if cost is not None:
                product_totals[line_item_product[i]] += cost
        for _ in range(len(row), len(line_items)):
            row.append(None)
        for _, total in sorted(product_totals.iteritems()):
            row.append(float(total))
    line_items += ['Cloud/' + product
                   for product in sorted(set(line_item_product))]


def MatchProjectDate(object_name):
    """Returns a project,date tuple from the object file name."""
    project_re = re.compile(
        '(?:.*/)?(.*)-([0-9]{4})-([0-9]{2})-([0-9]{2}).json')
    project_match = re.match(project_re, object_name)
    if project_match is not None:
        return (project_match.group(1),
                date(*[int(g) for g in project_match.groups()[1:]]))
    return None, None


def GetBillingProjects():
    """return a list of all projects we have billing export informaiton for."""
    projects = Projects.get_by_id('Projects')
    if projects is not None:
        logging.debug('using cached projects')
        return projects.projects
    project_list = []
    current_project = None
    for billing_object in gcs.listbucket(BUCKET,
                                         delimiter='/'):
        project_match = MatchProjectDate(billing_object.filename)
        if not project_match:
            continue
        project_name = project_match[0]
        if current_project != project_name:
            project_list.append(project_name)
            current_project = project_name
    projects = Projects(id='Projects')
    projects.projects = project_list
    projects.put()
    return project_list


class DataTableData(object):

    """Data for a gviz_api.DataTable."""
    rows = []
    columns = []

    def __init__(self, rows, columns):
        self.rows = rows
        self.columns = columns

    def GetTargetAmount(self, target):
        """Returns the amount of the input sku or total of all."""
        target_amount = 0
        for row in self.rows:
            for index, cell in enumerate(row[1:]):
                if ((target is 'Total' and
                     (not self.columns[index].startswith('Cloud/')))
                   or target == self.columns[index]):
                    target_amount += cell
        return target_amount


def GetDataTableData(project_name, table_date=None):
    """Read json files from cloud storage for project and an optional date.

    Args:
      project_name: name of the project to get data for.
      table_date: date object for when to get the data. When  None
      last 90 days of data is parsed.
    Returns:
      A DataTableData object of all the parsed data with product totals.
    """
    line_items = []
    date_hash = dict()
    object_prefix = os.path.join(BUCKET, project_name)
    object_marker = None
    if table_date is not None:
        object_prefix += table_date.strftime('-%Y-%m-%d.json')
    else:
        # query for last 90 days of data by using a 'marker' to start the
        # listing from, this limits the size of the chart data object
        # dropping older rows from the report.
        ninty_days_ago = date.today() + timedelta(-90)
        object_marker = object_prefix + \
            ninty_days_ago.strftime('-%Y-%m-%d.json')
    for billing_object in gcs.listbucket(object_prefix,
                                         marker=object_marker,
                                         delimiter='/'):
        billing_file = gcs.open(billing_object.filename)
        biling_data = json.loads(billing_file.read())
        for item in biling_data:
            end_time = datetime.strptime(
                item['endTime'][:-6], '%Y-%m-%dT%H:%M:%S')
            line_item = GetCanonicalLineItem(item['lineItemId'])
            if line_item not in line_items:
                line_items.append(line_item)
            row = date_hash.get(end_time, [])
            date_hash[end_time] = row
            coli = line_items.index(line_item)
            for _ in range(len(row), coli + 1):
                row.append(None)
            row[coli] = float(item['cost']['amount'])
        billing_file.close()

    # Add product totals to the parsed sku amounts.
    AddCloudProductSums(line_items, date_hash)
    data_table_data = [[bill_date] + row for bill_date, row in
                       date_hash.iteritems()]
    return DataTableData(data_table_data, line_items)


def GetAllBillingDataTable(project_name):
    """Returns gviz_api.DataTable containing last 90 days of data.
    Will try to use datastore/memcached data if available.

    Args:
      project_name: string name of the project
    Returns:
      A gviz_api.DataTable instance.
    """
    # first example datastore cache.
    cached_data_table = ChartData.get_by_id(project_name)
    if cached_data_table is not None:
        return cached_data_table.data_table

    # read billing data from cloud storage
    data_table_data = GetDataTableData(project_name)

    # create gviz data table from data
    data_table = gviz_api.DataTable([('Time', 'datetime', 'Time')] +
                                    [(li, 'number', li.split('/')[1])
                                     for li in data_table_data.columns])
    data_table.LoadData(data_table_data.rows)
    # create the ChartData entity to be cached in memcache and datatore
    cached_data_table = ChartData(id=project_name)
    # persist the DataTable object to it.
    cached_data_table.data_table = data_table
    cached_data_table.put()
    return data_table


class GetChartData(webapp2.RequestHandler):

    """Returns json parsable by Google Visualization javascript library."""

    def get(self):
        """Calls GetAllBillingDataTable.
        Returns: response in a format acceptible to google javascript
        visualization
        library.
        """
        data_table = GetAllBillingDataTable(self.request.get('project'))
        tqx = self.request.get('tqx')
        req_id = int(tqx[tqx.find('reqId'):].split(':')[1])
        json_response = data_table.ToJSonResponse(req_id=req_id,
                                                  columns_order=None,
                                                  order_by='Time')
        self.response.write(json_response)


def FlushAllCaches():
    """Removes any cached data from datastore/memache."""
    chart_data_keys = ChartData.query().fetch(keys_only=True)
    ndb.delete_multi(chart_data_keys)
    project_list_keys = Projects.query().fetch(keys_only=True)
    ndb.delete_multi(project_list_keys)


def PopulateCaches():
    """Loads all data into caches for faster initial page renders."""
    billing_projects = GetBillingProjects()
    for project in billing_projects:
        deferred.defer(GetAllBillingDataTable, project)


class FlushCache(webapp2.RequestHandler):

    """Handler to invoke FlushAllCaches."""

    def post(self):
        """Clear Datastore cache."""
        FlushAllCaches()
        self.redirect('/index.html')


class GetProfileInformation(webapp2.RequestHandler):

    def get(self):
        """Returns logged in user information."""
        user = users.get_current_user()
        profile_information = {'email': user.email(),
                               'logoutUrl': users.create_logout_url('/')}
        self.response.out.write(json.dumps(profile_information))


def DeserializeAlert(json_string):
    """Return an Alert json object."""
    alert_obj = json.loads(json_string)
    # handle enum properties
    if 'range' in alert_obj and alert_obj['range'] is not None:
        alert_obj['range'] = AlertRange(alert_obj['range'])
    if 'trigger' in alert_obj and alert_obj['trigger'] is not None:
        alert_obj['trigger'] = AlertTrigger(alert_obj['trigger'])
    return alert_obj


class AddAlert(webapp2.RequestHandler):

    def post(self):
        """Adds alert to the datastore."""
        alert_obj = DeserializeAlert(self.request.body)
        alert = Alert(parent=Alert.entity_group, **alert_obj)
        logging.debug('adding alert : ' + repr(alert))
        alert.put()
        self.response.out.write(json.dumps({'status': 'success'}))


class EditAlert(webapp2.RequestHandler):

    def post(self):
        """Save alert to the datastore."""
        alert_obj = DeserializeAlert(self.request.body)
        alert = Alert.get_by_id(alert_obj['key'], parent=Alert.entity_group)
        if alert is not None:
            alert_obj.pop('key')
            alert.populate(**alert_obj)
        logging.debug('editing alert : ' + repr(alert))
        alert.put()
        self.response.out.write(json.dumps({'status': 'success'}))


class DeleteAlert(webapp2.RequestHandler):

    def post(self):
        """Save alert to the datastore."""
        alert_obj = DeserializeAlert(self.request.body)
        logging.debug('deleting alert : ' + repr(alert_obj))
        alert = Alert.get_by_id(alert_obj['key'], parent=Alert.entity_group)
        if alert is not None:
            ndb.Key('Alert', alert_obj['key'],
                    parent=Alert.entity_group).delete()
        self.response.out.write(json.dumps({'status': 'success'}))


class GetAlert(webapp2.RequestHandler):

    def post(self):
        """Get Alert by supplied key."""
        alert_obj = json.loads(self.request.body)
        alert = Alert.get_by_id(alert_obj['key'], Alert.entity_group)
        self.response.out.write(json.dumps(alert.to_dict(),
                                           default=EnumPropertyHandler))


class GetAlertList(webapp2.RequestHandler):

    def post(self):
        """Lists alerts for supplied project."""
        filters = json.loads(self.request.body)
        alerts = Alert.forProject(filters.get('project', None))
        alerts = [alert.to_dict() for alert in alerts if alert is not None]
        self.response.out.write(json.dumps(alerts,
                                           default=EnumPropertyHandler))


class GetProjectList(webapp2.RequestHandler):

    def get(self):
        """Returns logged in user information."""
        project_list = GetBillingProjects()
        self.response.out.write(json.dumps(project_list))


class Subscription(ndb.Model):

    """Who to send emals to."""
    emails = ndb.StringProperty(indexed=False, repeated=True)
    daily_summary = ndb.BooleanProperty(indexed=False)

    @classmethod
    def getInstance(cls, project):
        subscription_key = ndb.Key(Subscription, project)
        subscription = subscription_key.get()
        if subscription is None:
            subscription = Subscription(key=subscription_key)
            subscription.put()
        return subscription


class GetSubscription(webapp2.RequestHandler):

    """Remove a list of emails from the subscribe list."""

    def post(self):
        request = json.loads(self.request.body)
        subscription = Subscription.getInstance(request['project'])
        self.response.write(json.dumps(subscription.to_dict()))


class EditSubscription(webapp2.RequestHandler):

    """Adds email to the email subscription list."""

    def post(self):
        request = json.loads(self.request.body)
        subscription = Subscription.getInstance(request['project'])
        subscription.emails = request['emails']
        subscription.daily_summary = request['daily_summary']
        subscription.put()
        self.response.write(json.dumps(subscription.to_dict()))


def SendEmail(context, recipients):
    """Send alert/daily summary email."""
    emailbody = EMAIL_TEMPLATE.render(context)

    if not recipients:
        logging.info('no recipients for email, using configured default: ' +
                     config.default_to_email)
        recipients = [config.default_to_email]
    mail.send_mail(sender=app_identity.get_service_account_name(),
                   subject='Billing Summary For ' + context['project'],
                   body=emailbody,
                   html=emailbody,
                   to=recipients)
    logging.info('sending email to ' + ','.join(recipients) + emailbody)


class ProcessedNotifications(ndb.Model):

    """Track if we processed the object notifications for a project today."""
    date_project_dict = ndb.PickleProperty()

    @classmethod
    def getInstance(cls):
        """Returns the single instance of this entity."""
        instance_key = ndb.Key(
            ProcessedNotifications, 'ProcessedNotifications')
        instance = instance_key.get()
        if instance is None:
            instance = ProcessedNotifications(key=instance_key)
            instance.put()
        return instance

    @classmethod
    @ndb.transactional
    def processForToday(cls, project):
        """Mark a project as having been processed (alerts/emails sent) today.

        Args:
           project: Name of project to process. Returns: True if we haven't and
           should process. This fuction modifies the map and assumes an email
           will be sent.

        Returns:
           True if the project was not processed today, False otherwise.
        """
        processed = ProcessedNotifications.getInstance()
        if processed.date_project_dict is None:
            processed.date_project_dict = {}
        today = date.today()
        if today not in processed.date_project_dict:
            processed.date_project_dict.clear()
            processed.date_project_dict[today] = []
        if project in processed.date_project_dict[today]:
            return False
        processed.date_project_dict[today].append(project)
        processed.put()
        return True


class ObjectChangeNotification(webapp2.RequestHandler):

    """Process notification events."""

    # get hostname from current request_url.
    host_name_re = re.compile('(.*)/')

    def post(self):
        """Process the notification event.

        Invoked when the notification channel is first created with a sync
        event, and then subsequently every time an object is added to the
        bucket, updated (both content and metadata) or removed. It records the
        notification message
        in the log.
        """

        logging.debug(
            '%s\n\n%s',
            '\n'.join(['%s: %s' %
                      x for x in self.request.headers.iteritems()]),
            self.request.body)

        # Check that the request body is not empty (such as in sync events)
        raw_json = self.request.body
        if not len(raw_json) > 0:
            logging.info('Request body was empty')
            return

        # Query for this project's alerts
        obj_notification = json.loads(raw_json)
        project_name, object_date = MatchProjectDate(obj_notification['name'])

        if not project_name or not object_date:
            logging.info('unable to parse project or date from ' +
                         obj_notification['name'])
            return

        # Ensure we don't send multiple emails for the same project if we get
        # multiple project object notifications in the same day.
        if not ProcessedNotifications.processForToday(project_name):
            logging.debug('Duplicate notification received for ' +
                          str(project_name))
            self.response.write('Duplicate notification')
            return

        alerts = Alert.forProject(project_name)

        # check if any alerts trigger.
        triggered_alerts = [alert for alert in alerts if
                            alert.isAlertTriggered(project_name, object_date)]

        logging.debug('\nfound alerts :' + repr(alerts) +
                      '\ntriggered:' + repr(triggered_alerts))

        # send the email if a daily summary is requested,
        # or an alert triggered.
        subscription = Subscription.getInstance(project_name)
        current_dtd = GetDataTableData(project_name, object_date)
        if len(triggered_alerts) or subscription.daily_summary:
            # built the data used by the email template
            host_url = self.host_name_re.match(self.request.url).group(1) + '/'
            context = {
                'project': project_name,
                'host_url': host_url,
                'project_url': host_url + '#/Project/' + project_name,
                'unsubscribe_url': host_url + '#/EditEmail/' + project_name,
                'alert_url': host_url + '#/EditAlert/' + project_name + '/',
                'triggered_alerts': triggered_alerts,
                'current_data': current_dtd}

            # actually send the email.
            SendEmail(context, subscription.emails)

        # Clear caches so project data is reread.
        FlushAllCaches()
        # Refresh project list and project data in a new task queue.
        deferred.defer(PopulateCaches)


app = webapp2.WSGIApplication(
    [('/chart', GetChartData),
     ('/projectList', GetProjectList),
     ('/getProfile', GetProfileInformation),
     ('/addAlert', AddAlert),
     ('/editAlert', EditAlert),
     ('/getAlertList', GetAlertList),
     ('/getAlert', GetAlert),
     ('/deleteAlert', DeleteAlert),
     ('/flushCache', FlushCache),
     ('/getSubscription', GetSubscription),
     ('/editSubscription', EditSubscription),
     ('/objectChangeNofication', ObjectChangeNotification)],
    debug=True)
