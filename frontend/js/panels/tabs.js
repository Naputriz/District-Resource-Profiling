/**
 * panels/tabs.js
 * Tab switcher navigation for the right info panel (Scorecard, Simulation, Blank Spots, Watchdog)
 * and tab-dependent spatial layer activation.
 */

import { state } from "../state.js";
import { loadDistrictBlankSpots } from "./blankspots.js";
import { clearBlankSpotLayers } from "../map/layers.js";

export function switchToTab(tabName) {
  const tabs = document.querySelectorAll(".info-tab-btn");
  tabs.forEach(t => {
    if (t.getAttribute("data-tab") === tabName) {
      t.classList.add("active");
    } else {
      t.classList.remove("active");
    }
  });

  document.querySelectorAll(".tab-pane-view").forEach(p => {
    p.style.display = "none";
  });

  const target = document.getElementById(`tab-pane-${tabName}`);
  if (target) {
    target.style.display = "flex";
  }

  if (tabName === "blankspots") {
    if (state.selectedDistrict) {
      loadDistrictBlankSpots(state.selectedDistrict.kemendagri_code);
    }
  } else {
    clearBlankSpotLayers();
  }
}

export function initTabNavigation() {
  const tabs = document.querySelectorAll(".info-tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.getAttribute("data-tab");
      switchToTab(target);
    });
  });
}
