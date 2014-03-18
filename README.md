# billing-export-python

View Google Cloud Platform billing export files via an App Engine dashboard.

Demonstrates parsing billing export files stored in a cloud storage bucket and rendering a <a href="https://developers.google.com/chart/">Google Chart</a>, triggering alerts and sending summary email.

The dashboard presents a graph of the last 90 days of billing data sent by the  <a href="http://googlecloudplatform.blogspot.com/2013/12/ow-get-programmatic-access-to-your-billing-data-with-new-billing-api.html">billing export</a> feature. A complete walkthrough of the application, and enabling billing export, is <a href="https://www.youtube.com/watch?v=L3-e9imswtk">available on YouTube</a>.

## Setup Instructions

* *Setup Billing Export*. - Create a Cloud Storage bucket, and navigate to "Billing → Project → Billing Export". Enter the bucket name, a useful prefix, and select 'JSON' as the format.

* *Copy config.py.template to config.py* -  Enter values for the bucket to monitor, and a default email address to use when no email address exists.

* *Edit app.yaml* -  Supply a valid App Engine application id with access to the created bucket.

* *Setup Object Change Notifications* - Configure the URL https://billing-export-dot-{appid}.appspot.com/objectChangeNofication as the object change notification URL of the bucket. Steps are described <a href="https://developers.google.com/storage/docs/object-change-notification">here</a>. Please not the necessity of *using a service account with gsutil* to run the "gsutil notification" command, a personal account won't work.

> gsutil notification watchbucket  https://billing-export-dot-{appid}.appspot.com/objectChangeNofication gs://{bucketname>}


## Usage Tips

* Clicking the "Flush all caches" button takes time if there are a large number of objects in the bucket. It should never be needed if object change notifications are working.

* Select a date in the line chart by clicking a column in the body of the chart.

* The TreeMap chart at the top of the file presents the charge breakdown for the selected date.

* Select a product or SKU from the treemap to show charges for just the selected product or SKU in the line chart.

* Right-click the treemap to go back up.

* Show or hide lines in the line chart by selecting a series in the chart legend.


## Dependencies

This application makes use of

- *httplib2* -   http://code.google.com/p/httplib2/
- *oauth2client* - http://pypi.python.org/pypi/oauth2client/1.0
- *cloudstorage* - https://code.google.com/p/appengine-gcs-client/
- *gviz_api* - https://code.google.com/p/google-visualization-python/
- *google charts* - https://developers.google.com/chart/
- *bootstrap* - http://getbootstrap.com/
- *angularjs* - http://angularjs.org/
