/**
 * panels/scorecard.js
 * Renders district score dial, coverage gate badge, province OSM caveat note,
 * verbatim composite note, 4-pillar progress bars with effective weights and exclusion tags,
 * and granular facility compliance audit list.
 */

import { state } from "../state.js";
import { BASE_PILLAR_WEIGHTS } from "../config.js";
import { getChoroplethColor, escapeHtml } from "../utils/dom.js";

const PROVINCE_OSM_CAVEAT =
  "Data fasilitas OSM di luar DKI belum lengkap; skor cenderung lebih rendah dari kondisi nyata.";

export function updateProvinceOsmNote(provinceCode) {
  const noteEl = document.getElementById("province-osm-note");
  if (!noteEl) return;
  const prov = String(provinceCode || state.activeProvince || "31");
  if (prov !== "31") {
    noteEl.textContent = PROVINCE_OSM_CAVEAT;
    noteEl.style.display = "block";
  } else {
    noteEl.textContent = "";
    noteEl.style.display = "none";
  }
}

export function resetScorecardPanel() {
  updateProvinceOsmNote(state.activeProvince);

  const covBadge = document.getElementById("district-coverage-badge");
  if (covBadge) {
    covBadge.style.display = "none";
    covBadge.textContent = "";
    covBadge.className = "coverage-badge";
  }

  const dial = document.getElementById("score-dial-val");
  if (dial) {
    dial.textContent = "--";
    dial.classList.remove("insufficient");
    dial.style.borderColor = "";
    dial.style.boxShadow = "";
  }

  const titleEl = document.getElementById("score-meta-title");
  if (titleEl) titleEl.textContent = "Indeks Kecukupan Fasilitas Dasar (0-100)";

  const gatedBox = document.getElementById("gated-coverage-box");
  if (gatedBox) {
    gatedBox.style.display = "none";
    gatedBox.innerHTML = "";
  }

  const noteBox = document.getElementById("composite-note-box");
  if (noteBox) {
    noteBox.style.display = "none";
    noteBox.innerHTML = "";
  }

  const singlePillarNotice = document.getElementById("single-pillar-notice");
  if (singlePillarNotice) {
    singlePillarNotice.style.display = "none";
    singlePillarNotice.textContent = "";
  }

  const excludedBlock = document.getElementById("excluded-types-block");
  if (excludedBlock) excludedBlock.style.display = "none";
  const excludedList = document.getElementById("excluded-types-list");
  if (excludedList) excludedList.innerHTML = "";

  const listContainer = document.getElementById("metrics-breakdown-list");
  if (listContainer) listContainer.innerHTML = "";

  const pillarDefaults = [
    { cardId: "pillar-card-health", valId: "score-h-val", barId: "score-h-bar", metaId: "pillar-h-meta", titleId: "pillar-title-health", title: "🏥 Lifeline & Kesehatan (30%)" },
    { cardId: "pillar-card-education", valId: "score-e-val", barId: "score-e-bar", metaId: "pillar-e-meta", titleId: "pillar-title-education", title: "🎓 Human Capital & Pendidikan (25%)" },
    { cardId: "pillar-card-livability", valId: "score-l-val", barId: "score-l-bar", metaId: "pillar-l-meta", titleId: "pillar-title-livability", title: "🌳 Kualitas Hidup & RTH (25%)" },
    { cardId: "pillar-card-mobility", valId: "score-m-val", barId: "score-m-bar", metaId: "pillar-m-meta", titleId: "pillar-title-mobility", title: "🚆 Mobilitas & Transit (20%)" },
  ];
  pillarDefaults.forEach(p => {
    const card = document.getElementById(p.cardId);
    if (card) card.classList.remove("pillar-excluded");
    const val = document.getElementById(p.valId);
    if (val) val.textContent = "--";
    const bar = document.getElementById(p.barId);
    if (bar) bar.style.width = "0%";
    const meta = document.getElementById(p.metaId);
    if (meta) meta.innerHTML = "";
    const t = document.getElementById(p.titleId);
    if (t) t.textContent = p.title;
  });
}

