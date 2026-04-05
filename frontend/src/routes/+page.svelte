<script>
  import { onMount, tick } from 'svelte';

  let length = 10;
  let uphill = 500;
  let downhill = 450;
  let prediction = '02:22';
  let linearPrediction = '02:15';
  let din33466 = '02:08';
  let sac = '02:18';
  let loading = false;
  let errorMsg = '';

  let mapContainer;
  let currentMarker = null;
  let map;

  // Slider → /api/predict
  async function fetchPredict() {
    const params = new URLSearchParams({
      downhill: Math.round(downhill),
      uphill: Math.round(uphill),
      length: Math.round(length * 1000)  // Backend erwartet Meter!
    });
    try {
      const res = await fetch(`/api/predict?${params}`);
      const data = await res.json();
      prediction      = data.time     ?? prediction;
      linearPrediction= data.linear   ?? linearPrediction;
      din33466        = data.din33466 ?? din33466;
      sac             = data.sac      ?? sac;
    } catch (e) {
      console.error('predict Fehler:', e);
    }
  }

  // Reaktiv: bei Slider-Änderung
  $: if (length >= 0 && uphill >= 0 && downhill >= 0) fetchPredict();

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

// Interaktive Karte
  function initMap() {
    const L = window.L;
    mapContainer.style.height = '500px';

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

  // Map-Klick → /api/hiking
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
    }).addTo(map).bindPopup('⏳ Route wird geladen...').openPopup();

    loading = true;
    errorMsg = '';

    try {
      const res = await fetch(`/api/hiking?lat=${e.latlng.lat}&lng=${e.latlng.lng}`);

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error ?? `HTTP ${res.status}`);
      }

      const data = await res.json();

      // Backened-Werte setzen
      length   = Number(data.length)   ?? length;
      uphill   = Number(data.uphill)   ?? uphill;
      downhill = Number(data.downhill) ?? downhill;

      // Zeiten direkt vom Backend (inkl. ML-Predictions)
      prediction       = data.time     ?? prediction;
      linearPrediction = data.linear   ?? linearPrediction;
      din33466         = data.din33466 ?? din33466;
      sac              = data.sac      ?? sac;

      currentMarker.setPopupContent(
        `<b>✅ Route geladen</b><br>
         📏 ${length} km<br>
         ⬆️ ${uphill} m<br>
         ⬇️ ${downhill} m`
      ).openPopup();

    } catch (err) {
      errorMsg = `Fehler: ${err.message}`;
      currentMarker.setPopupContent(`❌ ${errorMsg}`).openPopup();
      console.error('hiking API Fehler:', err);
    } finally {
      loading = false;
    }
  }
</script>

<div class="app-bg">
  <div class="container py-5">
    <h1>HikePlanner</h1>
    <p>Schätze die Gehzeit basierend auf Distanz und Höhenmetern.</p>

    {#if errorMsg}
      <div class="alert alert-danger">{errorMsg}</div>
    {/if}

    <div class="row g-4 mb-4">
      <div class="col-md-4">
        <label class="form-label fw-bold">Length (km)</label>
        <input bind:value={length} type="range" min="0" max="50" step="0.1" class="form-range" />
        <div class="value-display">
          <span class="value">{length}</span>
        </div>
      </div>

      <div class="col-md-4">
        <label class="form-label fw-bold">Uphill (m)</label>
        <input bind:value={uphill} type="range" min="0" max="3000" step="10" class="form-range" />
        <div class="value-display">
          <span class="value">{uphill}</span>
        </div>
      </div>

      <div class="col-md-4">
        <label class="form-label fw-bold">Downhill (m)</label>
        <input bind:value={downhill} type="range" min="0" max="3000" step="10" class="form-range" />
        <div class="value-display">
          <span class="value">{downhill}</span>
        </div>
      </div>
    </div>

    <p class="text-muted small">
      {#if loading}⏳ Lade SwissTopo Route...{:else}Klicke auf einen Wanderweg → echte Distanz, Höhen &amp; Zeiten{/if}
    </p>

    <div bind:this={mapContainer}></div>

    <h2 class="mt-4">Dauer Übersicht</h2>
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