/**
 * map/map.js
 * Leaflet map instance lifecycle, tile layers, choropleth rendering and styles,
 * district selection/deselection, search autocomplete, and splitter resizing.
 */

import { state } from "../state.js";
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM } from "../config.js";
import {
  fetchRegions,
  fetchDistricts,
  fetchBoundariesGeoJSON,
  fetchDistrictDetail,
  fetchDistrictFacilities,
  fetchStandardsMetadata
} from "../api.js";
import { getChoroplethColor, escapeHtml } from "../utils/dom.js";
import {
  renderFacilityMarkers,
  clearSpatialLayers,
  clearBlankSpotLayers
} from "./layers.js";
import { renderScorecard } from "../panels/scorecard.js";
import { loadDistrictBlankSpots } from "../panels/blankspots.js";
import { syncSimulationDistrict } from "../panels/simulation.js";

export function initResizableSplitter() {
  const container = document.getElementById("split-layout");
  const leftPane = document.getElementById("map-viewport");
  const resizer = document.getElementById("split-resizer");
  if (!container || !leftPane || !resizer) return;

  let isDragging = false;

  resizer.addEventListener("mousedown", () => {
    isDragging = true;
    resizer.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const containerRect = container.getBoundingClientRect();
    const pointerX = e.clientX - containerRect.left;
    const totalWidth = containerRect.width;

    let leftPercent = (pointerX / totalWidth) * 100;
    leftPercent = Math.max(45, Math.min(85, leftPercent));

    leftPane.style.flex = `0 0 ${leftPercent}%`;
    if (state.map) state.map.invalidateSize();
  });

  document.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove("dragging");
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      if (state.map) state.map.invalidateSize();
    }
  });
}

export function initLeafletMap() {
  state.map = L.map("gis-map-canvas", {
    zoomControl: false,
    attributionControl: true
  }).setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM);

  state.map.attributionControl.addAttribution("&copy; <a href='https://www.openstreetmap.org/copyright' target='_blank'>OpenStreetMap contributors</a>");

  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16,
    attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
  }).addTo(state.map);

  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16,
    opacity: 0.75
  }).addTo(state.map);

  L.control.zoom({ position: "topright" }).addTo(state.map);

  state.facilityMarkersLayer = L.layerGroup().addTo(state.map);
  state.bufferCirclesLayer = L.layerGroup().addTo(state.map);
  state.blankSpotLayer = L.layerGroup().addTo(state.map);

  state.map.on("click", (e) => {
    if (e.originalEvent && (e.originalEvent.target.id === "gis-map-canvas" || (e.originalEvent.target.classList && e.originalEvent.target.classList.contains("leaflet-container")))) {
      unselectDistrict();
    }
  });

  addMapLegend();
}

export function addMapLegend() {
  if (state.legendControl || !state.map) return;
  state.legendControl = L.control({ position: "bottomleft" });
  state.legendControl.onAdd = function() {
    const div = L.DomUtil.create("div", "info-legend-box");
    div.innerHTML = `
      <div style="font-size: 11px; font-weight: 700; color: #fff; margin-bottom: 5px;">Indeks Kecukupan Fasilitas Dasar</div>
      <div style="display: flex; flex-direction: column; gap: 3px; font-size: 10.5px; color: var(--text-muted);">
        <div style="display: flex; align-items: center; gap: 6px;"><span style="width: 12px; height: 12px; border-radius: 2px; background: #10b981; display: inline-block;"></span> 70 - 100 (Tinggi)</div>
        <div style="display: flex; align-items: center; gap: 6px;"><span style="width: 12px; height: 12px; border-radius: 2px; background: #84cc16; display: inline-block;"></span> 50 - 69 (Sedang)</div>
        <div style="display: flex; align-items: center; gap: 6px;"><span style="width: 12px; height: 12px; border-radius: 2px; background: #f59e0b; display: inline-block;"></span> 35 - 49 (Cukup)</div>
        <div style="display: flex; align-items: center; gap: 6px;"><span style="width: 12px; height: 12px; border-radius: 2px; background: #f97316; display: inline-block;"></span> 20 - 34 (Rendah)</div>
        <div style="display: flex; align-items: center; gap: 6px;"><span style="width: 12px; height: 12px; border-radius: 2px; background: #f43f5e; display: inline-block;"></span> &lt; 20 (Sangat Rendah)</div>
      </div>
    `;
    return div;
  };
  state.legendControl.addTo(state.map);
}

export function getDistrictStyle(code) {
  const isSelected = state.selectedDistrict && state.selectedDistrict.kemendagri_code === code;
  const distInfo = state.districts.find(d => d.kemendagri_code === code) || {};
  const score = distInfo.composite_livability_score || 0;
  const color = getChoroplethColor(score);
  const note = distInfo.composite_note || "";
  const hasLowCoverage = note.includes("dikeluarkan") || note.includes("cakupan data rendah");

  if (isSelected) {
    return {
      fillColor: color,
      fillOpacity: 0.55,
      weight: 3.5,
      opacity: 1,
      color: "#38bdf8",
      dashArray: hasLowCoverage ? "4, 4" : null
    };
  }

  const hasSelection = !!state.selectedDistrict;
  return {
    fillColor: color,
    fillOpacity: hasSelection ? 0.12 : 0.45,
    weight: hasLowCoverage ? 1.5 : 1,
    opacity: hasSelection ? 0.4 : 0.85,
    color: hasLowCoverage ? "#fbbf24" : "rgba(255, 255, 255, 0.4)",
    dashArray: hasLowCoverage ? "4, 4" : null
  };
}

