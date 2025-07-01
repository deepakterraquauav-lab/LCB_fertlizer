const map = L.map('map').setView([28.44, 76.865], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

// Init draw controls
const drawnItems = new L.FeatureGroup().addTo(map);
const drawControl = new L.Control.Draw({
  draw: { polygon: true, marker: false, circle: false, polyline: false, rectangle: false },
  edit: { featureGroup: drawnItems }
});
map.addControl(drawControl);

let userAOI = null;

map.on(L.Draw.Event.CREATED, function (e) {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  userAOI = e.layer.toGeoJSON();
  console.log("Drawn AOI:", userAOI);
});

// File upload: supports GeoJSON/KML
document.getElementById('fileInput').addEventListener('change', function (e) {
  const file = e.target.files[0];
  const reader = new FileReader();
  reader.onload = function (event) {
    let geojson = null;

    if (file.name.endsWith('.geojson') || file.name.endsWith('.json')) {
      geojson = JSON.parse(event.target.result);
    } else if (file.name.endsWith('.kml')) {
      const kml = new DOMParser().parseFromString(event.target.result, 'text/xml');
      geojson = toGeoJSON.kml(kml);
    } else {
      alert("Only GeoJSON and KML supported in this simple demo!");
      return;
    }

    drawnItems.clearLayers();
    const layer = L.geoJSON(geojson).addTo(drawnItems);
    map.fitBounds(layer.getBounds());
    userAOI = geojson.features[0];
    console.log("Uploaded AOI:", userAOI);
  };
  reader.readAsText(file);
});

// Load button
document.getElementById('load').onclick = () => {
  if (!userAOI) {
    alert("Please draw or upload an AOI first.");
    return;
  }

  fetch('/get_daily_data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ aoi: userAOI })
  })
    .then(res => res.json())
    .then(data => {
      const dates = data.map(d => d.date);
      const ndvi = data.map(d => d.NDVI);
      const eto = data.map(d => d.ETo);
      const effRain = data.map(d => d.EffRain);
      const deltaS = data.map(d => d.DeltaS);
      const etc = data.map(d => d.ETc);
      const iwr = data.map(d => d.IWR);

      Plotly.newPlot('chart', [
        { x: dates, y: ndvi, name: 'NDVI' },
        { x: dates, y: eto, name: 'ETo' },
        { x: dates, y: effRain, name: 'EffRain' },
        { x: dates, y: deltaS, name: 'DeltaS' },
        { x: dates, y: etc, name: 'ETc' },
        { x: dates, y: iwr, name: 'IWR' }
      ], {
        title: 'Daily Crop Water Parameters',
        xaxis: { title: 'Date' },
        yaxis: { title: 'Value (mm or NDVI)' }
      });
    });
};
