// dashboard/static/js/denuncias_map.js
(function () {
  // ---- Config --------------------------
  const MAP_ID = "mapa-permiso";
  const BTN_GEO_ID = "btn-geolocalizar";
  const LAT_INPUT_ID = "id_latitud";
  const LNG_INPUT_ID = "id_longitud";

  // Centro por defecto (Guatemala aprox) si no hay coords previas
  // Centro por defecto (San Luis Jilotepeque, Guatemala)
  const DEFAULT_CENTER = [14.64551, -89.72710]; // latitud, longitud
  const DEFAULT_ZOOM = 15;  // calles y avenidas visibles
  const ZOOM_WITH_MARKER = 17; // al seleccionar ubicación


  // Overpass: qué amenities queremos
  const POI_AMENITIES_REGEX = "school|hospital|place_of_worship|bank|restaurant|pharmacy";

  // Debounce para no spamear Overpass cuando mueves el mapa
  const DEBOUNCE_MS = 800;

  // --------------------------------------

  const mapEl = document.getElementById(MAP_ID);
  if (!mapEl) return; // en páginas sin mapa, salir silenciosamente

  // Inputs ocultos donde guardamos coords
  const latInput = document.getElementById(LAT_INPUT_ID);
  const lngInput = document.getElementById(LNG_INPUT_ID);

  // Lee valores iniciales (si vienen del form)
  const initialLat = latInput && latInput.value ? parseFloat(latInput.value) : null;
  const initialLng = lngInput && lngInput.value ? parseFloat(lngInput.value) : null;

  // Crea mapa
  const map = L.map(MAP_ID, {
    zoomControl: true,
    attributionControl: true,
  });

  // Tiles con labels claros (Carto Voyager)
  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    maxZoom: 20,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>, &copy; <a href="https://carto.com/">CARTO</a>',
  }).addTo(map);

  // Marker para la selección del usuario
  let userMarker = null;

  function setMarker(lat, lng, zoomTo = true) {
    const latNum = Number(lat);
    const lngNum = Number(lng);
    if (Number.isNaN(latNum) || Number.isNaN(lngNum)) return;

    // Crea o mueve marker
    if (!userMarker) {
      userMarker = L.marker([latNum, lngNum], { draggable: false }).addTo(map);
    } else {
      userMarker.setLatLng([latNum, lngNum]);
    }

    // Actualiza inputs ocultos
    if (latInput) latInput.value = latNum.toFixed(8);
    if (lngInput) lngInput.value = lngNum.toFixed(8);

    if (zoomTo) map.setView([latNum, lngNum], ZOOM_WITH_MARKER, { animate: true });
  }

  // Estado inicial del mapa
  if (initialLat != null && initialLng != null) {
    map.setView([initialLat, initialLng], ZOOM_WITH_MARKER);
    setMarker(initialLat, initialLng, false);
  } else {
    map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  }

  // Click en el mapa → fijar coords
  map.on("click", (e) => {
    const { lat, lng } = e.latlng;
    setMarker(lat, lng);
  });

  // Botón "Usar mi ubicación"
  const geoBtn = document.getElementById(BTN_GEO_ID);
  console.log('[denuncias_map] origin:', window.location.origin);
  console.log('[denuncias_map] geoBtn?', !!geoBtn);
  console.log('geoBtn found?', !!geoBtn, window.location.origin);

  if (geoBtn) {
    geoBtn.addEventListener("click", () => {
      console.log('click geoloc');
      if (!("geolocation" in navigator)) {
        alert("Tu navegador no soporta geolocalización.");
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          console.log('geoloc OK', pos.coords.latitude, pos.coords.longitude);
          const { latitude, longitude } = pos.coords;
          setMarker(latitude, longitude);
        },
        (err) => {
          console.warn('geoloc ERROR', err.code, err.message);
          alert("No fue posible obtener tu ubicación: " + err.message);
        },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    });
  }

  // ===== POIs (Overpass) =====
  let poiLayer = L.layerGroup().addTo(map);
  let debounceTimer = null;

  function bboxToString(b) {
    // south,west,north,east
    return `${b.getSouth()},${b.getWest()},${b.getNorth()},${b.getEast()}`;
  }

  function fetchPOIs() {
    const b = map.getBounds();
    const bbox = bboxToString(b);

    const query = `
      [out:json][timeout:25];
      (
        node["amenity"~"${POI_AMENITIES_REGEX}"](${bbox});
        way["amenity"~"${POI_AMENITIES_REGEX}"](${bbox});
        relation["amenity"~"${POI_AMENITIES_REGEX}"](${bbox});
      );
      out center 200;
    `;

    fetch("https://overpass-api.de/api/interpreter", {
      method: "POST",
      body: query,
      headers: { "Content-Type": "text/plain; charset=UTF-8" },
    })
      .then((r) => r.json())
      .then((data) => {
        poiLayer.clearLayers();

        // Evita saturar con demasiados puntos
        const elements = Array.isArray(data.elements) ? data.elements.slice(0, 200) : [];

        elements.forEach((el) => {
          const lat = el.lat ?? el.center?.lat;
          const lon = el.lon ?? el.center?.lon;
          if (lat == null || lon == null) return;

          const name = (el.tags && (el.tags.name || el.tags["name:es"])) || "(sin nombre)";
          const amenity = el.tags?.amenity || "poi";

          L.circleMarker([lat, lon], {
            radius: 5,
            weight: 1,
            opacity: 0.9,
            fillOpacity: 0.6,
          })
            .bindPopup(`<b>${name}</b><br><small>${amenity}</small>`)
            .addTo(poiLayer);
        });
      })
      .catch((err) => {
        // Silencioso para no molestar al usuario
        console.warn("Overpass error:", err);
      });
  }

  function debouncedPOIs() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(fetchPOIs, DEBOUNCE_MS);
  }

  map.on("moveend", debouncedPOIs);
  // carga inicial
  debouncedPOIs();

  // ===== UX: asegúrate que el contenedor de Leaflet no tenga reglas CSS que oculten los tiles =====
  // Ya lo resolviste en tu template con:
  // .leaflet-container img { max-width: none !important; }

})();


