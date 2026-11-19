/**
 * api.js
 * Centralized API client: one exported function per backend endpoint with shared error handling.
 * All requests conform to same-origin rule via config.js API_BASE.
 */

import { API_BASE } from "./config.js";

async function handleResponse(response, endpointName) {
  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(`API error [${endpointName}] HTTP ${response.status}: ${errorText || response.statusText}`);
  }
  return response.json();
}

export async function fetchStandardsMetadata() {
  const res = await fetch(`${API_BASE}/api/v1/meta/standards`);
  return handleResponse(res, "meta/standards");
}

export async function fetchHealthStatus() {
  const res = await fetch(`${API_BASE}/health`);
  return handleResponse(res, "health");
}

export async function fetchDistricts() {
  const res = await fetch(`${API_BASE}/api/v1/districts`);
  return handleResponse(res, "districts");
}

export async function fetchBoundariesGeoJSON() {
  const geoRes = await fetch("/data/boundaries/jakarta_44_kecamatan.geojson").catch(() => null);
  if (geoRes && geoRes.ok) {
    return geoRes.json();
  }
  // Fallback: fetch boundary from sample district
  const sample = await fetch(`${API_BASE}/api/v1/districts/31.71.09`);
  const sampleData = await sample.json();
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      properties: { kemendagri_code: "31.71.09", name: sampleData.name },
      geometry: sampleData.boundary_geojson
    }]
  };
}

export async function fetchDistrictDetail(districtCode) {
  const res = await fetch(`${API_BASE}/api/v1/districts/${districtCode}`);
  return handleResponse(res, `districts/${districtCode}`);
}

export async function fetchDistrictFacilities(districtCode, pillar = null) {
  let url = `${API_BASE}/api/v1/facilities?district_code=${districtCode}&limit=100`;
  if (pillar) {
    url += `&pillar=${encodeURIComponent(pillar)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, "facilities");
}

export async function fetchBlankSpots(districtCode, facilityType = "puskesmas_kelurahan") {
  const url = `${API_BASE}/api/v1/spatial/blank-spots?district_code=${districtCode}&facility_type=${encodeURIComponent(facilityType)}`;
  const res = await fetch(url);
  return handleResponse(res, "spatial/blank-spots");
}

export async function fetchBuffers(districtCode, facilityType = "puskesmas_kelurahan") {
  const url = `${API_BASE}/api/v1/spatial/buffers?district_code=${districtCode}&facility_type=${encodeURIComponent(facilityType)}`;
  const res = await fetch(url);
  return handleResponse(res, "spatial/buffers");
}

export async function postChatMessage(payload) {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return handleResponse(res, "chat");
}

export async function postWhatIfSimulation(payload) {
  const res = await fetch(`${API_BASE}/api/v1/simulation/what-if`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return handleResponse(res, "simulation/what-if");
}

export async function postSuperblockSimulation(payload) {
  const res = await fetch(`${API_BASE}/api/v1/simulation/superblock`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return handleResponse(res, "simulation/superblock");
}

export async function fetchWatchdogTelemetry() {
  const res = await fetch(`${API_BASE}/api/v1/watchdog/telemetry`);
  return handleResponse(res, "watchdog/telemetry");
}
