
// Callback after google javascript libraries load.
// initializes angular framework.
function bootstrapAngular() {
  angular.bootstrap(document.body,['BillingExport']);
}

// Angular application and configuration.
var app = angular.module('BillingExport', ['ngRoute']);


// the gobalData service broadcasts changes in the selected project or set of
// alerts to all views.
app.factory('globalData',function($rootScope){
  return {
    broadcastProjectChange: function(msg) {
      $rootScope.$broadcast('handleProjectChange', msg);
    },
    broadcastAlertChange: function(msg) {
      $rootScope.$broadcast('handleAlertChange', msg);
    }
  };
});

app.config(
  function($routeProvider){
    $routeProvider.when('/Project/:project',
                        {templateUrl:'ShowAlerts',
                         controller: 'ShowAlerts'});
    $routeProvider.when('/AddAlert/:project',
                        {templateUrl:'AlertDetail',
                         controller: 'AddAlert'});
    $routeProvider.when('/EditAlert/:project/:key',
                        {templateUrl:'AlertDetail',
                         controller: 'EditAlert'});
    $routeProvider.when('/EditEmail/:project',
                        {templateUrl:'EmailDetail',
                         controller: 'EditEmail'});

  });

// Creats a new alert.
app.controller('AddAlert', function ($scope,$http,$location,$routeParams,
                                     globalData){
  $scope.alert={project:globalData.project};

  // Alerts need to associated with the current project.
  $scope.$on('handleProjectChange', function() {
    $scope.alert.project = globalData.project;
  });

  // Calls server to add alert, redirect to show alerts view on success.
  $scope.save = function(){
    $http.post('/addAlert', $scope.alert)
      .success(function() {
        globalData.broadcastAlertChange();
        $location.path('/Project/' + $scope.project);
      });
  };
});

// Edit or remove an existing alert.
app.controller('EditAlert', function ($scope,$http,$location,$routeParams){

  $http.post('/getAlert', {key:parseInt($routeParams.key)}).
    success(function(data){
      $scope.alert = data;
    });

  $scope.save = function(){
    $http.post('/editAlert', $scope.alert)
      .success(function() {
        $location.path('/Project/' + $scope.project );
      });
  };

  $scope.remove = function(){
    $http.post('/deleteAlert', $scope.alert)
      .success(function() {
        $location.path('/Project/' + $scope.project);
      });
  };
});

// Display list of existing alerts.
app.controller('ShowAlerts', function ($scope,$http,globalData){
  $scope.alerts = globalData.alerts;

  function getAlertList(){
    $http.post('/getAlertList',{project:$scope.project})
      .success(function(data){
        globalData.alerts = data;
        $scope.alerts = data;
      });
  }

  // Called after saving or deleting an alert.
  $scope.$on('handleAlertChange', function() {
    getAlertList();
  });

  // When the project selection changes.
  $scope.$on('handleProjectChange', function() {
    getAlertList();
  });

  // Initialize alerts upon controller init.
  getAlertList();
});

// Edit or delete emails to notify of billing alerts/daily subscriptions.
app.controller('EditEmail', function ($scope,$http,$location,$routeParams){
  $http.post('/getSubscription',{project:$routeParams.project}).
    success(function(data){
      // translate server subscription object into UI subscription object.
      // the 'unsubscribe' flag is bound to a html checkbox.
      var emails = data.emails.map(function(email){
        return {'email': email,
                'unsubscribe': false};
      });
      $scope.subscription = {'emails':emails,
                             'dailySummary':data.daily_summary,
                             'project':$scope.project};
    });

  $scope.addEmail = function(){
    // scope emails list is a list of objects paring an email with a boolean
    // flag to indicate remove from the list (unsubscribe).
    $scope.subscription.emails.push({email:$scope.subscriptionEmail,
                                     unsubscribe:false});
  };

  $scope.save = function(){
    // translate the UI subscription object into the format server expects
    // emails should be a list of string, not objects with "unsubsribe"/remove
    // flags.
    var obj_subscription = {'project':$scope.subscription.project,
                            'daily_summary':$scope.subscription.dailySummary};
    // translate list of objects to list of strings (or false if they should be
    // removed).
    obj_subscription.emails = $scope.subscription.emails.map(function(email){
      if(!email.unsubscribe){
        return email.email;
      }
      return false;
    });
    // remove any false values, leaving only subscribed emails.
    obj_subscription.emails = obj_subscription.emails.filter(function(obj){
      return obj;
    });
    // try to get a valid project.
    if(typeof obj_subscription.project == 'undefined'){
      obj_subscription.project = $scope.project;
    }
    // send emails to server, show project view on success.
    $http.post('/editSubscription', obj_subscription)
      .success(function() {
        $location.path('/Project/' + $scope.project);
      });
  };
});


