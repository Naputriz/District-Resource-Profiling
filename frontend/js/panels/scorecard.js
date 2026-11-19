/**
 * panels/scorecard.js
 * Renders district score dial, verbatim composite note, 4-pillar progress bars
 * with effective weights and exclusion tags, and granular facility compliance audit list.
 */

import { state } from "../state.js";
import { BASE_PILLAR_WEIGHTS } from "../config.js";
import { getChoroplethColor, escapeHtml } from "../utils/dom.js";

export function renderScorecard(data) {
  const score = data.composite_livability_score !== undefined ? data.composite_livability_score : (data.composite_score || 0);
  const dial = document.getElementById("score-dial-val");
  if (dial) {
    dial.textContent = typeof score === "number" ? score.toFixed(1) : score;
    dial.style.borderColor = getChoroplethColor(Number(score) || 0);
    dial.style.boxShadow = `0 0 16px ${getChoroplethColor(Number(score) || 0)}55`;
  }

  // Verbatim Composite Note
  const noteBox = document.getElementById("composite-note-box");
  if (noteBox) {
    if (data.composite_note) {
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
    const status = pData.status || (isExcluded ? "cakupan data rendah" : "tersedia");
    const dataCoverage = pData.data_coverage !== undefined ? pData.data_coverage : 1.0;

    // Update pillar header with effective weight
    const isIncluded = !isExcluded && activeWeightSum > 0;
    const effWeight = isIncluded ? ((BASE_PILLAR_WEIGHTS[cfg.key] || 0) / activeWeightSum * 100) : 0;
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
          reason: ex.reason || "Kelengkapan data kota tidak memadai (<44 kecamatan)"
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
