// Configuration
const DEFAULT_CENTER = [46.603354, 1.888334]; // France center
const DEFAULT_ZOOM = 6;
const MARKER_ZOOM = 15;

// Marker colors
const COLORS = {
  clean: '#72f2ad',
  dirty: '#ff865f',
  non_annotee: '#9daea6'
};

// Global variables
let map;
let markersLayer;
let heatmapLayer;
let heatmapVisible = false;
let currentMarkers = [];

// Initialize map
document.addEventListener('DOMContentLoaded', function() {
  initMap();
  loadMarkers();
  setupFilters();
  setupHeatmapToggle();
});

function initMap() {
  map = L.map('map', {
    center: DEFAULT_CENTER,
    zoom: DEFAULT_ZOOM,
    zoomControl: true
  });

  // OpenStreetMap tiles
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }).addTo(map);

  // Initialize marker cluster group
  markersLayer = L.markerClusterGroup({
    maxClusterRadius: 50,
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    zoomToBoundsOnClick: true,
    iconCreateFunction: function(cluster) {
      const markers = cluster.getAllChildMarkers();
      let dirtyCount = 0;
      let cleanCount = 0;

      markers.forEach(m => {
        if (m.options.markerLabel === 'dirty') dirtyCount++;
        else if (m.options.markerLabel === 'clean') cleanCount++;
      });

      let className = 'marker-cluster';
      if (dirtyCount > cleanCount) {
        className += ' marker-cluster-dirty';
      } else if (cleanCount > dirtyCount) {
        className += ' marker-cluster-clean';
      } else {
        className += ' marker-cluster-mixed';
      }

      return L.divIcon({
        html: '<div><span>' + markers.length + '</span></div>',
        className: className,
        iconSize: L.point(40, 40)
      });
    }
  });

  map.addLayer(markersLayer);
}

function createMarkerIcon(label) {
  const color = COLORS[label] || COLORS.non_annotee;
  return L.divIcon({
    className: 'custom-marker marker-' + label,
    html: `<div style="background-color: ${color}"></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -12]
  });
}

function createPopupContent(marker) {
  const labelClass = marker.label === 'clean' ? 'clean' :
                     marker.label === 'dirty' ? 'dirty' : 'unknown';

  return `
    <div class="marker-popup">
      <img src="${marker.thumbnail}" alt="Image" class="popup-thumbnail" />
      <div class="popup-info">
        <span class="popup-badge ${labelClass}">${marker.label}</span>
        ${marker.address ? `<p class="popup-address">${marker.address}</p>` : ''}
        <p class="popup-date">${marker.date || 'Date inconnue'}</p>
        <a href="/images/${marker.id}" class="popup-link">Voir detail</a>
      </div>
    </div>
  `;
}

async function loadMarkers() {
  const label = document.getElementById('filter-label').value;
  const period = document.getElementById('filter-period').value;

  try {
    const response = await fetch(`/api/markers?label=${label}&period=${period}`);
    const data = await response.json();

    // Clear existing markers
    markersLayer.clearLayers();
    currentMarkers = data.markers;

    // Add new markers
    data.markers.forEach(markerData => {
      const marker = L.marker([markerData.lat, markerData.lng], {
        icon: createMarkerIcon(markerData.label),
        markerLabel: markerData.label
      });

      marker.bindPopup(createPopupContent(markerData), {
        maxWidth: 280,
        className: 'custom-popup'
      });

      markersLayer.addLayer(marker);
    });

    // Update stats
    document.getElementById('marker-count').textContent = data.count;

    // Fit bounds if we have markers
    if (data.bounds) {
      map.fitBounds([
        [data.bounds.south, data.bounds.west],
        [data.bounds.north, data.bounds.east]
      ], { padding: [50, 50], maxZoom: 14 });
    } else if (data.count === 0) {
      map.setView(DEFAULT_CENTER, DEFAULT_ZOOM);
    }

    // Reload heatmap if visible
    if (heatmapVisible) {
      loadHeatmap();
    }

  } catch (error) {
    console.error('Erreur chargement marqueurs:', error);
  }
}

async function loadHeatmap() {
  const period = document.getElementById('filter-period').value;

  try {
    const response = await fetch(`/api/heatmap?period=${period}`);
    const data = await response.json();

    // Remove existing heatmap
    if (heatmapLayer) {
      map.removeLayer(heatmapLayer);
    }

    if (data.points.length > 0) {
      heatmapLayer = L.heatLayer(data.points, {
        radius: 25,
        blur: 15,
        maxZoom: 17,
        gradient: {
          0.4: '#ffe066',
          0.6: '#ff9933',
          0.8: '#ff6600',
          1.0: '#cc3300'
        }
      }).addTo(map);
    }

  } catch (error) {
    console.error('Erreur chargement heatmap:', error);
  }
}

function setupFilters() {
  document.getElementById('filter-label').addEventListener('change', loadMarkers);
  document.getElementById('filter-period').addEventListener('change', loadMarkers);
}

function setupHeatmapToggle() {
  const button = document.getElementById('toggle-heatmap');
  const legendItem = document.getElementById('legend-heatmap');

  button.addEventListener('click', function() {
    heatmapVisible = !heatmapVisible;

    if (heatmapVisible) {
      button.classList.add('active');
      legendItem.style.display = 'flex';
      loadHeatmap();
    } else {
      button.classList.remove('active');
      legendItem.style.display = 'none';
      if (heatmapLayer) {
        map.removeLayer(heatmapLayer);
      }
    }
  });
}

// Export for mini-maps
window.WDPMap = {
  initMiniMap: function(containerId, lat, lng, zoom = 15) {
    const miniMap = L.map(containerId, {
      center: [lat, lng],
      zoom: zoom,
      zoomControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      touchZoom: false
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OSM',
      maxZoom: 19
    }).addTo(miniMap);

    return miniMap;
  },

  addMarker: function(miniMap, lat, lng, label) {
    const marker = L.marker([lat, lng], {
      icon: createMarkerIcon(label || 'non_annotee')
    }).addTo(miniMap);
    return marker;
  }
};
