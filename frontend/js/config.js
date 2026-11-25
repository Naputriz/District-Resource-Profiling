/**
 * config.js
 * Application configuration, API endpoints base URL (same-origin rule),
 * map defaults, asset cache-busting version, and polling intervals.
 */

export const API_BASE = window.location.origin;

// Bump alongside ?v= in index.html whenever deploying JS/CSS/GeoJSON updates.
export const APP_VERSION = "20261125-u3";

export function withAppVersion(url) {
  if (!url) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}v=${encodeURIComponent(APP_VERSION)}`;
}

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
