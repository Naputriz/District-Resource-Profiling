/**
 * config.js
 * Application configuration, API endpoints base URL (same-origin rule),
 * map defaults, and polling intervals for watchdog and health telemetry.
 */

export const API_BASE = window.location.origin;

export const DEFAULT_MAP_CENTER = [-6.2088, 106.8456];
export const DEFAULT_MAP_ZOOM = 12;

export const WATCHDOG_POLL_INTERVAL_MS = 15000;
export const HEALTH_POLL_INTERVAL_MS = 15000;

export const BASE_PILLAR_WEIGHTS = {
  lifeline_health: 0.30,
  education: 0.25,
  urban_livability: 0.25,
  mobility_connectivity: 0.20
};
