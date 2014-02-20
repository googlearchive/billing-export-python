"""View billing export information.

An app engine application for parsing, displaing and triggering alerts from
cloud platform billing export data.

"""

from datetime import datetime
import json
import logging
import re
import webapp2
import cloudstorage as gcs
from cloudstorage import common as gcs_common
import gviz_api
import httplib2
from google.appengine.api import users
from google.appengine.ext import ndb


def UseLocalGCS():
  """Use the local GCS stub."""
  gcs_common.set_access_token(None)


def UseRemoteGCS():
  """Use remote GCS via a signed certificate."""
  from oauth2client.client import SignedJwtAssertionCredentials
  http_object = httplib2.Http(timeout=60)
  service_account = '773711848681-fm7jaj9nmbh9sedcmq8otutunvq5etog@developer.gserviceaccount.com'
  private_key_pem_file = 'f3b1d264fec3033936ccf54413ff2bc72ecab698-privatekey.pem'
  scope = 'https://www.googleapis.com/auth/devstorage.full_control'
  private_key = file(private_key_pem_file, 'rb').read()
  certificate = SignedJwtAssertionCredentials(service_account,
                                              private_key,
                                              scope)
  certificate.refresh(http_object)
  # TODO(bmenasha): refresh every hour
  gcs_common.set_access_token(certificate.access_token)


# do convolutions to speak to remote cloud storage even when on a local
# devserver.
if gcs_common.local_run():
  UseLocalGCS()

BUCKET = '/platform-demo-billing-export'


# cache chart data
class ChartData(ndb.Model):
  data_table = ndb.PickleProperty()


class Projects(ndb.Model):
  projects = ndb.PickleProperty()


def GetCanonicalLineItem(line_item):
  return line_item.replace('com.google.cloud/services/', '')


def AddCloudProductSums(line_items, date_hash):
  """Synthesize product specific columns."""
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


def GetBillingProjects():
  """return a list of all projects we have billing export informaiton for."""
  projects = Projects.get_by_id('Projects')
  if projects is not None:
    return projects.projects
  project_list = []
  current_project = None
  project_re = re.compile('.*/(.*)-[0-9]{4}-[0-9]{2}-[0-9]{2}.json')
  for billing_object in gcs.listbucket(BUCKET,
                                       delimiter='/'):
    project_name_match = re.match(project_re, billing_object.filename)
    if not project_name_match:
      continue
    project_name = project_name_match.group(1)
    if current_project != project_name:
      project_list.append(project_name)
      current_project = project_name
  projects = Projects(id='Projects')
  projects.projects = project_list
  projects.put()
  return project_list


def GetAllBillingDataTable(project_name):
  """Return billing table data."""
  # first example datastore cache.
  cached_data_table = ChartData.get_by_id(project_name)
  if cached_data_table is not None:
    return cached_data_table.data_table
  line_items = []
  date_hash = dict()
  for billing_object in gcs.listbucket(BUCKET + '/' + project_name,
                                       delimiter='/'):
    billing_file = gcs.open(billing_object.filename)
    biling_data = json.loads(billing_file.read())
    for item in biling_data:
      end_time = datetime.strptime(item['endTime'][:-6], '%Y-%m-%dT%H:%M:%S')
      line_item = GetCanonicalLineItem(item['lineItemId'])
      if line_item not in line_items:
        line_items.append(line_item)
      row = date_hash.get(end_time, [])
      date_hash[end_time] = row
      coli = line_items.index(line_item)
      for _ in range(len(row), coli+1):
        row.append(None)
      row[coli] = float(item['cost']['amount'])
    billing_file.close()

  AddCloudProductSums(line_items, date_hash)
  data_table = gviz_api.DataTable([('Time', 'datetime', 'Time')] +
                                  [(li, 'number', li.split('/')[1])
                                   for li in line_items])
  data_table_data = [[date] + row for date, row in date_hash.iteritems()]
  data_table.LoadData(data_table_data)
  cached_data_table = ChartData(id=project_name)
  cached_data_table.data_table = data_table
  cached_data_table.put()
  return data_table


class GetChartData(webapp2.RequestHandler):
  def get(self):
    """Render chart."""
    data_table = GetAllBillingDataTable(self.request.get('project'))
    tqx = self.request.get('tqx')
    req_id = int(tqx[tqx.find('reqId'):].split(':')[1])
    json_response = data_table.ToJSonResponse(req_id=req_id,
                                              columns_order=None,
                                              order_by='Time')
    self.response.write(json_response)


class FlushCache(webapp2.RequestHandler):
  def post(self):
    """Clear Datastore cache."""
    chart_data_keys = ChartData.query().fetch(keys_only=True)
    ndb.delete_multi_async(chart_data_keys)
    project_list_keys = Projects.query().fetch(keys_only=True)
    ndb.delete_multi_async(project_list_keys)
    self.redirect('/index.html')


class GetProfileInformation(webapp2.RequestHandler):
  def get(self):
    """Returns logged in user information."""
    user = users.get_current_user()
    profile_information = {'email': user.email(),
                           'logoutUrl': users.create_logout_url('/')}
    self.response.out.write(json.dumps(profile_information))


class GetProjectList(webapp2.RequestHandler):
  def get(self):
    """Returns logged in user information."""
    project_list = GetBillingProjects()
    self.response.out.write(json.dumps(project_list))

app = webapp2.WSGIApplication(
    [('/chart', GetChartData),
     ('/projectList', GetProjectList),
     ('/getProfile', GetProfileInformation),
     ('/flushCache', FlushCache)],
    debug=True)
