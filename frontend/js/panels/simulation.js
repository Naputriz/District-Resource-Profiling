/**
 * panels/simulation.js
 * What-if sandbox and superblock impact simulation controls,
 * state synchronization between slider and count inputs, and safe delta rendering.
 */

import { state } from "../state.js";
import { postWhatIfSimulation, postSuperblockSimulation } from "../api.js";
import { formatAssumptionValue } from "../utils/dom.js";

let syncFromSlider = null;
let syncFromCount = null;

export function syncSimulationDistrict() {
  if (typeof syncFromSlider === "function") {
    syncFromSlider();
  }
}

export function resetSimulationPanel() {
  const resBox = document.getElementById("sim-result-box");
  if (resBox) resBox.style.display = "none";
  const obList = document.getElementById("res-obligations-list");
  if (obList) obList.innerHTML = "";
  const assumpBody = document.querySelector("#res-assumptions-table tbody");
  if (assumpBody) assumpBody.innerHTML = "";
  syncSimulationDistrict();
}

export function initSimulationControls() {
  const popSlider = document.getElementById("sim-pop-slider");
  const popVal = document.getElementById("sim-pop-slider-val");
  const popCountInput = document.getElementById("sim-pop-count");
  const runBtn = document.getElementById("btn-run-simulation");

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

  if (popSlider) popSlider.addEventListener("input", syncFromSlider);
  if (popCountInput) popCountInput.addEventListener("input", syncFromCount);
  syncFromSlider();

  if (runBtn) {
    runBtn.addEventListener("click", async () => {
      if (!state.selectedDistrict) {
        alert("Pilih kecamatan terlebih dahulu pada peta.");
        return;
      }

      const simType = document.querySelector('input[name="sim-mode"]:checked')?.value || "pop";
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
          const delta = await postWhatIfSimulation(payload);
          renderSimulationDelta(delta, false, delta.impact_level, delta.assumptions);
        } else {
          const unitsInput = document.getElementById("sim-sb-units");
          const areaInput = document.getElementById("sim-sb-area");
          const nameInput = document.getElementById("sim-sb-name");

          const units = parseInt(unitsInput?.value || "3000", 10);
          const siteArea = parseFloat(areaInput?.value || "20000");
          const payload = {
            district_code: state.selectedDistrict.kemendagri_code,
            project_name: nameInput?.value || "Superblok Hipotetis",
            residential_units: units,
            occupants_per_unit: 3.0,
            site_area_m2: siteArea
          };
          const impact = await postSuperblockSimulation(payload);
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
}

export function renderSimulationDelta(delta, isSuperblock = false, impactLevel = null, assumptions = null) {
  const box = document.getElementById("sim-result-box");
  if (!box) return;
  box.style.display = "flex";

  const impact = impactLevel || delta.impact_level || "Sedang";
  const impactEl = document.getElementById("res-impact-level");
  if (impactEl) {
    impactEl.textContent = `Indikasi: ${impact}`;
    if (impact === "Rendah") {
      impactEl.className = "pillar-badge-tag badge-status-tersedia";
    } else if (impact === "Sedang") {
      impactEl.className = "pillar-badge-tag badge-status-cakupan-rendah";
    } else {
      impactEl.className = "pillar-badge-tag badge-status-tidak-tersedia";
    }
  }

  const popDeltaEl = document.getElementById("res-pop-delta");
  if (popDeltaEl) popDeltaEl.textContent = `+${(delta.population_delta || 0).toLocaleString()}`;

  const scoreDeltaEl = document.getElementById("res-score-delta");
  if (scoreDeltaEl) {
    scoreDeltaEl.textContent = `${delta.score_delta > 0 ? '+' : ''}${delta.score_delta}`;
    scoreDeltaEl.style.color = delta.score_delta < 0 ? "#f43f5e" : "#10b981";
  }

  const simScoreEl = document.getElementById("res-sim-score");
  if (simScoreEl) simScoreEl.textContent = `${delta.simulated_composite_score} pts`;

  // Assumptions small table
  const assumpWrapper = document.getElementById("res-assumptions-wrapper");
  const assumpTableBody = document.querySelector("#res-assumptions-table tbody");
  const assumpData = assumptions || delta.assumptions || {};
  const entries = Object.entries(assumpData);

  if (entries.length > 0 && assumpWrapper && assumpTableBody) {
    assumpWrapper.style.display = "block";
    assumpTableBody.innerHTML = "";
    entries.forEach(([k, v]) => {
      const row = document.createElement("tr");
      const tdKey = document.createElement("td");
      tdKey.textContent = String(k);
      const tdVal = document.createElement("td");
      const strong = document.createElement("strong");
      strong.textContent = formatAssumptionValue(v);
      tdVal.appendChild(strong);
      row.appendChild(tdKey);
      row.appendChild(tdVal);
      assumpTableBody.appendChild(row);
    });
  } else if (assumpWrapper) {
    assumpWrapper.style.display = "none";
  }

  const obList = document.getElementById("res-obligations-list");
  if (obList) {
    obList.innerHTML = "";
    (delta.legal_recommendations || []).forEach(o => {
      const el = document.createElement("div");
      el.className = "obligation-badge-item";
      const strong = document.createElement("strong");
      strong.textContent = (o.regulation_code || "") + " (" + (o.article_reference || "") + "): ";
      el.appendChild(strong);
      el.appendChild(document.createTextNode((o.obligation_text || "") + " [" + (o.required_metric || "") + "]"));
      obList.appendChild(el);
    });
  }
}

export function renderSuperblockImpact(impact) {
  renderSimulationDelta(impact.simulation_delta, true, impact.impact_level, impact.assumptions);
  const obList = document.getElementById("res-obligations-list");
  if (!obList) return;
  (impact.developer_legal_obligations || []).forEach(o => {
    const el = document.createElement("div");
    el.className = "obligation-badge-item";
    el.style.borderLeftColor = "#38bdf8";
    const strong = document.createElement("strong");
    strong.textContent = (o.title || "") + " (" + (o.regulation_code || "") + "): ";
    el.appendChild(strong);
    el.appendChild(document.createTextNode(o.obligation_text ? o.obligation_text + " " : ""));
    el.appendChild(document.createElement("br"));
    const em = document.createElement("em");
    em.textContent = "Kebutuhan: " + (o.required_metric || "");
    el.appendChild(em);
    obList.appendChild(el);
  });
}
