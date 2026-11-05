/**
 * DISTRICT RESOURCE PROFILING (DKI JAKARTA)
 * MASTER FRONTEND CLIENT - DUAL-SYNC GIS MAP, CHATBOT & RESIZABLE SPLIT VIEW
 */

const API_BASE = window.location.origin;

// Master Application State
const state = {
  districts: [],
  selectedDistrict: null,
  activePillar: null,
  map: null,
  geojsonLayer: null,
  facilityMarkersLayer: null,
  bufferCirclesLayer: null,
  blankSpotLayer: null,
  legendControl: null,
  chatMessages: [],
  isSimulating: false,
  standardsMetadata: []
};

// ==============================================================================
// 1. INITIALIZATION & LIFECYCLE
// ==============================================================================
document.addEventListener("DOMContentLoaded", async () => {
  initResizableSplitter();
  initLeafletMap();
  initTabNavigation();
  initSearchAutocomplete();
  initPillarFilters();
  initChatbot();
  initSimulationControls();

  await loadStandardsMetadata();
  await loadHealthStatus();
  await loadAllDistricts();
  await loadWatchdogTelemetry();
  setInterval(loadWatchdogTelemetry, 15000); // 15s heartbeat
  setInterval(loadHealthStatus, 15000); // 15s health heartbeat
});

// ==============================================================================
// 2. RESIZABLE SPLIT PANE (70% MAP / 30% INFO PANEL)
// ==============================================================================
function initResizableSplitter() {
  const container = document.getElementById("split-layout");
  const leftPane = document.getElementById("map-viewport");
  const resizer = document.getElementById("split-resizer");

  let isDragging = false;

  resizer.addEventListener("mousedown", (e) => {
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
    // Bounds: 45% min, 85% max
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

// ==============================================================================
// 3. LEAFLET WEBGL GIS MAP MANAGER
// ==============================================================================
function initLeafletMap() {
  // Center of DKI Jakarta: Monas [-6.1754, 106.8272]
  state.map = L.map("gis-map-canvas", {
    zoomControl: false,
    attributionControl: true
  }).setView([-6.2088, 106.8456], 12);

  state.map.attributionControl.addAttribution("&copy; <a href='https://www.openstreetmap.org/copyright' target='_blank'>OpenStreetMap contributors</a>");

  // ESRI ArcGIS World Dark Gray Canvas (Zero API Key, Clean Dark Thematic Map)
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16,
    attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
  }).addTo(state.map);

  // ESRI Dark Gray Reference Layer for labels and boundaries
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 16,
    opacity: 0.75
  }).addTo(state.map);

  // Zoom control at top right
  L.control.zoom({ position: "topright" }).addTo(state.map);

  // Layers
  state.facilityMarkersLayer = L.layerGroup().addTo(state.map);
  state.bufferCirclesLayer = L.layerGroup().addTo(state.map);
  state.blankSpotLayer = L.layerGroup().addTo(state.map);

  // Clicking on empty map resets selection
  state.map.on("click", (e) => {
    if (e.originalEvent && (e.originalEvent.target.id === "gis-map-canvas" || (e.originalEvent.target.classList && e.originalEvent.target.classList.contains("leaflet-container")))) {
      unselectDistrict();
    }
  });

  addMapLegend();
}

async function loadStandardsMetadata() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/meta/standards`);
    if (!res.ok) return;
    const standards = await res.json();
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

function addMapLegend() {
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

function getChoroplethColor(score) {
  if (score >= 70) return "#10b981"; // Emerald
  if (score >= 50) return "#84cc16"; // Lime
  if (score >= 35) return "#f59e0b"; // Amber
  if (score >= 20) return "#f97316"; // Orange
  return "#f43f5e";                  // Rose/Red
}

function getDistrictStyle(code) {
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
      color: "#38bdf8", // Glowing cyan border
      dashArray: hasLowCoverage ? "4, 4" : null
    };
  }

  // When unselected: overview choropleth is clearly colored
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

async function loadHealthStatus() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return;
    const data = await res.json();
    const model = data.llm_model || "LLM tidak aktif";
    const modelPill = document.getElementById("nav-llm-model");
    const chatTag = document.getElementById("chat-model-tag");
    const dot = document.getElementById("nav-llm-dot");
    const chatDot = document.getElementById("chat-header-dot");

    if (modelPill) modelPill.textContent = model;
    if (chatTag) chatTag.textContent = model;
    if (dot) {
      if (model === "LLM tidak aktif") {
        dot.style.background = "#6b7280";
        dot.style.boxShadow = "none";
      } else {
        dot.style.background = "#a855f7";
        dot.style.boxShadow = "0 0 8px #a855f7";
      }
    }
    if (chatDot) {
      if (model === "LLM tidak aktif") {
        chatDot.style.background = "#6b7280";
      } else {
        chatDot.style.background = "#a855f7";
      }
    }
  } catch (err) {
    console.warn("Health check error:", err);
  }
}

async function loadAllDistricts() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/districts`);
    const data = await res.json();
    let districtList = data.districts || [];
    if (typeof districtList === "object" && !Array.isArray(districtList)) {
      districtList = Object.values(districtList);
    }
    state.districts = districtList;

    // Load GeoJSON Boundaries (Real administrative polygons)
    const geoRes = await fetch("/data/boundaries/jakarta_44_kecamatan.geojson").catch(() => null);
    let geojsonData = null;
    if (geoRes && geoRes.ok) {
      geojsonData = await geoRes.json();
    } else {
      // Fallback: fetch boundary from first district detail API
      const sample = await fetch(`${API_BASE}/api/v1/districts/31.71.09`);
      const sampleData = await sample.json();
      geojsonData = {
        type: "FeatureCollection",
        features: [{
          type: "Feature",
          properties: { kemendagri_code: "31.71.09", name: sampleData.name },
          geometry: sampleData.boundary_geojson
        }]
      };
    }

    renderDistrictChoropleth(geojsonData);
  } catch (err) {
    console.error("Error loading districts:", err);
  }
}

