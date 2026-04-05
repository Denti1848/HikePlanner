<script>
  import { onMount, tick } from 'svelte';

  let length = 10;
  let uphill = 500;
  let downhill = 450;
  let prediction = '02:22';
  let linearPrediction = '02:15';
  let din33466 = '02:08';
  let sac = '02:18';

  let mapContainer;
  let currentMarker = null;
  let map;

  function minutesToHHMM(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = Math.floor(minutes % 60);
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
  }

  function updatePredictions() {
    const baseSpeed = 4;
    const lengthHours = length / baseSpeed;
    const upPenalty = uphill / 300;
    const downBonus = downhill / 600;

    const predMins = (lengthHours + upPenalty + downBonus) * 60;
    const linMins = (lengthHours * 1.1 + upPenalty * 0.8) * 60;
    const dinMins = (lengthHours * 0.9 + upPenalty * 1.2) * 60;
    const sacMins = (lengthHours * 1.05 + upPenalty * 1.1) * 60;

    prediction = minutesToHHMM(predMins);
    linearPrediction = minutesToHHMM(linMins);
    din33466 = minutesToHHMM(dinMins);
    sac = minutesToHHMM(sacMins);
  }

  $: if (length >= 0 && uphill >= 0 && downhill >= 0) updatePredictions();

  onMount(async () => {
    if (typeof window === 'undefined') return;
    await tick();

    const css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
    document.head.appendChild(css);

    const leafletScript = document.createElement('script');
    leafletScript.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    leafletScript.onload = initMap;
    document.head.appendChild(leafletScript);
  });

  function initMap() {
    const L = window.L;
    mapContainer.style.height = '500px';
    mapContainer.style.width = '100%';

    map = L.map(mapContainer).setView([46.8, 8.2], 10);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

    L.tileLayer.wms('https://wms.geo.admin.ch/', {
      layers: 'ch.swisstopo.swisstlm3d-wanderwege',
      format: 'image/png',
      transparent: true,
      opacity: 0.9
    }).addTo(map);

    map.on('click', handleMapClick);
  }

  async function handleMapClick(e) {
    if (currentMarker) {
      map.removeLayer(currentMarker);
      currentMarker = null;
    }

    currentMarker = window.L.circleMarker(e.latlng, {
      radius: 12,
      color: '#10b981',
      weight: 3,
      fillOpacity: 0.7
    }).addTo(map);

    const params = new URLSearchParams({
      route: 'hiking',
      lat: e.latlng.lat,
      lng: e.latlng.lng
    });

    try {
      const res = await fetch(`/api/predict?${params.toString()}`);
      if (!res.ok) throw new Error(`API error ${res.status}`);

      const data = await res.json();

      if (typeof data.length !== 'undefined') length = Number(data.length);
      if (typeof data.uphill !== 'undefined') uphill = Number(data.uphill);
      if (typeof data.downhill !== 'undefined') downhill = Number(data.downhill);

      if (data.time) prediction = data.time;
      if (data.linear) linearPrediction = data.linear;
      if (data.din33466) din33466 = data.din33466;
      if (data.sac) sac = data.sac;

      currentMarker.bindPopup(
        `Route geladen!<br>
         Length: ${length} km<br>
         Uphill: ${uphill} m<br>
         Downhill: ${downhill} m`
      ).openPopup();
    } catch (err) {
      console.error('Route API fehlgeschlagen:', err);
      currentMarker.bindPopup('Route konnte nicht geladen werden').openPopup();
    }
  }
</script>

<div class="app-bg">
  <div class="container py-5">
    <h1>HikePlanner</h1>

    <p>Schätze die Gehzeit basierend auf Distanz und Höhenmetern.</p>

    <div class="row g-4 mb-4">
      <div class="col-md-4">
        <label class="form-label fw-bold">Length (km)</label>
        <input bind:value={length} type="range" min="0" max="50" step="0.1" class="form-range" />
        <div class="value-display">
          <span class="value">{length}</span>
          <span class="time">{prediction}</span>
        </div>
      </div>

      <div class="col-md-4">
        <label class="form-label fw-bold">Uphill (m)</label>
        <input bind:value={uphill} type="range" min="0" max="3000" step="10" class="form-range" />
        <div class="value-display">
          <span class="value">{uphill}</span>
          <span class="time">{linearPrediction}</span>
        </div>
      </div>

      <div class="col-md-4">
        <label class="form-label fw-bold">Downhill (m)</label>
        <input bind:value={downhill} type="range" min="0" max="3000" step="10" class="form-range" />
        <div class="value-display">
          <span class="value">{downhill}</span>
          <span class="time">{din33466}</span>
        </div>
      </div>
    </div>

    SwissTopo Wanderwege
    <div bind:this={mapContainer}></div>
    <small>Klicke rote/blaue Linien → Route via API laden</small>

    <h2>Dauer Übersicht</h2>
    <div class="table-responsive">
      <table class="table table-striped">
        <thead class="table-dark">
          <tr><th>Modell</th><th>Gehzeit</th></tr>
        </thead>
        <tbody>
          <tr><td>Gradient Boosting Regressor</td><td><strong>{prediction}</strong></td></tr>
          <tr><td>Linear Regression</td><td>{linearPrediction}</td></tr>
          <tr><td>DIN 33466</td><td>{din33466}</td></tr>
          <tr><td>SAC</td><td>{sac}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<style>
  :global(.leaflet-container) {
    height: 500px !important;
    width: 100% !important;
    border: 2px solid #dee2e6;
    border-radius: 8px;
  }

  .value-display {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 4px;
  }

  .value {
    font-size: 1.4rem;
    font-weight: 700;
    color: #1f2937;
  }

  .time {
    font-size: 1.1rem;
    font-weight: 600;
    color: #10b981;
    background: #f0fdf4;
    padding: 4px 12px;
    border-radius: 20px;
    font-family: monospace;
  }
</style>