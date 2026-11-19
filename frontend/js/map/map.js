/**
 * map/map.js
 * Leaflet map instance lifecycle, canvas choropleth rendering and styles,
 * multi-province region switcher with URL ?prov= sync, district selection,
 * search autocomplete, and splitter resizing.
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
import { renderScorecard, resetScorecardPanel, updateProvinceOsmNote } from "../panels/scorecard.js";
import { loadDistrictBlankSpots, resetBlankSpotsPanel } from "../panels/blankspots.js";
import { syncSimulationDistrict, resetSimulationPanel } from "../panels/simulation.js";

function formatProvincePopulation(districts) {
  const total = (districts || []).reduce((acc, d) => acc + (Number(d.population) || 0), 0);
  if (total >= 1_000_000) {
    return `${(total / 1_000_000).toFixed(2)} Juta Jiwa`;
  }
  return `${total.toLocaleString("id-ID")} jiwa`;
}

function getPopulationSourceLabel(districtOrRegion) {
  if (districtOrRegion) {
    if (districtOrRegion.population_source) return districtOrRegion.population_source;
    if (districtOrRegion.population_note) return districtOrRegion.population_note;
  }
  if (state.activeRegion?.population_source) {
    return state.activeRegion.population_source;
  }
  return (state.activeProvince || "31") === "31"
    ? "BPS 2024"
    : "Estimasi model WorldPop R2025A 2024";
}

function updateRegionTexts(regionConfig, districts) {
  const regionName = regionConfig?.name || "DKI Jakarta";
  const count = districts?.length ?? regionConfig?.total_districts ?? 44;
  const popSource = getPopulationSourceLabel(regionConfig);

  const brandBadge = document.querySelector(".brand-badge");
  if (brandBadge) brandBadge.textContent = regionName;

  const navCountEl = document.getElementById("nav-district-count");
  if (navCountEl) navCountEl.textContent = `${count} Kecamatan Loaded`;

  const resetBtn = document.getElementById("btn-reset-map");
  if (resetBtn) {
    resetBtn.textContent = `🔄 Seluruh ${regionName}`;
    resetBtn.title = `Tampilkan Seluruh ${regionName}`;
  }

  const chatWelcomeEl = document.getElementById("chat-welcome-region");
  if (chatWelcomeEl) chatWelcomeEl.textContent = regionName;

  const nameEl = document.getElementById("info-district-name");
  if (nameEl) nameEl.textContent = regionName;

  const codeEl = document.getElementById("info-district-code");
  if (codeEl) codeEl.textContent = "Pilih kecamatan pada peta atau cari di atas";

  const popEl = document.getElementById("info-district-pop");
  if (popEl) popEl.textContent = formatProvincePopulation(districts);

  const popNoteEl = document.getElementById("info-district-pop-note");
  if (popNoteEl) popNoteEl.textContent = popSource;

  const areaEl = document.getElementById("info-district-area");
  if (areaEl) areaEl.textContent = `${count} Kecamatan ${regionName}`;

  const sample =
    (districts || []).find(d => d.name === "Tebet" || d.name === "Coblong" || d.name === "Gondokusuman" || d.name === "Tegalsari") ||
    (districts || []).find(d => d.composite_livability_score !== null) ||
    (districts || [])[0];

  const searchInput = document.getElementById("search-district-input");
  if (searchInput && sample) {
    searchInput.placeholder = `Cari kecamatan atau kode (contoh: ${sample.name}, ${sample.kemendagri_code})...`;
  }

  const promptChips = document.querySelectorAll(".prompt-chip");
  if (sample && promptChips.length >= 4) {
    const sName = sample.name;
    promptChips[0].textContent = `Berapa indeks kecukupan fasilitas ${sName}?`;
    promptChips[1].textContent = `Tampilkan area blank spot puskesmas ${sName}`;
    promptChips[2].textContent = `Simulasi lonjakan 15.000 penduduk di ${sName}`;
    promptChips[3].textContent = `Simulasi dampak superblok 3.000 unit di ${sName}`;
  }

  const sbNameInput = document.getElementById("sim-sb-name");
  if (sbNameInput && !state.selectedDistrict) {
    sbNameInput.value = sample ? `Superblok Kawasan ${sample.name}` : "Superblok Kawasan Terpadu";
  }

  updateProvinceOsmNote(regionConfig?.province_code || state.activeProvince);
}

function fitMapToRegion(regionConfig, { preferBbox = true } = {}) {
  if (!state.map || !regionConfig) return;
  if (preferBbox && Array.isArray(regionConfig.bbox) && regionConfig.bbox.length === 4) {
    const [minLon, minLat, maxLon, maxLat] = regionConfig.bbox;
    state.map.fitBounds(
      [[minLat, minLon], [maxLat, maxLon]],
      { padding: [20, 20] }
    );
    return;
  }
  if (regionConfig.center && regionConfig.zoom) {
    state.map.setView(regionConfig.center, regionConfig.zoom);
  }
}

const SPLIT_STORAGE_KEY = "drp_split_left_pct";
const DEFAULT_SPLIT_PCT = 70;
const KEYBOARD_STEP_PCT = 2;

export function initResizableSplitter() {
  const container = document.getElementById("split-layout");
  const leftPane = document.getElementById("map-viewport");
  const resizer = document.getElementById("split-resizer");
  const sidebar = document.getElementById("info-panel");
  if (!container || !leftPane || !resizer) return;

  resizer.setAttribute("role", "separator");
  resizer.setAttribute("aria-orientation", "vertical");
  if (!resizer.hasAttribute("tabindex")) {
    resizer.setAttribute("tabindex", "0");
  }

  let isDragging = false;
  let activePointerId = null;
  let dragOffsetX = 0;
  let rafId = null;
  let desiredPct = loadStoredSplitPct();

  function loadStoredSplitPct() {
    try {
      const raw = localStorage.getItem(SPLIT_STORAGE_KEY);
      if (raw !== null) {
        const parsed = parseFloat(raw);
        if (Number.isFinite(parsed)) {
          return parsed;
        }
      }
    } catch (_) {
      // Ignore storage access errors (private mode / restricted storage)
    }
    return DEFAULT_SPLIT_PCT;
  }

  function saveSplitPct(pct) {
    try {
      localStorage.setItem(SPLIT_STORAGE_KEY, Number(pct).toFixed(2));
    } catch (_) {
      // Ignore storage access errors
    }
  }

  function scheduleMapInvalidate() {
    if (rafId !== null) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      if (state.map) state.map.invalidateSize();
      syncLegendPositionAboveChat();
    });
  }

  function isHorizontalSplitActive() {
    return window.getComputedStyle(resizer).display !== "none";
  }

  function getSplitBounds() {
    const containerRect = container.getBoundingClientRect();
    const containerWidth = containerRect.width;
    const resizerWidth = resizer.getBoundingClientRect().width || 10;
    const sidebarMinWidth = sidebar
      ? parseFloat(window.getComputedStyle(sidebar).minWidth) || 320
      : 320;
    const maxLeftPx = Math.max(0, Math.floor(containerWidth - sidebarMinWidth - resizerWidth));
    const minLeftPx = Math.min(maxLeftPx, Math.ceil(Math.max(320, containerWidth * 0.45)));
    return { containerRect, containerWidth, resizerWidth, minLeftPx, maxLeftPx };
  }

  function applySplitPx(rawPx, { persist = false, invalidate = true } = {}) {
    if (!isHorizontalSplitActive()) {
      leftPane.style.flex = "";
      return;
    }
    const { containerWidth, minLeftPx, maxLeftPx } = getSplitBounds();
    if (containerWidth <= 0) return;

    const clampedPx = Math.max(minLeftPx, Math.min(maxLeftPx, Math.round(rawPx)));
    leftPane.style.flex = `0 0 ${clampedPx}px`;

    const actualPct = (clampedPx / containerWidth) * 100;
    desiredPct = actualPct;

    const minPct = Math.round((minLeftPx / containerWidth) * 100);
    const maxPct = Math.round((maxLeftPx / containerWidth) * 100);
    resizer.setAttribute("aria-valuemin", String(minPct));
    resizer.setAttribute("aria-valuemax", String(maxPct));
    resizer.setAttribute("aria-valuenow", String(Math.round(actualPct)));

    if (persist) {
      saveSplitPct(actualPct);
    }
    if (invalidate) {
      scheduleMapInvalidate();
    }
  }

  function applySplitPct(pct, options = {}) {
    if (!isHorizontalSplitActive()) {
      leftPane.style.flex = "";
      return;
    }
    const { containerWidth } = getSplitBounds();
    if (containerWidth <= 0) return;
    applySplitPx((pct / 100) * containerWidth, options);
  }

  function endDrag(e) {
    if (!isDragging) return;
    if (e && activePointerId !== null && e.pointerId !== undefined && e.pointerId !== activePointerId) {
      return;
    }
    isDragging = false;
    resizer.classList.remove("dragging");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    if (activePointerId !== null && resizer.releasePointerCapture) {
      try {
        if (!resizer.hasPointerCapture || resizer.hasPointerCapture(activePointerId)) {
          resizer.releasePointerCapture(activePointerId);
        }
      } catch (_) {
        // Ignore if pointer capture already released
      }
    }
    activePointerId = null;
    saveSplitPct(desiredPct);
    scheduleMapInvalidate();
  }

  resizer.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (!isHorizontalSplitActive()) return;
    e.preventDefault();
    isDragging = true;
    activePointerId = e.pointerId;
    const resizerRect = resizer.getBoundingClientRect();
    dragOffsetX = e.clientX - resizerRect.left;
    resizer.classList.add("dragging");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    if (resizer.setPointerCapture) {
      try {
        resizer.setPointerCapture(e.pointerId);
      } catch (_) {
        // Ignore if pointer capture is unavailable for synthetic events
      }
    }
  });

  document.addEventListener("pointermove", (e) => {
    if (!isDragging) return;
    if (activePointerId !== null && e.pointerId !== undefined && e.pointerId !== activePointerId) {
      return;
    }
    const { containerRect } = getSplitBounds();
    const pointerLeftPx = e.clientX - containerRect.left - dragOffsetX;
    applySplitPx(pointerLeftPx, { persist: false, invalidate: true });
  });

  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  resizer.addEventListener("lostpointercapture", () => {
    if (isDragging) endDrag();
  });

  resizer.addEventListener("dblclick", (e) => {
    e.preventDefault();
    applySplitPct(DEFAULT_SPLIT_PCT, { persist: true, invalidate: true });
  });

  resizer.addEventListener("keydown", (e) => {
    if (!isHorizontalSplitActive()) return;
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      applySplitPct(desiredPct - KEYBOARD_STEP_PCT, { persist: true, invalidate: true });
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      applySplitPct(desiredPct + KEYBOARD_STEP_PCT, { persist: true, invalidate: true });
    } else if (e.key === "Home") {
      e.preventDefault();
      applySplitPct(0, { persist: true, invalidate: true });
    } else if (e.key === "End") {
      e.preventDefault();
      applySplitPct(100, { persist: true, invalidate: true });
    }
  });

  window.addEventListener("resize", () => {
    applySplitPct(desiredPct, { persist: false, invalidate: true });
  });

  // Restore initial split with clamping (no map yet during DOMContentLoaded init order)
  applySplitPct(desiredPct, { persist: false, invalidate: false });
}

export function initLeafletMap() {
  state.choroplethRenderer = L.canvas({ padding: 0.5 });

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

const LEGEND_COLLAPSED_STORAGE_KEY = "drp_legend_collapsed";
let legendObserverInitialized = false;

function getInitialLegendCollapsed() {
  try {
    const saved = localStorage.getItem(LEGEND_COLLAPSED_STORAGE_KEY);
    if (saved === "true") return true;
    if (saved === "false") return false;
  } catch (_) {
    // Ignore storage access errors (private mode / restricted storage)
  }
  return window.innerWidth < 768 || window.innerHeight < 700;
}

export function syncLegendPositionAboveChat() {
  const mapViewport = document.getElementById("map-viewport");
  const chatDock = document.getElementById("chatbot-dock");
  const legendContainer = mapViewport?.querySelector(".leaflet-bottom.leaflet-left");
  if (!mapViewport || !legendContainer) return;

  if (!chatDock) {
    legendContainer.style.bottom = "";
    return;
  }

  const vpRect = mapViewport.getBoundingClientRect();
  const chatRect = chatDock.getBoundingClientRect();
  const legendBox = legendContainer.querySelector(".info-legend-box");
  const legendRect = legendBox ? legendBox.getBoundingClientRect() : null;

  const legendRight = legendRect && legendRect.width > 0 ? legendRect.right : vpRect.left + 230;
  const overlapsHorizontally =
    window.innerWidth < 768 || (chatRect.width > 0 && legendRight + 8 > chatRect.left);

  if (overlapsHorizontally && chatRect.height > 0) {
    const chatBottomGap = Math.max(0, vpRect.bottom - chatRect.top);
    const headerEl = mapViewport.querySelector(".map-floating-header");
    const headerBottom = headerEl ? headerEl.getBoundingClientRect().bottom + 6 : vpRect.top + 8;
    const legendHeight = legendRect ? legendRect.height : 40;
    const desiredBottom = Math.ceil(chatBottomGap + 8);
    const maxBottom = Math.max(0, Math.floor(vpRect.bottom - headerBottom - legendHeight));
    legendContainer.style.bottom = `${Math.min(desiredBottom, maxBottom)}px`;
  } else {
    legendContainer.style.bottom = "";
  }
}

function initLegendChatObserver() {
  if (legendObserverInitialized) return;
  legendObserverInitialized = true;

  const chatDock = document.getElementById("chatbot-dock");
  const mapViewport = document.getElementById("map-viewport");
  if (typeof ResizeObserver !== "undefined") {
    const ro = new ResizeObserver(() => syncLegendPositionAboveChat());
    if (chatDock) ro.observe(chatDock);
    if (mapViewport) ro.observe(mapViewport);
  }
  window.addEventListener("resize", syncLegendPositionAboveChat);
}

export function addMapLegend() {
  if (state.legendControl || !state.map) return;
  state.legendControl = L.control({ position: "bottomleft" });
  state.legendControl.onAdd = function() {
    const div = L.DomUtil.create("div", "info-legend-box");
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);

    const isCollapsed = getInitialLegendCollapsed();
    if (isCollapsed) {
      div.classList.add("collapsed");
    }

    div.innerHTML = `
      <button type="button" class="legend-toggle-btn" id="map-legend-toggle" aria-expanded="${!isCollapsed}" aria-controls="map-legend-body">
        <span class="legend-title">Indeks Kecukupan Fasilitas Dasar</span>
        <span class="legend-chevron" aria-hidden="true">▾</span>
      </button>
      <div class="legend-body" id="map-legend-body">
        <div class="legend-item"><span class="legend-swatch legend-swatch-high"></span> 70 - 100 (Tinggi)</div>
        <div class="legend-item"><span class="legend-swatch legend-swatch-medium"></span> 50 - 69 (Sedang)</div>
        <div class="legend-item"><span class="legend-swatch legend-swatch-fair"></span> 35 - 49 (Cukup)</div>
        <div class="legend-item"><span class="legend-swatch legend-swatch-low"></span> 20 - 34 (Rendah)</div>
        <div class="legend-item"><span class="legend-swatch legend-swatch-very-low"></span> &lt; 20 (Sangat Rendah)</div>
        <div class="legend-item"><span class="legend-swatch-insufficient"></span> Data tidak memadai (cakupan OSM)</div>
      </div>
    `;

    const toggleBtn = div.querySelector("#map-legend-toggle");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const nextCollapsed = !div.classList.contains("collapsed");
        div.classList.toggle("collapsed", nextCollapsed);
        toggleBtn.setAttribute("aria-expanded", String(!nextCollapsed));
        try {
          localStorage.setItem(LEGEND_COLLAPSED_STORAGE_KEY, String(nextCollapsed));
        } catch (_) {
          // Ignore storage access errors
        }
        syncLegendPositionAboveChat();
      });
    }

    requestAnimationFrame(() => syncLegendPositionAboveChat());
    return div;
  };
  state.legendControl.addTo(state.map);
  initLegendChatObserver();
}

export function getDistrictStyle(code) {
  const isSelected = state.selectedDistrict && state.selectedDistrict.kemendagri_code === code;
  const distInfo = state.districtByCode.get(code) || {};
  const rawScore = distInfo.composite_livability_score;
  const isInsufficientData =
    rawScore === null ||
    rawScore === undefined ||
    distInfo.score_status === "Data tidak memadai";

  const color = isInsufficientData ? "#64748b" : getChoroplethColor(rawScore);
  const note = distInfo.composite_note || "";
  const hasLowCoverage =
    isInsufficientData ||
    note.includes("dikeluarkan") ||
    note.includes("cakupan data rendah") ||
    note.includes("minimal 2 jenis");

  if (isSelected) {
    return {
      fillColor: color,
      fillOpacity: 0.55,
      weight: 3.5,
      opacity: 1,
      color: "#38bdf8",
      dashArray: isInsufficientData ? "4, 4" : (hasLowCoverage ? "4, 4" : null)
    };
  }

  const hasSelection = !!state.selectedDistrict;
  return {
    fillColor: color,
    fillOpacity: hasSelection ? 0.14 : (isInsufficientData ? 0.35 : 0.45),
    weight: isInsufficientData ? 1.4 : (hasLowCoverage ? 1.5 : 1),
    opacity: hasSelection ? 0.45 : 0.85,
    color: isInsufficientData ? "#94a3b8" : (hasLowCoverage ? "#fbbf24" : "rgba(255, 255, 255, 0.4)"),
    dashArray: (isInsufficientData || hasLowCoverage) ? "4, 4" : null
  };
}

function buildDistrictTooltipHtml(feature) {
  const p = feature.properties || {};
  const code = p.kemendagri_code || "";
  const distInfo = state.districtByCode.get(code) || {};
  const rawScore = distInfo.composite_livability_score;
  const isInsufficientData =
    rawScore === null ||
    rawScore === undefined ||
    distInfo.score_status === "Data tidak memadai";

  const note = distInfo.composite_note || "";
  const hasLowCoverage = !isInsufficientData && (note.includes("dikeluarkan") || note.includes("cakupan data rendah"));

  const safeName = escapeHtml(p.name || distInfo.name || "");
  const safeCode = escapeHtml(code);
  const popStr = (distInfo.population ?? p.population ?? 0).toLocaleString("id-ID");
  const popLabel = escapeHtml(getPopulationSourceLabel(distInfo));

  const scoreLine = isInsufficientData
    ? `Indeks Kecukupan Fasilitas Dasar: <strong style="color: #cbd5e1;">Data tidak memadai (cakupan OSM)</strong>`
    : `Indeks Kecukupan Fasilitas Dasar: <strong>${Number(rawScore).toFixed(2)} / 100</strong>`;

  const lowCoverageHtml = hasLowCoverage
    ? `<div style="color: #fbbf24; font-size: 11px; margin-top: 4px; font-weight: 600;">⚠️ Cakupan data parsial / pilar dikecualikan</div>`
    : "";

  return `
    <div class="custom-district-tooltip">
      <strong>${safeName}</strong> (${safeCode})<br/>
      Populasi: ${popStr} jiwa <span style="color: #94a3b8; font-size: 10px;">(${popLabel})</span><br/>
      ${scoreLine}
      ${lowCoverageHtml}
    </div>
  `;
}

export function renderDistrictChoropleth(geojsonData) {
  if (!geojsonData || !state.map) return;
  if (state.geojsonLayer) state.map.removeLayer(state.geojsonLayer);

  state.geojsonLayer = L.geoJSON(geojsonData, {
    renderer: state.choroplethRenderer,
    style: (feature) => {
      const code = feature.properties?.kemendagri_code;
      return getDistrictStyle(code);
    },
    onEachFeature: (feature, layer) => {
      const code = feature.properties?.kemendagri_code;

      // Lazy tooltip generator avoids upfront DOM/HTML creation across 666+ features
      layer.bindTooltip(() => buildDistrictTooltipHtml(feature), { sticky: true });

      layer.on("click", (e) => {
        if (e && e.originalEvent) L.DomEvent.stopPropagation(e);
        selectDistrict(code);
      });

      layer.on("mouseover", () => {
        const isSelected = state.selectedDistrict && state.selectedDistrict.kemendagri_code === code;
        if (!isSelected) {
          layer.setStyle({ weight: 2.5, color: "#38bdf8", fillOpacity: 0.38 });
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

const REGION_ISLAND_GROUPS = [
  { label: "Sumatra", codes: ["11", "12", "13", "14", "15", "16", "17", "18", "19", "21"] },
  { label: "Jawa", codes: ["31", "32", "33", "34", "35", "36"] },
  { label: "Bali & Nusa Tenggara", codes: ["51", "52", "53"] },
  { label: "Kalimantan", codes: ["61", "62", "63", "64", "65"] },
  { label: "Sulawesi", codes: ["71", "72", "73", "74", "75", "76"] },
  { label: "Maluku", codes: ["81", "82"] },
  { label: "Papua", codes: ["91", "92", "93", "94", "95", "96"] }
];

function createRegionOption(r, activeCode) {
  const opt = document.createElement("option");
  opt.value = r.province_code;
  const isActive = r.status === "Active";
  opt.disabled = !isActive;
  opt.textContent = isActive ? r.name : `${r.name} (${r.status})`;
  if (r.province_code === activeCode) {
    opt.selected = true;
  }
  return opt;
}

function populateRegionSelect(regions, activeCode) {
  const select = document.getElementById("region-select");
  if (!select) return;

  select.innerHTML = "";
  const regionByCode = new Map();
  (regions || []).forEach(r => {
    if (r && r.province_code) regionByCode.set(r.province_code, r);
  });

  const placed = new Set();
  REGION_ISLAND_GROUPS.forEach(group => {
    const items = group.codes
      .map(code => regionByCode.get(code))
      .filter(Boolean);
    if (items.length === 0) return;

    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;
    items.forEach(r => {
      placed.add(r.province_code);
      optgroup.appendChild(createRegionOption(r, activeCode));
    });
    select.appendChild(optgroup);
  });

  (regions || []).forEach(r => {
    if (r && !placed.has(r.province_code)) {
      select.appendChild(createRegionOption(r, activeCode));
    }
  });

  if (!select.dataset.bound) {
    select.addEventListener("change", async (e) => {
      const targetProv = e.target.value;
      if (targetProv && targetProv !== state.activeProvince) {
        await switchProvince(targetProv);
      }
    });
    select.dataset.bound = "true";
  }
}

function clearSelectionAndPanels() {
  state.selectedDistrict = null;
  clearSpatialLayers();
  const searchInput = document.getElementById("search-district-input");
  if (searchInput) searchInput.value = "";
  const dropdown = document.getElementById("search-autocomplete-list");
  if (dropdown) {
    dropdown.innerHTML = "";
    dropdown.style.display = "none";
  }
  resetBlankSpotsPanel();
  resetSimulationPanel();
  resetScorecardPanel();
}

export async function switchProvince(provinceCode, { updateUrl = true, fitBbox = true } = {}) {
  const code = String(provinceCode || "31").trim();
  const regionConfig =
    (state.regions || []).find(r => r.province_code === code && r.status === "Active") ||
    (state.regions || []).find(r => r.status === "Active") ||
    (state.regions || [])[0];

  const resolvedCode = regionConfig?.province_code || code;
  state.activeProvince = resolvedCode;
  state.activeRegion = regionConfig || null;

  const select = document.getElementById("region-select");
  if (select && select.value !== resolvedCode) {
    select.value = resolvedCode;
  }

  if (updateUrl && window.history?.replaceState) {
    const url = new URL(window.location.href);
    url.searchParams.set("prov", resolvedCode);
    window.history.replaceState({}, "", url.toString());
  }

  clearSelectionAndPanels();

  const data = await fetchDistricts(resolvedCode);
  let districtList = data.districts || [];
  if (typeof districtList === "object" && !Array.isArray(districtList)) {
    districtList = Object.values(districtList);
  }
  state.districts = districtList;
  state.districtByCode = new Map();
  districtList.forEach(d => {
    if (d.kemendagri_code) state.districtByCode.set(d.kemendagri_code, d);
  });

  updateRegionTexts(regionConfig, districtList);

  const geojsonUrl = regionConfig?.geojson_url || "/data/boundaries/jakarta_44_kecamatan.geojson";
  const geojsonData = await fetchBoundariesGeoJSON(geojsonUrl);
  renderDistrictChoropleth(geojsonData);

  if (regionConfig && state.map) {
    fitMapToRegion(regionConfig, { preferBbox: fitBbox || resolvedCode !== "31" });
  }
}

export async function loadAllDistricts() {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const requestedProv = urlParams.get("prov");

    let regions = [];
    try {
      regions = await fetchRegions();
      state.regions = regions;
    } catch (regErr) {
      console.warn("Could not load regions metadata, using defaults:", regErr);
    }

    const activeRegions = regions.filter(r => r.status === "Active");
    const matchedRequested = requestedProv
      ? activeRegions.find(r => r.province_code === requestedProv.trim())
      : null;

    const initialRegion =
      matchedRequested ||
      activeRegions.find(r => r.province_code === "31") ||
      activeRegions[0] ||
      regions[0];

    const initialProv = initialRegion?.province_code || "31";
    populateRegionSelect(regions, initialProv);

    await switchProvince(initialProv, {
      updateUrl: Boolean(matchedRequested),
      fitBbox: Boolean(matchedRequested),
    });
  } catch (err) {
    console.error("Error loading districts:", err);
  }
}

export async function loadDistrictFacilities(districtCode) {
  try {
    const data = await fetchDistrictFacilities(
      districtCode,
      state.activePillar,
      state.activeProvince
    );
    renderFacilityMarkers(data.facilities || []);
  } catch (err) {
    console.error("Error loading facilities:", err);
  }
}

export async function selectDistrict(districtCode) {
  try {
    const data = await fetchDistrictDetail(districtCode, state.activeProvince);
    if (!data) return;
    state.selectedDistrict = data;

    const regionName = state.activeRegion?.name || "DKI Jakarta";
    const popLabel = getPopulationSourceLabel(data);

    const nameEl = document.getElementById("info-district-name");
    if (nameEl) nameEl.textContent = data.name;

    const codeEl = document.getElementById("info-district-code");
    if (codeEl) codeEl.textContent = `${data.kemendagri_code} • ${data.city_name || regionName}`;

    const popEl = document.getElementById("info-district-pop");
    if (popEl) popEl.textContent = `${(data.population || 0).toLocaleString("id-ID")} jiwa`;

    const popNoteEl = document.getElementById("info-district-pop-note");
    if (popNoteEl) popNoteEl.textContent = popLabel;

    const areaEl = document.getElementById("info-district-area");
    if (areaEl) areaEl.textContent = `Luas wilayah: ${data.area_km2} km²`;

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
  resetBlankSpotsPanel();
  resetSimulationPanel();
  resetScorecardPanel();

  if (state.geojsonLayer) {
    state.geojsonLayer.eachLayer(layer => {
      const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
      if (c) layer.setStyle(getDistrictStyle(c));
    });
  }

  updateRegionTexts(state.activeRegion, state.districts);

  if (state.map) {
    fitMapToRegion(state.activeRegion, {
      preferBbox: (state.activeProvince || "31") !== "31"
    });
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
      (d.name || "").toLowerCase().includes(q) ||
      (d.kemendagri_code || "").includes(q) ||
      (d.city_name || "").toLowerCase().includes(q)
    );

    if (matches.length === 0) {
      dropdown.style.display = "none";
      return;
    }

    matches.slice(0, 8).forEach(m => {
      const item = document.createElement("div");
      item.className = "search-autocomplete-item";
      const rawScore = m.composite_livability_score;
      const isNull = rawScore === null || rawScore === undefined;
      const scoreLabel = isNull ? "Data tidak memadai" : `${Number(rawScore).toFixed(1)} pts`;
      const scoreColor = getChoroplethColor(rawScore);
      const citySuffix = m.city_name ? ` • ${escapeHtml(m.city_name)}` : "";

      item.innerHTML = `
        <span><strong>${escapeHtml(m.name)}</strong> (${escapeHtml(m.kemendagri_code)}${citySuffix})</span>
        <span style="color: ${scoreColor}; font-weight: 700;">
          ${scoreLabel}
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