export function renderDistrictChoropleth(geojsonData) {
  if (!geojsonData || !state.map) return;
  if (state.geojsonLayer) state.map.removeLayer(state.geojsonLayer);

  state.geojsonLayer = L.geoJSON(geojsonData, {
    style: (feature) => {
      const code = feature.properties.kemendagri_code;
      return getDistrictStyle(code);
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      const code = p.kemendagri_code;
      const distInfo = state.districts.find(d => d.kemendagri_code === code) || {};
      const score = distInfo.composite_livability_score || 0;
      const note = distInfo.composite_note || "";
      const hasLowCoverage = note.includes("dikeluarkan") || note.includes("cakupan data rendah");
      const lowCoverageHtml = hasLowCoverage
        ? `<div style="color: #fbbf24; font-size: 11px; margin-top: 4px; font-weight: 600;">⚠️ Cakupan data parsial / pilar dikecualikan</div>`
        : "";

      const safeName = escapeHtml(p.name || distInfo.name || "");
      const safeCode = escapeHtml(code || "");
      const popStr = (distInfo.population || p.population || 0).toLocaleString();

      layer.bindTooltip(`
        <div class="custom-district-tooltip">
          <strong>${safeName}</strong> (${safeCode})<br/>
          Populasi: ${popStr} jiwa <span style="color: #fbbf24; font-size: 10px;">(Sumber data penduduk belum terverifikasi (TODO-VERIFY))</span><br/>
          Indeks Kecukupan Fasilitas Dasar: <strong>${score} / 100</strong>
          ${lowCoverageHtml}
        </div>
      `, { sticky: true });

      layer.on("click", (e) => {
        if (e && e.originalEvent) L.DomEvent.stopPropagation(e);
        selectDistrict(code);
      });

      layer.on("mouseover", () => {
        const isSelected = state.selectedDistrict && state.selectedDistrict.kemendagri_code === code;
        if (!isSelected) {
          layer.setStyle({ weight: 2.5, color: "#38bdf8", fillOpacity: 0.35 });
        }
      });

      layer.on("mouseout", () => {
        layer.setStyle(getDistrictStyle(code));
      });
    }
  }).addTo(state.map);
}

export async function loadStandardsMetadata() {
  try {
    const standards = await fetchStandardsMetadata();
    state.standardsMetadata = standards;

    const scoredCount = standards.filter(s => s.scored === true).length;
    const totalCount = standards.length;

    const descEl = document.getElementById("score-meta-standards-desc");
    if (descEl) {
      const infoCount = totalCount - scoredCount;
      descEl.textContent = `Dihitung deterministik via PostGIS berdasarkan ${scoredCount} standar SNI 03-1733-2004 (${infoCount} jenis lain ditampilkan sebagai informasi).`;
    }
  } catch (err) {
    console.warn("Failed to load standards metadata:", err);
  }
}

export async function loadAllDistricts() {
  try {
    let regionConfig = null;
    try {
      const regions = await fetchRegions();
      regionConfig = regions.find(r => r.has_data && r.province_code === (state.activeProvince || "31")) ||
                    regions.find(r => r.has_data) ||
                    regions[0];
      state.activeRegion = regionConfig;
      if (regionConfig && state.map && regionConfig.center && regionConfig.zoom) {
        state.map.setView(regionConfig.center, regionConfig.zoom);
      }
      const brandBadge = document.querySelector(".brand-badge");
      if (brandBadge && regionConfig && regionConfig.name) {
        brandBadge.textContent = regionConfig.name;
      }
    } catch (regErr) {
      console.warn("Could not load regions metadata, using defaults:", regErr);
    }

    const data = await fetchDistricts(state.activeProvince || "31");
    let districtList = data.districts || [];
    if (typeof districtList === "object" && !Array.isArray(districtList)) {
      districtList = Object.values(districtList);
    }
    state.districts = districtList;

    const geojsonUrl = regionConfig?.geojson_url || "/data/boundaries/jakarta_44_kecamatan.geojson";
    const geojsonData = await fetchBoundariesGeoJSON(geojsonUrl);
    renderDistrictChoropleth(geojsonData);
  } catch (err) {
    console.error("Error loading districts:", err);
  }
}

export async function loadDistrictFacilities(districtCode) {
  try {
    const data = await fetchDistrictFacilities(districtCode, state.activePillar);
    renderFacilityMarkers(data.facilities || []);
  } catch (err) {
    console.error("Error loading facilities:", err);
  }
}