// Handles chart displays and project selection.
app.controller('BillingExportController', function ($scope,$http,$location,
                                                    $routeParams,globalData){

  // DataTable object for line chart
  var chartData;
  // chart object
  var chart;
  // DataTable for the TreeMap
  var treeData;
  // TreeMap object
  var treeChart;
  // Array for all chart series to display. if value of the column is a number,
  // series is displayed, otherwise it will be an object configuring the series to
  // be hidden.
  var filteredColumns = [];
  // properties of the lines to show in chart
  var series = {};

  // the chart properties object,
  // see "https://developers.google.com/chart/interactive/docs/gallery/linechart#Configuration_Options"
  var options = {
    series: series,
    title: 'Charges',
    titlePosition: 'in',
    axisTitlesPosition: 'in',
    hAxis: {textPosition: 'in'},
    vAxis: {textPosition: 'in'},
    curveType:'function',
    focusTarget:'datum',
    width: '1200',
    height: 400,
    legend: {position: 'top', maxLines:100,alignment:'center'},
    chartArea:{height:'50%',width:'90%',left:0,top:170}
  };



  $scope.skus=[];

  // if the "loading" spinning circle overlay should display.
  $scope.showLoading=true;
  function showLoading(show){
    $scope.showLoading=show;
  }

  // Called when user clicks on a TreeMap area, will shift LineChart to show
  // selected product or sku.
  function showSelectedSku(selectedProduct,selectedSku){

    // initialize list of filteredSeries if this is our first time. index into
    // filteredSeries is one off from the column index as the first column is
    // the time axis and not a series.
    var filteredSeries = options.series;
    if(typeof filteredSeries == 'undefined'){
      filteredSeries = {};
      options.series = filteredSeries;
    }

    // clear the global filteredColumns
    filteredColumns = [];

    for(var col=0;col < chartData.getNumberOfColumns();col++){
      // assume the column is shown.
      filteredColumns.push(col);

      // skip the time values it's always first and always shown.
      if(col==0){
        continue;
      }

      var columnId = chartData.getColumnId(col);
      var product = columnId.substr(0,columnId.indexOf('/'));
      var sku = columnId.substr(columnId.indexOf('/')+1,columnId.length);

      // If a product selected, is this column in the selected product?
      // If a sku was selected, is this column the selected sku?
      // if so, it's to be shown.
      if(((typeof selectedProduct == 'undefined') ||
          (selectedProduct == null) ||
          (product == selectedProduct)) &&
         ((typeof selectedSku == 'undefined') ||
          (selectedSku == null) ||
          (sku == selectedSku))){
        filteredColumns[col] = col;
        // index into filteredSeries is one off from columns due to time value.
        filteredSeries[col-1] = {visibleInLegend:'True'};
      }else{
        // otherwise, it needs to be filtered, set column value to a config
        // object to hide the column.
        filteredColumns[col] = {
          label: chartData.getColumnLabel(col),
          type: chartData.getColumnType(col),
          calc: function () {
            return null;
          }
        };
        filteredSeries[col-1] = {visibleInLegend:'False'};
      }
    }

    // finally draw the chart with columns and options.
    var view = new google.visualization.DataView(chartData);
    view.setColumns(filteredColumns);
    chart.draw(view, options);
  }

  // to show username
  $http.get('/getProfile').success(function(data){
    $scope.profile = data;
  });

  // called when select box changes to a new project.
  $scope.projectSelected = function(){
    // notify other views that the project changed
    globalData.project = $scope.project;
    globalData.broadcastProjectChange();

    // when project changes, show the spinner.
    // as operation can take time if chart is not cached.
    showLoading(true);
    var query = new google.visualization.Query('/chart?project=' + $scope.project);
    query.send(function(response){
      handleQueryResponse(response);

      // change the url location so it can be bookmarked.
      if($routeParams.project != $scope.project){
        $location.path('/Project/' + $scope.project);
      }

      // we aren't in a UI thread, so need to invoke angular sync manually.
      $scope.$apply();
    });
  };

  // get dataSource response from app engine. draw chart.
  function handleQueryResponse(response){
    showLoading(false);
    chartData = response.getDataTable();

    // must have failed
    if(typeof chartData == 'undefined' || chartData == null){
      console.log('error loading chart data for project');
      return;
    }

    // after we load the chart, reset number of filtered columns/series.
    filteredColumns =[];
    for (var i = 0; i < chartData.getNumberOfColumns(); i++) {
      filteredColumns.push(i);
      if (i > 0) {
        // series is on off from columns due to 'date' column.
        series[i - 1] = {};
      }
    }

    var line_chart_div = document.getElementById('line_chart_div');
    chart = new google.visualization.LineChart(line_chart_div);

    var tree_chart_div = document.getElementById('tree_chart_div');
    treeChart = new google.visualization.TreeMap(tree_chart_div);

    // when 'right click' is pressed on TreeMap, go up a level and show product view.
    google.visualization.events.addListener(treeChart, 'rollup', function () {
      showSelectedSku('Cloud');
    });

    // when a product region is selected, show selected sku/product in LineChart.
    google.visualization.events.addListener(treeChart, 'select', function () {
      var sel = treeChart.getSelection();
      // we selected something from the TreeMap, show on the line chart only the selected product or sku.
      if (sel.length > 0) {
        var selectedRow = sel[0].row;
        var selectedProduct = treeData.getValue(selectedRow,1);
        var selectedSku = treeData.getValue(selectedRow,0);
        // top level product was selected.
        if(selectedProduct == 'Cloud'){
          selectedProduct = selectedSku;
          selectedSku = null;
        }
        showSelectedSku(selectedProduct,selectedSku);
      }
    });

    // Draw a TreeMap representing sku prices for the selected day.
    // row index is the index of the selected date on the line chart.
    function drawTreeChart(rowIndex){

      // keep track of any selected sku so it can remain selected on the new
      // date. (keep showing compute engine on a new date if they have selected
      // compute engine).
      var previousSelection = treeChart.getSelection();

      // now construct a new DataTable with new product/sku row.
      var treeDataTable ={cols:[],rows:[]};
      treeDataTable.cols.push({label:'Product',type:'string'});
      treeDataTable.cols.push({label:'Sku',type:'string'});
      treeDataTable.cols.push({label:'Cost',type:'number'});

      // could show increase or decrease in price as a color difference.
      // treeDataTable.cols.push({label:'Difference',type:'number'});

      // translate the existing data format into a nested tree structure.
      // node, parent, value, color
      // first get all the root nodes, with total values
      var allProducts = {};
      var allSkus = {};

      // but be sure to skip first row as it's just the date.
      // so start at 1, not 0.
      for(var col=1;col < chartData.getNumberOfColumns();col++){
        var columnId = chartData.getColumnId(col);

        // each column Id is of the format: 'Product/Sku'
        // so break out the product and sku.
        var sku = columnId.substr(columnId.indexOf('/')+1,columnId.length);
        var product = columnId.substr(0,columnId.indexOf('/'));
        var cell = chartData.getValue(rowIndex,col);

        // add row showing product/sku parent child relationship.
        treeDataTable.rows.push({c:[{v:sku},{v:product},{v:cell}]});
        if(!(product in allProducts)){
          allProducts[product] = {};
        }
        // values doesn't matter, this is just a "set".
        allSkus[columnId] = true;
        allProducts[product][sku] = true;
      }

      $scope.skus = Object.keys(allSkus).sort();
      // the 'Total' is not a real product/sku so remove it.
      $scope.skus.unshift('Total');

      // add top level 'Cloud' product
      treeDataTable.rows.push({c:[{v:'Cloud'},null,0]});
      treeData = new google.visualization.DataTable(treeDataTable);
      treeChart.draw(treeData);

      // Restore any selection made by the user.
      if(previousSelection.length > 0){
        treeChart.setSelection(previousSelection);
      }
      // refresh angular as we are not in a UI thread.
      $scope.$apply();
    }

    function drawLineChart(){

      // register for click events on the LineChart.
      google.visualization.events.addListener(chart, 'select', function () {
        var sel = chart.getSelection();

        // make sure we selected something.
        if (sel.length > 0) {
          // if row is undefined, we clicked on the legend, so hide/show the series.
          var col = sel[0].column;
          if (typeof sel[0].row === 'undefined' || sel[0].row == null) {
            if (filteredColumns[col] == col) {
              // hide the data series
              filteredColumns[col] = {
                label: chartData.getColumnLabel(col),
                type: chartData.getColumnType(col),
                calc: function () {
                  return null;
                }
              };

              // grey out the legend entry
              series[col - 1].color = '#CCCCCC';
            }
            else {
              // show the data series
              filteredColumns[col] = col;
              series[col - 1].color = null;
            }
            var view = new google.visualization.DataView(chartData);
            view.setColumns(filteredColumns);
            chart.draw(view, options);
          }else{
            // we selected a row/date so update the TreeMap.
            drawTreeChart(sel[0].row);
          }
        }
      });

      // on initialization show top level treemap view.
      showSelectedSku('Cloud');
    }

    // being too fast causes chart to improperly draw.
    window.setTimeout(function(){
      drawLineChart();
      var lastRow = chartData.getNumberOfRows()-1;
      chart.setSelection([{row:lastRow,column:0}]);
      drawTreeChart(lastRow);
    },2);
  }

  // show project selectbox
  $scope.project = null;
  $http.get('/projectList').success(function(data){
    $scope.projects = data;
    // if the project in the url is valid, use it as the default selection.
    if($scope.projects.indexOf($routeParams.project) != -1){
      $scope.project = $routeParams.project;
    }else{
      // otherwise just pick the first project we load.
      $scope.project = $scope.projects[0];
    }
    // load the project's chart
    $scope.projectSelected();
  });

});


// Load the Visualization API and the TreeMap/CoreChart package.
google.load('visualization', '1.0', {'packages':['corechart','treemap']});

// Set a callback to run when the Google Visualization API is loaded.
google.setOnLoadCallback(bootstrapAngular);
