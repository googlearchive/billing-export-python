import logging
from datetime import date
import os
import unittest
import webapp2
import webtest
import json
import cloudstorage as gcs
import main
from google.appengine.ext import testbed


class TestParseData(unittest.TestCase):
  """Tests parsing billing export data into a datatable."""

  def LoadTestData(self):
    data_dir = 'test/data/exports'
    for file_name in os.listdir(data_dir):
      local_data_file = open(os.sep.join([data_dir, file_name]))
      gcs_data_file = gcs.open(main.BUCKET + '/' + file_name, 'w')
      gcs_data_file.write(local_data_file.read())
      gcs_data_file.close()
      local_data_file.close()

  def setUp(self):
    #logging.basicConfig(level=logging.DEBUG)
    self.testbed = testbed.Testbed()
    self.testbed.setup_env(app_id='_')
    self.testbed.activate()
    self.testbed.init_all_stubs()
    main.UseLocalGCS()
    self.LoadTestData()
    app = webapp2.WSGIApplication([('/objectChangeNotification',
                                    main.ObjectChangeNotification)])
    self.testapp = webtest.TestApp(app)

  def testSKURelativeDifferenceAlert(self):
    compute_engine_alert = main.Alert()
    compute_engine_alert.range = main.AlertRange.ONE_WEEK
    compute_engine_alert.trigger = main.AlertTrigger.RELATIVE_CHANGE
    compute_engine_alert.target = main.AlertTarget.SKU
    compute_engine_alert.target_value = 'Cloud/compute-engine'
    compute_engine_alert.trigger_value = 300
    v = compute_engine_alert.isAlertTriggered('google-platform-demo',
                                              date(2014, 02, 01))
    assert v

  def testNotSKURelativeDifferenceAlert(self):
    compute_engine_alert = main.Alert()
    compute_engine_alert.range = main.AlertRange.ONE_WEEK
    compute_engine_alert.trigger = main.AlertTrigger.RELATIVE_CHANGE
    compute_engine_alert.target = main.AlertTarget.SKU
    compute_engine_alert.target_value = 'Cloud/compute-engine'
    compute_engine_alert.trigger_value = 400
    v = compute_engine_alert.isAlertTriggered('google-platform-demo',
                                              date(2014, 02, 01))
    assert not v

  def testNegativetSKURelativeDifferenceAlert(self):
    compute_engine_alert = main.Alert()
    compute_engine_alert.range = main.AlertRange.ONE_WEEK
    compute_engine_alert.trigger = main.AlertTrigger.RELATIVE_CHANGE
    compute_engine_alert.target = main.AlertTarget.SKU
    compute_engine_alert.target_value = 'Cloud/compute-engine'
    compute_engine_alert.trigger_value = -300
    v = compute_engine_alert.isAlertTriggered('google-platform-demo',
                                              date(2014, 02, 01))
    assert not v

  def testTotalDifferenceAlert(self):
    # data_table = main.GetAllBillingDataTable('google-platform-demo')
    compute_engine_alert = main.Alert()
    compute_engine_alert.range = main.AlertRange.ONE_DAY
    compute_engine_alert.target = main.AlertTarget.TOTAL
    compute_engine_alert.trigger = main.AlertTrigger.TOTAL_CHANGE
    compute_engine_alert.trigger_value = 10.00
    v = compute_engine_alert.isAlertTriggered('google-platform-demo',
                                              date(2014, 02, 04))
    self.assertTrue(v)
    # 167.33016600000002 2/3
    # 184.93568900000002 2/4

  def testSimpleObjectChangeNotification(self):
    data_dir = 'test/data/notifications'
    for file_name in os.listdir(data_dir):
      local_notification = open(os.sep.join([data_dir, file_name])).read()
      notification_dict = json.loads(local_notification)
      response = self.testapp.post_json('/objectChangeNotification',
                                        notification_dict)
      logging.debug(repr(response))
      self.assertEqual(response.status_int, 200)

  def testDailySummaryObjectChangeNotification(self):
    data_dir = 'test/data/notifications'
    for file_name in os.listdir(data_dir):
      local_notification = open(os.sep.join([data_dir, file_name])).read()
      notification_dict = json.loads(local_notification)
      project_date = main.MatchProjectDate(file_name)
      subscription = main.Subscription.getInstance(project_date[0])
      subscription.daily_summary = True
      response = self.testapp.post_json('/objectChangeNotification',
                                        notification_dict)
      logging.debug(repr(response))
      self.assertEqual(response.status_int, 200)

  def testAlertSummaryObjectChangeNotification(self):
    data_dir = 'test/data/notifications'
    file_name = 'google-platform-demo-2014-02-04.json'
    project_date = main.MatchProjectDate(file_name)

    compute_engine_alert = main.Alert(parent=main.Alert.entity_group)
    compute_engine_alert.name = 'Test Compute Engine Alert Alert'
    compute_engine_alert.range = main.AlertRange.ONE_DAY
    compute_engine_alert.target = main.AlertTarget.TOTAL
    compute_engine_alert.trigger = main.AlertTrigger.TOTAL_CHANGE
    compute_engine_alert.trigger_value = 10.00
    compute_engine_alert.project = project_date[0]
    compute_engine_alert.put()
    subscription = main.Subscription.getInstance(project_date[0])
    subscription.daily_summary = False
    local_notification = open(os.sep.join([data_dir, file_name])).read()
    notification_dict = json.loads(local_notification)
    project_date = main.MatchProjectDate(file_name)
    subscription = main.Subscription.getInstance(project_date[0])
    subscription.daily_summary = True
    response = self.testapp.post_json('/objectChangeNotification',
                                      notification_dict)
    logging.debug(repr(response))
    self.assertEqual(response.status_int, 200)

  def tearDown(self):
    # for gcs_object in gcs.listbucket(main.BUCKET):
    #  gcs.delete(gcs_object.filename)
    self.testbed.deactivate()
