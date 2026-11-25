/**
 * map/layers.js
 * Leaflet spatial layer management: facility point markers, buffer circles,
 * blank spot red polygon layers, and simulation result polygon styling.
 */

import { state } from "../state.js";
import { escapeHtml } from "../utils/dom.js";

export function clearSpatialLayers() {
  if (state.facilityMarkersLayer) state.facilityMarkersLayer.clearLayers();
  if (state.bufferCirclesLayer) state.bufferCirclesLayer.clearLayers();
  if (state.blankSpotLayer) state.blankSpotLayer.clearLayers();
}

export function clearBlankSpotLayers() {
  if (state.bufferCirclesLayer) state.bufferCirclesLayer.clearLayers();
  if (state.blankSpotLayer) state.blankSpotLayer.clearLayers();
}

export function renderFacilityMarkers(facilities) {
  if (!state.facilityMarkersLayer) return;
  state.facilityMarkersLayer.clearLayers();

  facilities.forEach(f => {
    const lat = f.latitude;
    const lon = f.longitude;
    if (!lat || !lon) return;

    let color = "#38bdf8";
    if (f.pillar === "lifeline_health") color = "#f43f5e";
    else if (f.pillar === "education") color = "#8b5cf6";
    else if (f.pillar === "urban_livability") color = "#10b981";
    else if (f.pillar === "mobility_connectivity") color = "#06b6d4";

    const isSatellite = state.activeBaseLayer === "Satelit";
    const marker = L.circleMarker([lat, lon], {
      pane: "markerPane",
      radius: 6,
      fillColor: color,
      color: isSatellite ? "#ffffff" : "#0f172a",
      weight: 1.8,
      opacity: 1,
      fillOpacity: 0.92
    });

    const safeType = (f.facility_type || "").replace(/_/g, " ");
    marker.bindPopup(`
      <div style="font-family: inherit; font-size: 12.5px;">
        <strong style="color: ${color};">${escapeHtml(f.name || "")}</strong><br/>
        Jenis: ${escapeHtml(safeType)}<br/>
        Pilar: ${escapeHtml(f.pillar || "")}
      </div>
    `);

    state.facilityMarkersLayer.addLayer(marker);
  });
}

export function renderBufferLayer(bufData) {
  if (!state.bufferCirclesLayer || !bufData) return;
  state.bufferCirclesLayer.clearLayers();

  const isSatellite = state.activeBaseLayer === "Satelit";
  L.geoJSON(bufData, {
    style: {
      color: isSatellite ? "#38bdf8" : "#0284c7",
      weight: 1.5,
      opacity: 0.8,
      fillColor: "#38bdf8",
      fillOpacity: 0.12,
      dashArray: "4, 3"
    }
  }).addTo(state.bufferCirclesLayer);
}

export function renderBlankSpotLayer(data) {
  if (!state.blankSpotLayer) return;
  state.blankSpotLayer.clearLayers();

  if (data && data.blank_spot_geojson && Object.keys(data.blank_spot_geojson).length > 0) {
    const cov = data.coverage_pct !== undefined ? data.coverage_pct : (data.coverage_percentage !== undefined ? data.coverage_percentage : "--");
    L.geoJSON(data.blank_spot_geojson, {
      style: {
        color: "#dc2626",
        weight: 2.2,
        opacity: 0.95,
        fillColor: "#ef4444",
        fillOpacity: 0.42
      }
    }).bindTooltip(`Blank spot ${escapeHtml(data.facility_type)}: ${data.unserved_area_km2} km² tidak terlayani (${cov}% cakupan)`, { sticky: true }).addTo(state.blankSpotLayer);

    if (state.blankSpotLayer.bringToFront) {
      state.blankSpotLayer.bringToFront();
    }
  }
}

export function styleSimulationLayer(code, delta) {
  if (!state.geojsonLayer || !code) return;

  state.geojsonLayer.eachLayer(layer => {
    const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
    if (c === code) {
      if (state.map && typeof layer.getBounds === "function") {
        state.map.fitBounds(layer.getBounds(), { padding: [50, 50], maxZoom: 14 });
      }
      layer.setStyle({
        color: delta < 0 ? "#e11d48" : "#059669",
        weight: 3.5,
        opacity: 1,
        fillOpacity: 0.35
      });
    }
  });
}
