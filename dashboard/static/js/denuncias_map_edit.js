// static/js/denuncias_map_edit.js
(function () {
  const mapDiv = document.getElementById("mapa-denuncia-edit");
  if (!mapDiv) return;

  const latInput = document.getElementById("id_latitud");
  const lngInput = document.getElementById("id_longitud");

  // lee coords iniciales si existen
  const initLat = parseFloat(mapDiv.dataset.lat);
  const initLng = parseFloat(mapDiv.dataset.lng);
  const hasInit = !isNaN(initLat) && !isNaN(initLng);

  const center = hasInit ? [initLat, initLng] : [14.65, -89.73]; // San Luis aprox
  const zoom = hasInit ? 16 : 13;

  const map = L.map("mapa-denuncia-edit").setView(center, zoom);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    maxZoom: 20,
    attribution: "&copy; OpenStreetMap, &copy; CARTO"
  }).addTo(map);

  let marker = null;
  if (hasInit) {
    marker = L.marker(center, { draggable: true }).addTo(map);
    marker.on("dragend", e => {
      const { lat, lng } = e.target.getLatLng();
      latInput.value = lat.toFixed(6);
      lngInput.value = lng.toFixed(6);
    });
  }

  function placeMarker(lat, lng) {
    if (marker) {
      marker.setLatLng([lat, lng]);
    } else {
      marker = L.marker([lat, lng], { draggable: true }).addTo(map);
      marker.on("dragend", e => {
        const { lat, lng } = e.target.getLatLng();
        latInput.value = lat.toFixed(6);
        lngInput.value = lng.toFixed(6);
      });
    }
    latInput.value = lat.toFixed(6);
    lngInput.value = lng.toFixed(6);
  }

  map.on("click", (e) => {
    placeMarker(e.latlng.lat, e.latlng.lng);
  });

  // geolocalizar
  const btnGeo = document.getElementById("btn-geoloc");
  if (btnGeo) {
    btnGeo.addEventListener("click", () => {
      if (!navigator.geolocation) return alert("Geolocalización no soportada.");
      navigator.geolocation.getCurrentPosition(
        pos => {
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          map.setView([lat, lng], 17);
          placeMarker(lat, lng);
        },
        () => alert("No se pudo obtener tu ubicación.")
      );
    });
  }

  // limpiar
  const btnClear = document.getElementById("btn-limpiar");
  if (btnClear) {
    btnClear.addEventListener("click", () => {
      if (marker) {
        map.removeLayer(marker);
        marker = null;
      }
      latInput.value = "";
      lngInput.value = "";
    });
  }
})();
