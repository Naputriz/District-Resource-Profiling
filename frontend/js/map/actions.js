/**
 * map/actions.js
 * Dual-view synchronization bridge dispatching AI spatial actions to the Leaflet map
 * (flying to district bounds, switching tabs, highlighting blank spots, or rendering simulation deltas).
 */

import { state } from "../state.js";
import { selectDistrict } from "./map.js";
import { styleSimulationLayer } from "./layers.js";
import { switchToTab } from "../panels/tabs.js";
import { loadDistrictBlankSpots } from "../panels/blankspots.js";

export async function executeMapActions(actions) {
  if (!actions || !Array.isArray(actions)) return;

  for (const act of actions) {
    if (act.action_type === "fly_to") {
      const code = act.payload && act.payload.district_code;
      if (code) await selectDistrict(code);
    } else if (act.action_type === "highlight_blank_spot") {
      const code = (act.payload && act.payload.district_code) || (state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null);
      const ftype = (act.payload && act.payload.facility_type) || "puskesmas_kelurahan";
      if (code) {
        switchToTab("blankspots");
        await loadDistrictBlankSpots(code, ftype);
      }
    } else if (act.action_type === "render_simulation_layer") {
      const code = (act.payload && act.payload.district_code) || (state.selectedDistrict ? state.selectedDistrict.kemendagri_code : null);
      const delta = act.payload && act.payload.score_delta;
      switchToTab("simulation");
      if (code) {
        if (!state.selectedDistrict || state.selectedDistrict.kemendagri_code !== code) {
          await selectDistrict(code);
        }
      }
      if (code) {
        styleSimulationLayer(code, delta);
      }
      console.log(`[DUAL-SYNC] Simulation Layer Rendered for ${code}: Delta ${delta}`);
    }
  }
}
