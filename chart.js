var data
var chart;
var treeData;
var treeChart;
var filteredColumns = [];
var series = {};


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

// Callback that creates and populates a data table,
// instantiates the pie chart, passes in the data and
// draws it.
function drawChart() {
  angular.bootstrap(document.body,['BillingExport']);
}


var app = angular.module('BillingExport', ['ngRoute']);
app.config(
  function($routeProvider){
    $routeProvider.when('/',
                        {templateUrl:'ShowAlerts',
                         controller: 'ShowAlerts'});
    $routeProvider.when('/AddAlert',
                        {templateUrl:'AddAlert',
                         controller: 'AddAlert'});
  });


app.controller('AddAlert', function ($scope,$http){
  $scope.message = "Add An Alert!";
});

app.controller('ShowAlerts', function ($scope,$http){
  $scope.message = "Here are your alerts!";
});



app.controller('BillingExportController', function ($scope,$http){
  console.log("billingexportcontrollerinit");

  $scope.showLoading=true;
  function showLoading(show){
    $scope.showLoading=show;
  }

  function showSelectedSku(selectedProduct,selectedSku){
    // if selectedProduct and selectedSku are null.
    // merge the

    filteredColumns =[];
    var filteredSeries = options.series;
    if(typeof filteredSeries == 'undefined'){
      filteredSeries = {};
      options.series = filteredSeries;
    }
    for(var col=0;col < data.getNumberOfColumns();col++){
      filteredColumns.push(col);
      // skip the time column
      if(col==0){
        continue;
      }
      var columnId = data.getColumnId(col);
      var product = columnId.substr(0,columnId.indexOf('/'));
      var sku = columnId.substr(columnId.indexOf('/')+1,columnId.length);
      if(((typeof selectedProduct == 'undefined') ||
          (selectedProduct == null) ||
          (product == selectedProduct)) &&
         ((typeof selectedSku == 'undefined') ||
          (selectedSku == null) ||
          (sku == selectedSku))){
        filteredColumns[col] = col;
        filteredSeries[col-1] = {visibleInLegend:'True'};
      }else{
        filteredColumns[col] = {
          label: data.getColumnLabel(col),
          type: data.getColumnType(col),
          calc: function () {
            return null;
          }
        };
        filteredSeries[col-1] = {visibleInLegend:'False'};
      }
    }
    var view = new google.visualization.DataView(data);
    view.setColumns(filteredColumns);
    chart.draw(view, options);
  }

  $http.get('/getProfile').success(function(data){
    console.log('profilescope');
    $scope.profile = data;
  });


  $scope.projectSelected = function(){
    console.log('projectselected!');
    var query = new google.visualization.Query('/chart?project=' + $scope.project);
    query.send(function(response){
      console.log('callback!');
      handleQueryResponse(response);
    });
  };

  console.log("projectlist");
  $scope.project = null;
  $http.get('/projectList').success(function(data){
    console.log("projectlistsuscess");
    $scope.projects = data;
    $scope.project = $scope.projects[5];
    $scope.projectSelected();
  });

  // get dataSource response from app engine. draw chart.
  function handleQueryResponse(response){
    console.log('handleQueryResponse!');
    showLoading(false);
    $scope.$apply();
    data = response.getDataTable();
    if(typeof data == 'undefined' || data == null){
      console.log('null?!');
      return;
    }
    chart = new google.visualization.LineChart(document.getElementById('line_chart_div'));
    treeChart = new google.visualization.TreeMap(document.getElementById('tree_chart_div'));

    google.visualization.events.addListener(treeChart, 'rollup', function () {
      showSelectedSku('Cloud');
    });

    google.visualization.events.addListener(treeChart, 'select', function () {
      var sel = treeChart.getSelection();
      // we selected something from the treemap, show on the line chart only the selected product or sku.
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


    for (var i = 0; i < data.getNumberOfColumns(); i++) {
      filteredColumns.push(i);
      if (i > 0) {
        series[i - 1] = {};
      }
    }

    // draw a treemap of the first row of the datable.
    function drawTreeChart(rowIndex){

      var previousSelection = treeChart.getSelection();
      // now construct a new DataTable
      var treeDataTable ={cols:[],rows:[]};
      treeDataTable.cols.push({label:'Product',type:'string'});
      treeDataTable.cols.push({label:'Sku',type:'string'});
      treeDataTable.cols.push({label:'Cost',type:'number'});
      // come up with a color???
      //treeDataTable.cols.push({label:'Difference',type:'number'});

      // translate the existing data format into a nested tree structure.
      // node, parent, value, color
      // first get all the root nodes, with total values
      // oh, wait!
      // skip first row (time)
      for(var col=1;col < data.getNumberOfColumns();col++){
        var columnId = data.getColumnId(col);
        var sku = columnId.substr(columnId.indexOf('/')+1,columnId.length);
        var product = columnId.substr(0,columnId.indexOf('/'));
        var cell = data.getValue(rowIndex,col);
        treeDataTable.rows.push({c:[{v:sku},{v:product},{v:cell}]});
      }

      // add top level root product
      treeDataTable.rows.push({c:[{v:'Cloud'},null,0]});
      treeData = new google.visualization.DataTable(treeDataTable);
      treeChart.draw(treeData);
      if(previousSelection.length > 0){
        treeChart.setSelection(previousSelection);
      }
    }

    function drawLineChart(){

      google.visualization.events.addListener(chart, 'select', function () {
        var sel = chart.getSelection();
        // if selection length is 0, we deselected an element
        if (sel.length > 0) {
          // if row is undefined, we clicked on the legend
          var col = sel[0].column;
          if (typeof sel[0].row === 'undefined' || sel[0].row == null) {
            if (filteredColumns[col] == col) {
              // hide the data series
              filteredColumns[col] = {
                label: data.getColumnLabel(col),
                type: data.getColumnType(col),
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
            var view = new google.visualization.DataView(data);
            view.setColumns(filteredColumns);
            chart.draw(view, options);
          }else{
            // we selected a row, update the treemap
            drawTreeChart(sel[0].row);
            // also highlight column selected in the legend.
          }
        }
      });
      //             chart.draw(data, options);
      showSelectedSku('Cloud');
    }

    // being too fast causes chart to improperly draw.
    window.setTimeout(function(){
      drawLineChart();
      var lastRow = data.getNumberOfRows()-1;
      chart.setSelection([{row:lastRow,column:0}]);
      drawTreeChart(lastRow);
    },2);
  }

});


// Load the Visualization API and the piechart package.
google.load('visualization', '1.0', {'packages':['corechart','treemap']});

// Set a callback to run when the Google Visualization API is loaded.
google.setOnLoadCallback(drawChart);