function renderDistrictChoropleth(geojsonData) {
  if (!geojsonData) return;
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

      layer.bindTooltip(`
        <div class="custom-district-tooltip">
          <strong>${p.name || distInfo.name}</strong> (${code})<br/>
          Populasi: ${(distInfo.population || p.population || 0).toLocaleString()} jiwa <span style="color: #fbbf24; font-size: 10px;">(Sumber data penduduk belum terverifikasi (TODO-VERIFY))</span><br/>
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

// ==============================================================================
// 4. DUAL-SYNC DISTRICT SELECTION
// ==============================================================================
async function selectDistrict(districtCode) {
  try {
    const res = await fetch(`${API_BASE}/api/v1/districts/${districtCode}`);
    if (!res.ok) return;
    const data = await res.json();
    state.selectedDistrict = data;

    // 1. Update Information Panel Header
    document.getElementById("info-district-name").textContent = data.name;
    document.getElementById("info-district-code").textContent = `${data.kemendagri_code} • ${data.city_name || 'DKI Jakarta'}`;
    document.getElementById("info-district-pop").textContent = `${data.population.toLocaleString()} jiwa`;
    const popNoteEl = document.getElementById("info-district-pop-note");
    if (popNoteEl) popNoteEl.textContent = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)";
    document.getElementById("info-district-area").textContent = `Luas administratif (BPS): ${data.area_km2} km²`;

    // 2. Render Scorecard
    renderScorecardTab(data);

    // 3. Render Facilities on Map (point markers only)
    loadDistrictFacilities(districtCode);

    // 4. Load Blank Spots only if currently on Blank Spots tab
    const activeTab = document.querySelector(".info-nav-tabs .info-tab-btn.active")?.getAttribute("data-tab");
    if (activeTab === "blankspots") {
      loadDistrictBlankSpots(districtCode);
    } else {
      state.blankSpotLayer.clearLayers();
      state.bufferCirclesLayer.clearLayers();
    }

    // 5. Update boundary styles across all polygons
    if (state.geojsonLayer) {
      state.geojsonLayer.eachLayer(layer => {
        const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
        if (c) layer.setStyle(getDistrictStyle(c));
      });
    }

    // 6. Dual-Sync: Fly map to boundary
    if (data.boundary_geojson && state.map) {
      const tempLayer = L.geoJSON(data.boundary_geojson);
      state.map.fitBounds(tempLayer.getBounds(), { padding: [50, 50], maxZoom: 14 });
    }

    // 7. Sync simulation population count to district
    if (typeof syncFromSlider === "function") {
      syncFromSlider();
    }
  } catch (err) {
    console.error("Failed to select district:", err);
  }
}

function unselectDistrict() {
  state.selectedDistrict = null;
  state.facilityMarkersLayer.clearLayers();
  state.bufferCirclesLayer.clearLayers();
  state.blankSpotLayer.clearLayers();

  if (state.geojsonLayer) {
    state.geojsonLayer.eachLayer(layer => {
      const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
      if (c) layer.setStyle(getDistrictStyle(c));
    });
  }

  document.getElementById("info-district-name").textContent = "DKI Jakarta";
  document.getElementById("info-district-code").textContent = "Pilih kecamatan pada peta atau cari di atas";
  document.getElementById("info-district-pop").textContent = "10.68 Juta Jiwa";
  const popNoteEl = document.getElementById("info-district-pop-note");
  if (popNoteEl) popNoteEl.textContent = "Sumber data penduduk belum terverifikasi (TODO-VERIFY)";
  document.getElementById("info-district-area").textContent = "44 Kecamatan";

  if (state.map) {
    state.map.setView([-6.2088, 106.8456], 12);
  }
}


function renderScorecardTab(data) {
  const score = data.composite_livability_score !== undefined ? data.composite_livability_score : (data.composite_score || 0);
  const dial = document.getElementById("score-dial-val");
  dial.textContent = typeof score === "number" ? score.toFixed(1) : score;
  dial.style.borderColor = getChoroplethColor(Number(score) || 0);
  dial.style.boxShadow = `0 0 16px ${getChoroplethColor(Number(score) || 0)}55`;

  // Verbatim Composite Note
  const noteBox = document.getElementById("composite-note-box");
  if (data.composite_note) {
    noteBox.style.display = "block";
    noteBox.innerHTML = `<strong>Catatan Skor Komposit:</strong> ${data.composite_note}`;
  } else {
    noteBox.style.display = "none";
  }

  // 4 Pillars mapping
  const pillars = data.pillar_scores || {};
  const BASE_WEIGHTS = {
    lifeline_health: 0.30,
    education: 0.25,
    urban_livability: 0.25,
    mobility_connectivity: 0.20
  };
  const pillarConfigs = [
    { key: "lifeline_health", titleId: "pillar-title-health", icon: "🏥", name: "Lifeline & Kesehatan", cardId: "pillar-card-health", valId: "score-h-val", barId: "score-h-bar", metaId: "pillar-h-meta", defaultScore: data.health_score },
    { key: "education", titleId: "pillar-title-education", icon: "🎓", name: "Human Capital & Pendidikan", cardId: "pillar-card-education", valId: "score-e-val", barId: "score-e-bar", metaId: "pillar-e-meta", defaultScore: data.education_score },
    { key: "urban_livability", titleId: "pillar-title-livability", icon: "🌳", name: "Kualitas Hidup & RTH", cardId: "pillar-card-livability", valId: "score-l-val", barId: "score-l-bar", metaId: "pillar-l-meta", defaultScore: data.livability_score },
    { key: "mobility_connectivity", titleId: "pillar-title-mobility", icon: "🚆", name: "Mobilitas & Transit", cardId: "pillar-card-mobility", valId: "score-m-val", barId: "score-m-bar", metaId: "pillar-m-meta", defaultScore: data.mobility_score }
  ];

  // Single-pillar notice check & active weights computation
  const activePillars = pillarConfigs.filter(cfg => {
    const pData = pillars[cfg.key] || {};
    const scoreVal = pData.score !== undefined ? pData.score : cfg.defaultScore;
    return pData.included_in_composite !== false && scoreVal !== null && scoreVal !== undefined;
  });
  const activeWeightSum = activePillars.reduce((acc, cfg) => acc + (BASE_WEIGHTS[cfg.key] || 0), 0);

  const singlePillarNotice = document.getElementById("single-pillar-notice");
  if (singlePillarNotice) {
    if (activePillars.length === 1) {
      const activeName = pillars[activePillars[0].key]?.label || activePillars[0].key;
      singlePillarNotice.style.display = "block";
      singlePillarNotice.textContent = `Indeks saat ini hanya dari pilar ${activeName} (${data.composite_note || "pilar lain belum memenuhi syarat"}).`;
    } else {
      singlePillarNotice.style.display = "none";
    }
  }

  let allExcluded = [];

  pillarConfigs.forEach(cfg => {
    const pData = pillars[cfg.key] || {};
    const cardEl = document.getElementById(cfg.cardId);
    const valEl = document.getElementById(cfg.valId);
    const barEl = document.getElementById(cfg.barId);
    const metaEl = document.getElementById(cfg.metaId);

    const scoreVal = pData.score !== undefined ? pData.score : cfg.defaultScore;
    const isExcluded = pData.included_in_composite === false || scoreVal === null || scoreVal === undefined;
    const status = pData.status || (isExcluded ? "cakupan data rendah" : "tersedia");
    const dataCoverage = pData.data_coverage !== undefined ? pData.data_coverage : 1.0;

    // Update pillar header with effective weight
    const isIncluded = !isExcluded && activeWeightSum > 0;
    const effWeight = isIncluded ? ((BASE_WEIGHTS[cfg.key] || 0) / activeWeightSum * 100) : 0;
    const effWeightStr = effWeight.toFixed(1).replace(".", ",");
    const titleEl = document.getElementById(cfg.titleId);
    if (titleEl) {
      if (isIncluded) {
        titleEl.textContent = `${cfg.icon} ${cfg.name} (bobot efektif ${effWeightStr}%)`;
      } else {
        titleEl.textContent = `${cfg.icon} ${cfg.name} (bobot efektif 0%)`;
      }
    }

    let statusClass = "tersedia";
    if (status === "cakupan data rendah") statusClass = "cakupan-rendah";
    else if (status === "data tidak tersedia") statusClass = "tidak-tersedia";

    // Numerical value & progress bar & badges
    if (isExcluded) {
      valEl.textContent = "-";
      barEl.style.width = "0%";
      cardEl.classList.add("pillar-excluded");
      metaEl.innerHTML = `
        <span class="pillar-badge-tag badge-status-${statusClass}">${status}</span>
        <span class="pillar-badge-tag badge-excluded">Dikeluarkan dari Komposit (${status})</span>
      `;
    } else {
      valEl.textContent = `${typeof scoreVal === "number" ? scoreVal.toFixed(1) : scoreVal}%`;
      barEl.style.width = `${Math.min(100, Math.max(0, Number(scoreVal) || 0))}%`;
      cardEl.classList.remove("pillar-excluded");
      metaEl.innerHTML = `
        <span class="pillar-badge-tag badge-status-${statusClass}">${status}</span>
        <span class="pillar-badge-tag" style="background: rgba(255,255,255,0.06); color: var(--text-dim);">Cakupan data: ${Math.round(dataCoverage * 100)}%</span>
        <span class="pillar-badge-tag badge-included">Termasuk Komposit</span>
      `;
    }

    // Collect excluded types
    if (pData.types_excluded && Array.isArray(pData.types_excluded)) {
      pData.types_excluded.forEach(ex => {
        allExcluded.push({
          pillar: cfg.key,
          type: ex.facility_type || ex.type || String(ex),
          reason: ex.reason || "Kelengkapan data kota tidak memadai (<44 kecamatan)"
        });
      });
    }
  });

  // Render Collapsible Excluded Types Block
  const excludedBlock = document.getElementById("excluded-types-block");
  const excludedSummary = document.getElementById("excluded-types-summary");
  const excludedList = document.getElementById("excluded-types-list");

  if (allExcluded.length > 0) {
    excludedBlock.style.display = "block";
    excludedSummary.textContent = `Tipe Fasilitas Dikecualikan dari Penilaian (${allExcluded.length})`;
    excludedList.innerHTML = "";
    allExcluded.forEach(item => {
      const el = document.createElement("div");
      el.className = "excluded-type-item";
      el.innerHTML = `<strong>${item.type.replace(/_/g, ' ')}</strong> <span style="color: var(--text-dim);">(${item.pillar})</span>: ${item.reason}`;
      excludedList.appendChild(el);
    });
  } else {
    excludedBlock.style.display = "none";
  }

  // Detailed metrics
  const listContainer = document.getElementById("metrics-breakdown-list");
  listContainer.innerHTML = "";
  const metrics = data.metrics_payload || [];
  metrics.forEach(item => {
    if (item.category === "unclassified" || item.status === "unclassified") return;

    const isScored = item.scored === true;
    const el = document.createElement("div");
    el.className = "pillar-progress-card";

    if (!isScored) {
      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${item.facility_type.replace(/_/g, ' ').toUpperCase()}</span>
          <span style="color: var(--text-muted); font-weight: 600;">Informasi</span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          ${item.existing} titik OSM - tidak dinilai
        </div>
      `;
    } else {
      const isDeficit = item.deficit < 0;
      const badgeColor = isDeficit ? "#f43f5e" : "#10b981";

      let sourceStr = item.source || "";
      if (!sourceStr && state.standardsMetadata) {
        const found = state.standardsMetadata.find(s => s.facility_type === item.facility_type);
        if (found) sourceStr = found.source || "";
      }

      let tableLabel = "SNI";
      const m = sourceStr.match(/Tabel\s+\d+/i);
      if (m) {
        tableLabel = `SNI ${m[0]}`;
      }

      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${item.facility_type.replace(/_/g, ' ').toUpperCase()}</span>
          <span style="color: ${badgeColor}; font-weight: 700;">
            ${isDeficit ? `Defisit ${Math.abs(item.deficit)} unit (menurut data OSM)` : `Terpenuhi (${item.existing}/${item.required})`}
          </span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          Eksisting: ${item.existing} • Kebutuhan (${tableLabel}): ${item.required} • Rasio Kepatuhan: ${item.compliance_pct}%${isDeficit ? ' • <span style="color: #fbbf24;">(Defisit menurut data OSM, bukan data resmi Dapodik/Dinkes)</span>' : ''}
        </div>
      `;
    }
    listContainer.appendChild(el);
  });
}

// ==============================================================================
// 5. PUBLIC FACILITIES & SERVICE BUFFERS
// ==============================================================================
async function loadDistrictFacilities(districtCode) {
  state.facilityMarkersLayer.clearLayers();
  state.bufferCirclesLayer.clearLayers();

  let url = `${API_BASE}/api/v1/facilities?district_code=${districtCode}&limit=100`;
  if (state.activePillar) {
    url += `&pillar=${state.activePillar}`;
  }

  try {
    const res = await fetch(url);
    const data = await res.json();
    const facs = data.facilities || [];

    facs.forEach(f => {
      const lat = f.latitude;
      const lon = f.longitude;
      if (!lat || !lon) return;

      let color = "#38bdf8";
      if (f.pillar === "lifeline_health") color = "#f43f5e";
      else if (f.pillar === "education") color = "#8b5cf6";
      else if (f.pillar === "urban_livability") color = "#10b981";
      else if (f.pillar === "mobility_connectivity") color = "#06b6d4";

      const marker = L.circleMarker([lat, lon], {
        radius: 6,
        fillColor: color,
        color: "#fff",
        weight: 1.5,
        opacity: 1,
        fillOpacity: 0.9
      });

      marker.bindPopup(`
        <div style="font-family: inherit; font-size: 12.5px;">
          <strong style="color: ${color};">${f.name}</strong><br/>
          Jenis: ${f.facility_type.replace(/_/g, ' ')}<br/>
          Pilar: ${f.pillar}
        </div>
      `);

      state.facilityMarkersLayer.addLayer(marker);
    });
  } catch (err) {
    console.error("Error loading facilities:", err);
  }
}

async function loadDistrictBlankSpots(districtCode, facilityType = "puskesmas_kelurahan") {
  state.blankSpotLayer.clearLayers();
  state.bufferCirclesLayer.clearLayers();

  try {
    const res = await fetch(`${API_BASE}/api/v1/spatial/blank-spots?district_code=${districtCode}&facility_type=${facilityType}`);
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("bs-area-total").textContent = `${data.district_area_km2} km²`;
    document.getElementById("bs-area-unserved").textContent = `${data.unserved_area_km2} km²`;
    const cov = data.coverage_pct !== undefined ? data.coverage_pct : (data.coverage_percentage !== undefined ? data.coverage_percentage : "--");
    document.getElementById("bs-coverage-pct").textContent = `${cov}%`;
    const covNoNeigh = data.coverage_pct_without_neighbours !== undefined ? data.coverage_pct_without_neighbours : "--";
    document.getElementById("bs-coverage-no-neigh").textContent = `${covNoNeigh}%`;
    document.getElementById("bs-fac-inside").textContent = `${data.facilities_inside !== undefined ? data.facilities_inside : '--'}`;
    document.getElementById("bs-fac-neighbours").textContent = `${data.facilities_from_neighbours !== undefined ? data.facilities_from_neighbours : '--'}`;
    document.getElementById("bs-cross-border-scope").textContent = `${data.cross_border_scope || 'DKI Jakarta only'}`;

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

    // Render facility buffers with low opacity, thin stroke
    const bufRes = await fetch(`${API_BASE}/api/v1/spatial/buffers?district_code=${districtCode}&facility_type=${facilityType}`);
    if (bufRes.ok) {
      const bufData = await bufRes.json();
      L.geoJSON(bufData, {
        style: {
          color: "#38bdf8",
          weight: 0.8,
          opacity: 0.35,
          fillColor: "#38bdf8",
          fillOpacity: 0.05
        }
      }).addTo(state.bufferCirclesLayer);
    }

    // Render Blank Spot Polygon on top in contrasting red (0.5 opacity)
    if (data.blank_spot_geojson && Object.keys(data.blank_spot_geojson).length > 0) {
      L.geoJSON(data.blank_spot_geojson, {
        style: {
          color: "#dc2626",
          weight: 2,
          fillColor: "#ef4444",
          fillOpacity: 0.5
        }
      }).bindTooltip(`Blank spot ${data.facility_type}: ${data.unserved_area_km2} km² tidak terlayani (${cov}% cakupan)`, { sticky: true }).addTo(state.blankSpotLayer);

      if (state.blankSpotLayer.bringToFront) {
        state.blankSpotLayer.bringToFront();
      }
    }
  } catch (err) {
    console.error("Error loading blank spots:", err);
  }
}

// ==============================================================================
// 6. SEARCH BAR WITH AUTOCOMPLETE
// ==============================================================================
function initSearchAutocomplete() {
  const input = document.getElementById("search-district-input");
  const dropdown = document.getElementById("search-autocomplete-list");

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
        <span><strong>${m.name}</strong> (${m.kemendagri_code})</span>
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

function initPillarFilters() {
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

// ==============================================================================
// 7. INTERACTIVE CHATBOT (ASISTEN TATA RUANG DUAL-SYNC)
// ==============================================================================
function initChatbot() {
  const dock = document.getElementById("chatbot-dock");
  const toggleBtn = document.getElementById("btn-toggle-chat");
  const input = document.getElementById("chat-msg-input");
  const sendBtn = document.getElementById("btn-send-chat");

  toggleBtn.addEventListener("click", () => {
    dock.classList.toggle("collapsed");
    toggleBtn.textContent = dock.classList.contains("collapsed") ? "▲ Expand" : "▼ Minimize";
  });

  sendBtn.addEventListener("click", handleSendMessage);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleSendMessage();
  });

  // Quick Prompt Chips
  document.querySelectorAll(".prompt-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      input.value = chip.textContent;
      handleSendMessage();
    });
  });
}

async function handleSendMessage() {
  const input = document.getElementById("chat-msg-input");
  const text = input.value.trim();
  if (!text) return;

  appendChatMessage("user", text);
  input.value = "";

  // Show thinking indicator
  const thinkingId = appendChatMessage("assistant", "<em>Sedang memproses pemanggilan alat spasial PostGIS & inferensi AI...</em>");

  try {
    const payload = {
      messages: state.chatMessages.map(m => ({ role: m.role, content: m.content })),
      district_context: state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null
    };

    const res = await fetch(`${API_BASE}/api/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: json_stringify(payload)
    });

    const data = await res.json();

    // Update thinking bubble with real response
    const bubbleEl = document.getElementById(thinkingId);
    if (bubbleEl) {
      let html = renderMarkdown(data.reply || "");

      // Guardrail status badge (passed / retried / numeric_fallback)
      if (data.guardrail) {
        const badgeClass = data.guardrail === "passed" ? "passed" : data.guardrail === "retried" ? "retried" : "numeric_fallback";
        const badgeLabel = data.guardrail === "passed" ? "Guardrail: Passed" : data.guardrail === "retried" ? "Guardrail: Retried" : "Guardrail: Fallback";
        html = `
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
            <span style="font-size: 11px; color: var(--text-dim);">Asisten Tata Ruang</span>
            <span class="guardrail-badge ${badgeClass}">${badgeLabel}</span>
          </div>
        ` + html;
      }

      // Validated Citations list
      if (data.citations && Array.isArray(data.citations) && data.citations.length > 0) {
        let citHtml = `
          <div class="chat-citations-container">
            <div class="chat-citations-title">📜 Rujukan Hukum Terverifikasi (${data.citations.length}):</div>
            <ul class="chat-citations-list">
        `;
        data.citations.forEach(c => {
          const title = c.regulation_code ? `${c.regulation_code} - ${c.title || ''}` : (c.title || String(c));
          const art = c.article_reference ? ` <em>(${c.article_reference})</em>` : '';
          citHtml += `<li><strong>${escapeHtml(title)}</strong>${art}</li>`;
        });
        citHtml += `</ul></div>`;
        html += citHtml;
      }

      bubbleEl.innerHTML = html;
    }

    // Execute Map Actions (Dual-View Sync)
    if (data.map_actions && data.map_actions.length > 0) {
      executeMapActions(data.map_actions);
    }
  } catch (err) {
    const bubbleEl = document.getElementById(thinkingId);
    if (bubbleEl) {
      bubbleEl.textContent = `Maaf, terjadi kendala koneksi ke server AI: ${err.message}`;
    }
  }
}