export async function selectDistrict(districtCode) {
  try {
    const data = await fetchDistrictDetail(districtCode);
    if (!data) return;
    state.selectedDistrict = data;

    const regionName = state.activeRegion?.name || "DKI Jakarta";

    const nameEl = document.getElementById("info-district-name");
    if (nameEl) nameEl.textContent = data.name;

    const codeEl = document.getElementById("info-district-code");
    if (codeEl) codeEl.textContent = `${data.kemendagri_code} • ${data.city_name || regionName}`;

    const popEl = document.getElementById("info-district-pop");
    if (popEl) popEl.textContent = `${data.population.toLocaleString()} jiwa`;

    const popNoteEl = document.getElementById("info-district-pop-note");
    if (popNoteEl) popNoteEl.textContent = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)";

    const areaEl = document.getElementById("info-district-area");
    if (areaEl) areaEl.textContent = `Luas administratif (BPS): ${data.area_km2} km²`;

    renderScorecard(data);
    await loadDistrictFacilities(districtCode);

    const activeTab = document.querySelector(".info-nav-tabs .info-tab-btn.active")?.getAttribute("data-tab");
    if (activeTab === "blankspots") {
      await loadDistrictBlankSpots(districtCode);
    } else {
      clearBlankSpotLayers();
    }

    if (state.geojsonLayer) {
      state.geojsonLayer.eachLayer(layer => {
        const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
        if (c) layer.setStyle(getDistrictStyle(c));
      });
    }

    if (data.boundary_geojson && state.map) {
      const tempLayer = L.geoJSON(data.boundary_geojson);
      state.map.fitBounds(tempLayer.getBounds(), { padding: [50, 50], maxZoom: 14 });
    }

    syncSimulationDistrict();
  } catch (err) {
    console.error("Failed to select district:", err);
  }
}

export function unselectDistrict() {
  state.selectedDistrict = null;
  clearSpatialLayers();

  if (state.geojsonLayer) {
    state.geojsonLayer.eachLayer(layer => {
      const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
      if (c) layer.setStyle(getDistrictStyle(c));
    });
  }

  const regionName = state.activeRegion?.name || "DKI Jakarta";
  const totalCount = state.districts?.length || 44;

  const nameEl = document.getElementById("info-district-name");
  if (nameEl) nameEl.textContent = regionName;

  const codeEl = document.getElementById("info-district-code");
  if (codeEl) codeEl.textContent = "Pilih kecamatan pada peta atau cari di atas";

  const popEl = document.getElementById("info-district-pop");
  if (popEl) popEl.textContent = "10.68 Juta Jiwa";

  const popNoteEl = document.getElementById("info-district-pop-note");
  if (popNoteEl) popNoteEl.textContent = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)";

  const areaEl = document.getElementById("info-district-area");
  if (areaEl) areaEl.textContent = `${totalCount} Kecamatan ${regionName}`;

  if (state.map) {
    const center = state.activeRegion?.center || DEFAULT_MAP_CENTER;
    const zoom = state.activeRegion?.zoom || DEFAULT_MAP_ZOOM;
    state.map.setView(center, zoom);
  }
}

export function initSearchAutocomplete() {
  const input = document.getElementById("search-district-input");
  const dropdown = document.getElementById("search-autocomplete-list");
  if (!input || !dropdown) return;

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    dropdown.innerHTML = "";
    if (!q) {
      dropdown.style.display = "none";
      return;
    }

    const matches = state.districts.filter(d =>
      d.name.toLowerCase().includes(q) || d.kemendagri_code.includes(q)
    );

    if (matches.length === 0) {
      dropdown.style.display = "none";
      return;
    }

    matches.slice(0, 8).forEach(m => {
      const item = document.createElement("div");
      item.className = "search-autocomplete-item";
      item.innerHTML = `
        <span><strong>${escapeHtml(m.name)}</strong> (${escapeHtml(m.kemendagri_code)})</span>
        <span style="color: ${getChoroplethColor(m.composite_livability_score || 0)}; font-weight: 700;">
          ${m.composite_livability_score || 0} pts
        </span>
      `;
      item.addEventListener("click", () => {
        input.value = m.name;
        dropdown.style.display = "none";
        selectDistrict(m.kemendagri_code);
      });
      dropdown.appendChild(item);
    });

    dropdown.style.display = "block";
  });

  const resetBtn = document.getElementById("btn-reset-map");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      input.value = "";
      dropdown.style.display = "none";
      unselectDistrict();
    });
  }

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = "none";
    }
  });
}

export function initPillarFilters() {
  const chips = document.querySelectorAll(".pillar-chip");
  chips.forEach(chip => {
    chip.addEventListener("click", () => {
      const pillar = chip.getAttribute("data-pillar");
      if (chip.classList.contains("active")) {
        chip.classList.remove("active");
        state.activePillar = null;
      } else {
        chips.forEach(c => c.classList.remove("active"));
        chip.classList.add("active");
        state.activePillar = pillar;
      }
      if (state.selectedDistrict) {
        loadDistrictFacilities(state.selectedDistrict.kemendagri_code);
      }
    });
  });
}
