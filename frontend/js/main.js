/**
 * main.js
 * Frontend application entry point: initializes layout, map, panels, timers,
 * and kicks off initial metadata and district loading on DOMContentLoaded.
 */

import { WATCHDOG_POLL_INTERVAL_MS, HEALTH_POLL_INTERVAL_MS } from "./config.js";
import {
  initResizableSplitter,
  initLeafletMap,
  initSearchAutocomplete,
  initPillarFilters,
  loadStandardsMetadata,
  loadAllDistricts
} from "./map/map.js";
import { initTabNavigation } from "./panels/tabs.js";
import { initSimulationControls } from "./panels/simulation.js";
import { initChatbot } from "./chat/chat.js";
import { loadWatchdogTelemetry, loadHealthStatus } from "./panels/watchdog.js";

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

  setInterval(loadWatchdogTelemetry, WATCHDOG_POLL_INTERVAL_MS);
  setInterval(loadHealthStatus, HEALTH_POLL_INTERVAL_MS);
});