function appendChatMessage(role, content) {
  const history = document.getElementById("chat-history");
  const row = document.createElement("div");
  const msgId = `msg-${Date.now()}`;
  row.className = `chat-message-row ${role}`;
  row.innerHTML = `
    <div class="chat-bubble" id="${msgId}">
      ${role === 'assistant' ? renderMarkdown(content) : escapeHtml(content)}
    </div>
  `;
  history.appendChild(row);
  history.scrollTop = history.scrollHeight;
  state.chatMessages.push({ role, content });
  return msgId;
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderMarkdown(rawText) {
  if (!rawText) return "";
  // Check if it's already an HTML string like our initial assistant greeting or thinking indicator
  if (rawText.startsWith("<em>") || rawText.startsWith("Halo! Saya adalah <strong>")) {
    return rawText;
  }

  const escaped = escapeHtml(rawText);
  const lines = escaped.split("\n");
  let html = "";
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // Headings
    if (/^###\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^###\s+(.*)/, '<h4 style="margin: 8px 0 4px; font-size: 13px; font-weight: 700; color: #fff;">$1</h4>');
      continue;
    }
    if (/^##\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^##\s+(.*)/, '<h3 style="margin: 10px 0 6px; font-size: 14px; font-weight: 800; color: #fff;">$1</h3>');
      continue;
    }
    if (/^#\s+(.*)/.test(line)) {
      if (inList) { html += "</ul>"; inList = false; }
      html += line.replace(/^#\s+(.*)/, '<h2 style="margin: 12px 0 8px; font-size: 15px; font-weight: 800; color: #fff;">$1</h2>');
      continue;
    }

    // Bullet points
    if (/^[\*\-]\s+(.*)/.test(line)) {
      if (!inList) { html += '<ul style="margin: 4px 0 6px 18px; padding: 0;">'; inList = true; }
      const itemContent = line.replace(/^[\*\-]\s+(.*)/, '$1')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 4px;">$1</code>');
      html += `<li style="margin-bottom: 3px;">${itemContent}</li>`;
      continue;
    }

    if (inList) {
      html += "</ul>";
      inList = false;
    }

    // Empty lines
    if (!line.trim()) {
      html += '<div style="height: 6px;"></div>';
      continue;
    }

    // Normal paragraph text
    let formatted = line
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 1px 4px; border-radius: 4px;">$1</code>');
    html += `<p style="margin: 3px 0;">${formatted}</p>`;
  }

  if (inList) {
    html += "</ul>";
  }

  return html;
}

function switchToTab(tabName) {
  const tabs = document.querySelectorAll(".info-tab-btn");
  tabs.forEach(t => {
    if (t.getAttribute("data-tab") === tabName) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });
  document.querySelectorAll(".tab-pane-view").forEach(p => p.style.display = "none");
  const target = document.getElementById(`tab-pane-${tabName}`);
  if (target) target.style.display = "flex";

  if (tabName === "blankspots") {
    if (state.selectedDistrict) {
      loadDistrictBlankSpots(state.selectedDistrict.kemendagri_code);
    }
  } else {
    state.bufferCirclesLayer.clearLayers();
    state.blankSpotLayer.clearLayers();
  }
}

function executeMapActions(actions) {
  actions.forEach(act => {
    if (act.action_type === "fly_to") {
      const code = act.payload && act.payload.district_code;
      if (code) selectDistrict(code);
    } else if (act.action_type === "highlight_blank_spot") {
      const code = (act.payload && act.payload.district_code) || (state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null);
      const ftype = (act.payload && act.payload.facility_type) || "puskesmas_kelurahan";
      if (code) {
        switchToTab("blankspots");
        loadDistrictBlankSpots(code, ftype);
      }
    } else if (act.action_type === "render_simulation_layer") {
      const code = (act.payload && act.payload.district_code) || (state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null);
      const delta = act.payload && act.payload.score_delta;
      switchToTab("simulation");
      if (state.geojsonLayer && code) {
        state.geojsonLayer.eachLayer(layer => {
          const c = layer.feature && layer.feature.properties && layer.feature.properties.kemendagri_code;
          if (c === code) {
            layer.setStyle({
              color: delta < 0 ? "#f43f5e" : "#10b981",
              weight: 3.5,
              fillOpacity: 0.5
            });
          }
        });
      }
      console.log(`[DUAL-SYNC] Simulation Layer Rendered for ${code}: Delta ${delta}`);
    }
  });
}

// ==============================================================================
// 8. WHAT-IF SIMULATION SANDBOX CONTROLS
// ==============================================================================
let syncFromSlider = null;
let syncFromCount = null;

function initSimulationControls() {
  const popSlider = document.getElementById("sim-pop-slider");
  const popVal = document.getElementById("sim-pop-slider-val");
  const popCountInput = document.getElementById("sim-pop-count");
  const runBtn = document.getElementById("btn-run-simulation");

  // Mode radio toggling (hide superblock fields when 'pop' selected)
  const simRadios = document.querySelectorAll('input[name="sim-mode"]');
  const popControls = document.getElementById("sim-pop-controls");
  const sbControls = document.getElementById("sim-superblock-controls");

  function updateSimModeVisibility() {
    const selectedMode = document.querySelector('input[name="sim-mode"]:checked')?.value || "pop";
    if (selectedMode === "pop") {
      if (popControls) popControls.style.display = "block";
      if (sbControls) sbControls.style.display = "none";
    } else {
      if (popControls) popControls.style.display = "none";
      if (sbControls) sbControls.style.display = "flex";
    }
  }

  simRadios.forEach(r => r.addEventListener("change", updateSimModeVisibility));
  updateSimModeVisibility();

  // Dual sync between slider (%) and input count (jiwa)
  syncFromSlider = function() {
    if (!popSlider || !popVal || !popCountInput) return;
    const pct = parseInt(popSlider.value, 10);
    const basePop = (state.selectedDistrict && state.selectedDistrict.population) ? state.selectedDistrict.population : 100000;
    const computedCount = Math.round(basePop * (pct / 100));
    popVal.textContent = `${pct > 0 ? '+' : ''}${pct}%`;
    popCountInput.value = computedCount;
  };

  syncFromCount = function() {
    if (!popSlider || !popVal || !popCountInput) return;
    const count = parseInt(popCountInput.value, 10) || 0;
    const basePop = (state.selectedDistrict && state.selectedDistrict.population) ? state.selectedDistrict.population : 100000;
    const pct = Math.round((count / basePop) * 100);
    const clampedPct = Math.max(-30, Math.min(60, pct));
    popSlider.value = clampedPct;
    popVal.textContent = `${clampedPct > 0 ? '+' : ''}${clampedPct}%`;
  };

  popSlider.addEventListener("input", syncFromSlider);
  popCountInput.addEventListener("input", syncFromCount);
  syncFromSlider();

  runBtn.addEventListener("click", async () => {
    if (!state.selectedDistrict) {
      alert("Pilih kecamatan terlebih dahulu pada peta.");
      return;
    }

    const simType = document.querySelector('input[name="sim-mode"]:checked').value;
    runBtn.textContent = "Menghitung Sandbox...";
    runBtn.disabled = true;

    try {
      if (simType === "pop") {
        const directCount = parseInt(popCountInput?.value || "0", 10);
        const payload = {
          district_code: state.selectedDistrict.kemendagri_code,
          population_shock_percent: 0.0,
          population_shock_count: directCount
        };
        const res = await fetch(`${API_BASE}/api/v1/simulation/what-if`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const delta = await res.json();
        renderSimulationDelta(delta, false, delta.impact_level, delta.assumptions);
      } else {
        // Superblock mode
        const units = parseInt(document.getElementById("sim-sb-units").value) || 3000;
        const siteArea = parseFloat(document.getElementById("sim-sb-area").value) || 20000;
        const payload = {
          district_code: state.selectedDistrict.kemendagri_code,
          project_name: document.getElementById("sim-sb-name").value || "Superblok Hipotetis",
          residential_units: units,
          occupants_per_unit: 3.0,
          site_area_m2: siteArea
        };
        const res = await fetch(`${API_BASE}/api/v1/simulation/superblock`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const impact = await res.json();
        renderSuperblockImpact(impact);
      }
    } catch (err) {
      alert(`Simulasi gagal: ${err.message}`);
    } finally {
      runBtn.textContent = "⚡ Jalankan Simulasi Sandbox";
      runBtn.disabled = false;
    }
  });
}

function renderSimulationDelta(delta, isSuperblock = false, impactLevel = null, assumptions = null) {
  const box = document.getElementById("sim-result-box");
  box.style.display = "flex";

  const impact = impactLevel || delta.impact_level || "Sedang";
  const impactEl = document.getElementById("res-impact-level");
  impactEl.textContent = `Indikasi: ${impact}`;
  if (impact === "Rendah") {
    impactEl.className = "pillar-badge-tag badge-status-tersedia";
  } else if (impact === "Sedang") {
    impactEl.className = "pillar-badge-tag badge-status-cakupan-rendah";
  } else {
    impactEl.className = "pillar-badge-tag badge-status-tidak-tersedia";
  }

  document.getElementById("res-pop-delta").textContent = `+${(delta.population_delta || 0).toLocaleString()}`;
  document.getElementById("res-score-delta").textContent = `${delta.score_delta > 0 ? '+' : ''}${delta.score_delta}`;
  document.getElementById("res-score-delta").style.color = delta.score_delta < 0 ? "#f43f5e" : "#10b981";
  document.getElementById("res-sim-score").textContent = `${delta.simulated_composite_score} pts`;

  // Assumptions small table
  const assumpWrapper = document.getElementById("res-assumptions-wrapper");
  const assumpTableBody = document.querySelector("#res-assumptions-table tbody");
  const assumpData = assumptions || delta.assumptions || {};
  const entries = Object.entries(assumpData);

  if (entries.length > 0) {
    assumpWrapper.style.display = "block";
    assumpTableBody.innerHTML = "";
    entries.forEach(([k, v]) => {
      const row = document.createElement("tr");
      row.innerHTML = `<td>${k}</td><td><strong>${v}</strong></td>`;
      assumpTableBody.appendChild(row);
    });
  } else {
    assumpWrapper.style.display = "none";
  }

  const obList = document.getElementById("res-obligations-list");
  obList.innerHTML = "";
  (delta.legal_recommendations || []).forEach(o => {
    const el = document.createElement("div");
    el.className = "obligation-badge-item";
    el.innerHTML = `<strong>${o.regulation_code} (${o.article_reference}):</strong> ${o.obligation_text} [${o.required_metric}]`;
    obList.appendChild(el);
  });
}

function renderSuperblockImpact(impact) {
  renderSimulationDelta(impact.simulation_delta, true, impact.impact_level, impact.assumptions);
  const obList = document.getElementById("res-obligations-list");
  (impact.developer_legal_obligations || []).forEach(o => {
    const el = document.createElement("div");
    el.className = "obligation-badge-item";
    el.style.borderLeftColor = "#38bdf8";
    el.innerHTML = `<strong>${o.title} (${o.regulation_code}):</strong> ${o.obligation_text} <br/><em>Kebutuhan: ${o.required_metric}</em>`;
    obList.appendChild(el);
  });
}

// ==============================================================================
// 9. WATCHDOG TELEMETRY & TABS
// ==============================================================================
function initTabNavigation() {
  const tabs = document.querySelectorAll(".info-tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.getAttribute("data-tab");
      switchToTab(target);
    });
  });
}