export function renderScorecard(data) {
  updateProvinceOsmNote(data.province_code || state.activeProvince);

  // Coverage badge for every kecamatan (memadai / tidak memadai, mapped SD vs required SD)
  const covBadge = document.getElementById("district-coverage-badge");
  const osmCov = data.coverage?.osm_coverage;
  if (covBadge) {
    if (osmCov) {
      const isMemadai = osmCov.status === "memadai";
      const mapped = osmCov.mapped_sd ?? 0;
      const required = osmCov.required_sd ?? 0;
      covBadge.className = `coverage-badge ${isMemadai ? "memadai" : "tidak-memadai"}`;
      covBadge.textContent = `Cakupan OSM: ${isMemadai ? "memadai" : "tidak memadai"} (SD: ${mapped} / ${required} dibutuhkan)`;
      covBadge.style.display = "inline-flex";
    } else {
      covBadge.style.display = "none";
    }
  }

  const rawScore = data.composite_livability_score !== undefined ? data.composite_livability_score : data.composite_score;
  const isGatedOrNull = rawScore === null || rawScore === undefined || data.score_status === "Data tidak memadai";

  const dial = document.getElementById("score-dial-val");
  const titleEl = document.getElementById("score-meta-title");
  if (dial) {
    if (isGatedOrNull) {
      dial.textContent = "N/A";
      dial.classList.add("insufficient");
      dial.style.borderColor = "#64748b";
      dial.style.boxShadow = "none";
      if (titleEl) titleEl.textContent = "Data tidak memadai";
    } else {
      const numScore = Number(rawScore);
      dial.textContent = Number.isFinite(numScore) ? numScore.toFixed(1) : String(rawScore);
      dial.classList.remove("insufficient");
      dial.style.borderColor = getChoroplethColor(numScore);
      dial.style.boxShadow = `0 0 16px ${getChoroplethColor(numScore)}55`;
      if (titleEl) titleEl.textContent = "Indeks Kecukupan Fasilitas Dasar (0-100)";
    }
  }

  // Gated coverage reason box
  const gatedBox = document.getElementById("gated-coverage-box");
  if (gatedBox) {
    if (isGatedOrNull) {
      const gatedMetric = (data.metrics_payload || []).find(
        m => m.data_availability === "insufficient_local"
      );
      const reason =
        gatedMetric?.availability_reason ||
        data.composite_note ||
        osmCov?.rule ||
        "Cakupan data OSM tidak memadai untuk perhitungan skor.";
      gatedBox.style.display = "block";
      gatedBox.innerHTML = `<strong>Data tidak memadai</strong> — ${escapeHtml(reason)}`;
    } else {
      gatedBox.style.display = "none";
      gatedBox.innerHTML = "";
    }
  }

  // Verbatim Composite Note
  const noteBox = document.getElementById("composite-note-box");
  if (noteBox) {
    if (data.composite_note && !isGatedOrNull) {
      noteBox.style.display = "block";
      noteBox.innerHTML = `<strong>Catatan Skor Komposit:</strong> ${escapeHtml(data.composite_note)}`;
    } else {
      noteBox.style.display = "none";
    }
  }

  // 4 Pillars mapping
  const pillars = data.pillar_scores || {};
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
  const activeWeightSum = activePillars.reduce((acc, cfg) => acc + (BASE_PILLAR_WEIGHTS[cfg.key] || 0), 0);

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

  const allExcluded = [];

  pillarConfigs.forEach(cfg => {
    const pData = pillars[cfg.key] || {};
    const cardEl = document.getElementById(cfg.cardId);
    const valEl = document.getElementById(cfg.valId);
    const barEl = document.getElementById(cfg.barId);
    const metaEl = document.getElementById(cfg.metaId);

    const scoreVal = pData.score !== undefined ? pData.score : cfg.defaultScore;
    const isExcluded = pData.included_in_composite === false || scoreVal === null || scoreVal === undefined;
    const status = pData.status || (isExcluded ? (isGatedOrNull ? "data tidak memadai" : "cakupan data rendah") : "tersedia");
    const dataCoverage = pData.data_coverage !== undefined ? pData.data_coverage : 1.0;

    // Update pillar header with effective weight
    const isIncluded = !isExcluded && activeWeightSum > 0;
    const effWeight = isIncluded ? ((BASE_PILLAR_WEIGHTS[cfg.key] || 0) / activeWeightSum * 100) : 0;
    const effWeightStr = effWeight.toFixed(1).replace(".", ",");
    const pTitleEl = document.getElementById(cfg.titleId);
    if (pTitleEl) {
      if (isIncluded) {
        pTitleEl.textContent = `${cfg.icon} ${cfg.name} (bobot efektif ${effWeightStr}%)`;
      } else {
        pTitleEl.textContent = `${cfg.icon} ${cfg.name} (bobot efektif 0%)`;
      }
    }

    let statusClass = "tersedia";
    if (status === "cakupan data rendah") statusClass = "cakupan-rendah";
    else if (status === "data tidak tersedia" || status === "data tidak memadai") statusClass = "tidak-tersedia";

    if (valEl && barEl && cardEl && metaEl) {
      if (isExcluded) {
        valEl.textContent = "-";
        barEl.style.width = "0%";
        cardEl.classList.add("pillar-excluded");
        metaEl.innerHTML = `
          <span class="pillar-badge-tag badge-status-${statusClass}">${escapeHtml(status)}</span>
          <span class="pillar-badge-tag badge-excluded">Dikeluarkan dari Komposit (${escapeHtml(status)})</span>
        `;
      } else {
        valEl.textContent = `${typeof scoreVal === "number" ? scoreVal.toFixed(1) : scoreVal}%`;
        barEl.style.width = `${Math.min(100, Math.max(0, Number(scoreVal) || 0))}%`;
        cardEl.classList.remove("pillar-excluded");
        metaEl.innerHTML = `
          <span class="pillar-badge-tag badge-status-${statusClass}">${escapeHtml(status)}</span>
          <span class="pillar-badge-tag" style="background: rgba(255,255,255,0.06); color: var(--text-dim);">Cakupan data: ${Math.round(dataCoverage * 100)}%</span>
          <span class="pillar-badge-tag badge-included">Termasuk Komposit</span>
        `;
      }
    }

    // Collect excluded types
    if (pData.types_excluded && Array.isArray(pData.types_excluded)) {
      pData.types_excluded.forEach(ex => {
        allExcluded.push({
          pillar: cfg.key,
          type: ex.facility_type || ex.type || String(ex),
          reason: ex.reason || "Kelengkapan data provinsi tidak memadai"
        });
      });
    }
  });

  // Render Collapsible Excluded Types Block
  const excludedBlock = document.getElementById("excluded-types-block");
  const excludedSummary = document.getElementById("excluded-types-summary");
  const excludedList = document.getElementById("excluded-types-list");

  if (excludedBlock && excludedSummary && excludedList) {
    if (allExcluded.length > 0) {
      excludedBlock.style.display = "block";
      excludedSummary.textContent = `Tipe Fasilitas Dikecualikan dari Penilaian (${allExcluded.length})`;
      excludedList.innerHTML = "";
      allExcluded.forEach(item => {
        const el = document.createElement("div");
        el.className = "excluded-type-item";
        el.innerHTML = `<strong>${escapeHtml(item.type.replace(/_/g, ' '))}</strong> <span style="color: var(--text-dim);">(${escapeHtml(item.pillar)})</span>: ${escapeHtml(item.reason)}`;
        excludedList.appendChild(el);
      });
    } else {
      excludedBlock.style.display = "none";
    }
  }

  // Detailed metrics
  const listContainer = document.getElementById("metrics-breakdown-list");
  if (!listContainer) return;
  listContainer.innerHTML = "";
  const metrics = data.metrics_payload || [];
  metrics.forEach(item => {
    if (item.category === "unclassified" || item.status === "unclassified") return;

    const isScored = item.scored === true;
    const el = document.createElement("div");
    el.className = "pillar-progress-card";

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

    if (!isScored) {
      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${escapeHtml(item.facility_type.replace(/_/g, ' ').toUpperCase())}</span>
          <span style="color: var(--text-muted); font-weight: 600;">Informasi</span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          ${item.existing} titik OSM - tidak dinilai
        </div>
      `;
    } else if (item.data_availability === "insufficient_local") {
      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${escapeHtml(item.facility_type.replace(/_/g, ' ').toUpperCase())}</span>
          <span style="color: #94a3b8; font-weight: 700;">Data tidak memadai</span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          Eksisting: ${item.existing} • Kebutuhan (${escapeHtml(tableLabel)}): ${item.required ?? "-"} • Rasio & defisit tidak dihitung (cakupan OSM tidak memadai)
        </div>
      `;
    } else if (
      item.compliance_pct === null ||
      item.compliance_pct === undefined ||
      item.data_availability === "insufficient" ||
      item.data_availability === "not_available"
    ) {
      const reasonText = item.availability_reason || "Kelengkapan data provinsi tidak memadai";
      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${escapeHtml(item.facility_type.replace(/_/g, ' ').toUpperCase())}</span>
          <span style="color: #94a3b8; font-weight: 600;">Tidak dinilai</span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          ${item.existing} titik OSM • ${escapeHtml(reasonText)}
        </div>
      `;
    } else {
      const isDeficit = item.deficit < 0;
      const badgeColor = isDeficit ? "#f43f5e" : "#10b981";
      el.innerHTML = `
        <div class="pillar-card-header">
          <span>${escapeHtml(item.facility_type.replace(/_/g, ' ').toUpperCase())}</span>
          <span style="color: ${badgeColor}; font-weight: 700;">
            ${isDeficit ? `Defisit ${Math.abs(item.deficit)} unit (menurut data OSM)` : `Terpenuhi (${item.existing}/${item.required})`}
          </span>
        </div>
        <div style="font-size: 11.5px; color: var(--text-dim);">
          Eksisting: ${item.existing} • Kebutuhan (${escapeHtml(tableLabel)}): ${item.required} • Rasio Kepatuhan: ${item.compliance_pct}%${isDeficit ? ' • <span style="color: #fbbf24;">(Defisit menurut data OSM, bukan data resmi Dapodik/Dinkes)</span>' : ''}
        </div>
      `;
    }
    listContainer.appendChild(el);
  });
}
