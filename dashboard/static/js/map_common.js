// Mapa genérico que escribe en inputs lat/lng
window.initMapToInputs = function(containerId, latInputSel, lngInputSel, initLat, initLng, opts) {
  const container = document.getElementById(containerId);
  if (!container || typeof L === "undefined") return;

  const latInput = document.querySelector(latInputSel);
  const lngInput = document.querySelector(lngInputSel);
  if (!latInput || !lngInput) return;

  const center = (Array.isArray(opts?.center) ? opts.center : [14.65, -89.73]);
  const zoom   = (typeof opts?.zoom === "number" ? opts.zoom : 13);

  const map = L.map(containerId).setView(
    (initLat != null && initLng != null) ? [initLat, initLng] : center,
    (initLat != null && initLng != null) ? 16 : zoom
  );

  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    maxZoom: 20,
    attribution: '&copy; OpenStreetMap, &copy; CARTO'
  }).addTo(map);

  let marker = null;
  function putMarker(lat, lng) {
    if (marker) { marker.setLatLng([lat, lng]); }
    else { marker = L.marker([lat, lng]).addTo(map); }
    latInput.value = lat.toFixed(6);
    lngInput.value = lng.toFixed(6);
  }
  function clearMarker() {
    if (marker) { map.removeLayer(marker); marker = null; }
    latInput.value = ""; lngInput.value = "";
  }

  // inicial con coords (si las hay)
  if (initLat != null && initLng != null) {
    putMarker(parseFloat(initLat), parseFloat(initLng));
  }

  map.on('click', (e) => putMarker(e.latlng.lat, e.latlng.lng));

  // geolocalizar (opcional)
  if (opts?.geolocBtnId) {
    const btnGeo = document.getElementById(opts.geolocBtnId);
    if (btnGeo) {
      btnGeo.addEventListener('click', () => {
        if (!navigator.geolocation) return;
        navigator.geolocation.getCurrentPosition(
          pos => {
            const { latitude, longitude } = pos.coords;
            map.setView([latitude, longitude], 16);
            putMarker(latitude, longitude);
          }
        );
      });
    }
  }

  // limpiar marcador (opcional)
  if (opts?.clearBtnId) {
    const btnClear = document.getElementById(opts.clearBtnId);
    if (btnClear) btnClear.addEventListener('click', clearMarker);
  }
};