function setWatchdogBadge(el, status) {
  if (!el) return;
  const s = String(status || "--").trim().toUpperCase();
  el.textContent = status || "--";
  if (s === "HEALTHY" || s === "ONLINE" || s === "UP") {
    el.style.background = "rgba(16, 185, 129, 0.2)";
    el.style.color = "#10b981";
    el.style.borderColor = "rgba(16, 185, 129, 0.4)";
  } else if (s === "WARNING" || s === "WARNING_OVERHEAT" || s.includes("STANDBY") || s === "DEGRADED") {
    el.style.background = "rgba(245, 158, 11, 0.2)";
    el.style.color = "#f59e0b";
    el.style.borderColor = "rgba(245, 158, 11, 0.4)";
  } else if (s === "DOWN" || s === "CRITICAL" || s === "ERROR" || s === "OFFLINE" || s === "UNHEALTHY") {
    el.style.background = "rgba(239, 68, 68, 0.2)";
    el.style.color = "#ef4444";
    el.style.borderColor = "rgba(239, 68, 68, 0.4)";
  } else {
    el.style.background = "rgba(107, 114, 128, 0.2)";
    el.style.color = "#9ca3af";
    el.style.borderColor = "rgba(107, 114, 128, 0.3)";
  }
}

function setContainerStatusText(el, statusText) {
  if (!el) return;
  const s = statusText || "--";
  el.textContent = s;
  const lower = s.toLowerCase();
  if (lower.includes("unhealthy") || lower.includes("down") || lower.includes("fail") || lower.includes("exit")) {
    el.style.color = "#ef4444";
  } else if (lower.includes("healthy") || lower.startsWith("up")) {
    el.style.color = "#10b981";
  } else {
    el.style.color = "#9ca3af";
  }
}

