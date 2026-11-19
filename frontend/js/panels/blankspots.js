/**
 * panels/blankspots.js
 * Controls the Blank Spots inspection panel, querying unserved spatial zones,
 * displaying coverage statistics, cross-border notes, and triggering map layer rendering.
 */

import { state } from "../state.js";
import { fetchBlankSpots, fetchBuffers } from "../api.js";
import { escapeHtml } from "../utils/dom.js";
import { renderBufferLayer, renderBlankSpotLayer, clearBlankSpotLayers } from "../map/layers.js";

export function resetBlankSpotsPanel() {
  clearBlankSpotLayers();
  const ids = [
    "bs-area-total",
    "bs-area-unserved",
    "bs-coverage-pct",
    "bs-coverage-no-neigh",
    "bs-fac-inside",
    "bs-fac-neighbours",
    "bs-cross-border-scope",
  ];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "--";
  });
  const warnBox = document.getElementById("bs-area-warning-box");
  if (warnBox) {
    warnBox.style.display = "none";
    warnBox.innerHTML = "";
  }
}

export async function loadDistrictBlankSpots(districtCode, facilityType = "puskesmas_kelurahan") {
  clearBlankSpotLayers();

  try {
    const prov = state.activeProvince || "31";
    const data = await fetchBlankSpots(districtCode, facilityType, prov);
    if (!data) return;

    const areaTotal = document.getElementById("bs-area-total");
    if (areaTotal) areaTotal.textContent = `${data.district_area_km2} km²`;

    const areaUnserved = document.getElementById("bs-area-unserved");
    if (areaUnserved) areaUnserved.textContent = `${data.unserved_area_km2} km²`;

    const cov = data.coverage_pct !== undefined ? data.coverage_pct : (data.coverage_percentage !== undefined ? data.coverage_percentage : "--");
    const covEl = document.getElementById("bs-coverage-pct");
    if (covEl) covEl.textContent = `${cov}%`;

    const covNoNeigh = data.coverage_pct_without_neighbours !== undefined ? data.coverage_pct_without_neighbours : "--";
    const covNoNeighEl = document.getElementById("bs-coverage-no-neigh");
    if (covNoNeighEl) covNoNeighEl.textContent = `${covNoNeigh}%`;

    const facInside = document.getElementById("bs-fac-inside");
    if (facInside) facInside.textContent = `${data.facilities_inside !== undefined ? data.facilities_inside : '--'}`;

    const facNeighbours = document.getElementById("bs-fac-neighbours");
    if (facNeighbours) facNeighbours.textContent = `${data.facilities_from_neighbours !== undefined ? data.facilities_from_neighbours : '--'}`;

    const cbScope = document.getElementById("bs-cross-border-scope");
    if (cbScope) {
      cbScope.textContent = data.cross_border_scope || state.activeRegion?.name || "DKI Jakarta only";
    }

    // Area note warning
    const warnBox = document.getElementById("bs-area-warning-box");
    if (warnBox) {
      if (data.area_note) {
        warnBox.style.display = "block";
        warnBox.innerHTML = `⚠️ <strong>Peringatan Luas Wilayah:</strong> ${escapeHtml(data.area_note)}`;
      } else {
        warnBox.style.display = "none";
      }
    }

    // Render facility buffers
    try {
      const bufData = await fetchBuffers(districtCode, facilityType, prov);
      if (bufData) {
        renderBufferLayer(bufData);
      }
    } catch (bufErr) {
      console.warn("Failed to load facility buffers:", bufErr);
    }

    // Render Blank Spot Polygon
    renderBlankSpotLayer(data);
  } catch (err) {
    console.error("Error loading blank spots:", err);
  }
}
