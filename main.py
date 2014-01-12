"""
returns billing information.
"""

from datetime import datetime
import json
import webapp2
import cloudstorage as gcs
from cloudstorage.common import local_run
import gviz_api
from google.appengine.api import users
from google.appengine.ext import ndb

# do convolutions to speak to remote cloud storage even when on a local
# devserver.
if local_run():
  import httplib2
  from oauth2client.client import SignedJwtAssertionCredentials
  from cloudstorage import common
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
  common.set_access_token(certificate.access_token)


# cache chart data
class ChartData(ndb.Model):
  data_table = ndb.PickleProperty()


def GetCanonicalLineItem(line_item):
  return line_item.replace('com.google.cloud/services/', '')


# figure out how to cache this stuff.
def GetAllBillingDataTable():
  """Return billing table data."""
  # first example datastore cache.
  cached_data_table = ChartData.get_by_id('ChartData')
  if cached_data_table is not None:
    return cached_data_table.data_table
  line_items = []
  date_hash = dict()
  bucket = '/platform-demo-billing-export'
  for billing_object in gcs.listbucket(bucket + '/google-platform-demo-',
                                       delimiter='/'):
    billing_file = gcs.open(billing_object.filename)
    biling_data = json.loads(billing_file.read())
    for item in biling_data:
      # parse iso datetime without timzone (python can't handle it)
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

  data_table = gviz_api.DataTable([('Time', 'datetime')] +
                                  [(line_item, 'number') for
                                   line_item in line_items])
  data_table_data = [[date] + row for date, row in date_hash.iteritems()]
  data_table.LoadData(data_table_data)
  cached_data_table = ChartData(id='ChartData')
  cached_data_table.data_table = data_table
  cached_data_table.put()
  return data_table


class MainPage(webapp2.RequestHandler):
  def get(self):
    """Render chart."""
    data_table = GetAllBillingDataTable()
    json_response = data_table.ToJSonResponse(columns_order=None,
                                              order_by='Time')
    self.response.write(json_response)


class FlushCache(webapp2.RequestHandler):
  def post(self):
    """Clear Datastore cache."""
    ndb.Key('ChartData', 'ChartData').delete()
    self.redirect('/index.html')


class GetProfileInformation(webapp2.RequestHandler):
  def get(self):
    """Returns logged in user information."""
    user = users.get_current_user()
    profile_information = {'email': user.email(),
                           'logoutUrl': users.create_logout_url('/')}
    self.response.out.write(json.dumps(profile_information))

app = webapp2.WSGIApplication([('/chart', MainPage),
                               ('/getprofile', GetProfileInformation),
                               ('/flushCache', FlushCache)],
                              debug=True)