function resetWatchdogTelemetry(errorMessage = "Telemetri tidak dapat dimuat") {
  const errBanner = document.getElementById("watchdog-error-banner");
  if (errBanner) {
    if (errorMessage) {
      errBanner.textContent = errorMessage;
      errBanner.style.display = "block";
    } else {
      errBanner.textContent = "";
      errBanner.style.display = "none";
    }
  }

  const gpuName = document.getElementById("watchdog-gpu-name");
  if (gpuName) gpuName.textContent = "--";

  setWatchdogBadge(document.getElementById("watchdog-gpu-status"), "--");

  const vram = document.getElementById("watchdog-vram-usage");
  if (vram) vram.textContent = "--";

  const temp = document.getElementById("watchdog-gpu-temp");
  if (temp) temp.textContent = "--";

  setWatchdogBadge(document.getElementById("watchdog-ai-status"), "--");

  const aiModel = document.getElementById("watchdog-ai-model");
  if (aiModel) aiModel.textContent = "--";

  setContainerStatusText(document.getElementById("watchdog-postgis-status"), "--");
  setContainerStatusText(document.getElementById("watchdog-redis-status"), "--");
}

async function loadWatchdogTelemetry() {
  try {
    const res = await fetch(`${API_BASE}/api/v1/watchdog/telemetry`);
    if (!res.ok) {
      resetWatchdogTelemetry("Telemetri tidak dapat dimuat");
      return;
    }
    const data = await res.json();
    if (!data || typeof data !== "object") {
      resetWatchdogTelemetry("Telemetri tidak dapat dimuat");
      return;
    }

    const errBanner = document.getElementById("watchdog-error-banner");
    if (errBanner) {
      errBanner.textContent = "";
      errBanner.style.display = "none";
    }

    const gpu = data.gpu || {};
    const gpuNameEl = document.getElementById("watchdog-gpu-name");
    if (gpuNameEl) {
      gpuNameEl.textContent = gpu.gpu_name || "tidak tersedia";
    }
    setWatchdogBadge(document.getElementById("watchdog-gpu-status"), gpu.status || "--");

    const vramEl = document.getElementById("watchdog-vram-usage");
    if (vramEl) {
      if (gpu.vram_total_mb && gpu.vram_total_mb > 0) {
        vramEl.textContent = `${gpu.vram_used_mb ?? 0} / ${gpu.vram_total_mb} MB (${gpu.vram_percent ?? 0}%)`;
      } else {
        vramEl.textContent = "--";
      }
    }

    const tempEl = document.getElementById("watchdog-gpu-temp");
    if (tempEl) {
      if (gpu.temperature_celsius != null && gpu.power_watts != null && gpu.status !== "UNAVAILABLE") {
        tempEl.textContent = `${gpu.temperature_celsius}°C • ${gpu.power_watts}W`;
      } else {
        tempEl.textContent = "--";
      }
    }

    const ai = data.ai_engine || {};
    setWatchdogBadge(document.getElementById("watchdog-ai-status"), ai.status || "--");
    const aiModelEl = document.getElementById("watchdog-ai-model");
    if (aiModelEl) {
      aiModelEl.textContent = ai.loaded_model || "--";
    }

    const containers = data.containers || {};
    setContainerStatusText(
      document.getElementById("watchdog-postgis-status"),
      containers.postgis || "--"
    );
    setContainerStatusText(
      document.getElementById("watchdog-redis-status"),
      containers.redis || "--"
    );
  } catch (err) {
    console.warn("Watchdog poller warning:", err);
    resetWatchdogTelemetry("Telemetri tidak dapat dimuat");
  }
}

function json_stringify(obj) {
  return JSON.stringify(obj);
}
