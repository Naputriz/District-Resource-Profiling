/**
 * api.js
 * Centralized API client: one exported function per backend endpoint with shared error handling.
 * All requests conform to same-origin rule via config.js API_BASE.
 * Supports JWT authentication via sessionStorage (drp_auth_token).
 */

import { API_BASE } from "./config.js";

export function getAuthToken() {
  return sessionStorage.getItem("drp_auth_token");
}

export function setAuthToken(token) {
  if (token) {
    sessionStorage.setItem("drp_auth_token", token);
  } else {
    sessionStorage.removeItem("drp_auth_token");
  }
}

export function getStoredUser() {
  const u = sessionStorage.getItem("drp_auth_user");
  try {
    return u ? JSON.parse(u) : null;
  } catch (e) {
    return null;
  }
}

export function setStoredUser(user) {
  if (user) {
    sessionStorage.setItem("drp_auth_user", JSON.stringify(user));
  } else {
    sessionStorage.removeItem("drp_auth_user");
  }
}

export function getAuthHeaders() {
  const token = getAuthToken();
  const headers = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function handleResponse(response, endpointName) {
  if (response.status === 401) {
    window.dispatchEvent(
      new CustomEvent("drp:unauthorized", {
        detail: { endpoint: endpointName },
      })
    );
    const errorData = await response.json().catch(() => null);
    const msg = errorData && errorData.detail ? errorData.detail : "Login diperlukan untuk memakai fitur ini.";
    throw new Error(msg);
  }
  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    throw new Error(
      `API error [${endpointName}] HTTP ${response.status}: ${
        errorText || response.statusText
      }`
    );
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

export async function fetchRegions() {
  const res = await fetch(`${API_BASE}/api/v1/regions`);
  return handleResponse(res, "regions");
}

export async function fetchRegionDetail(provinceCode) {
  const res = await fetch(`${API_BASE}/api/v1/regions/${provinceCode}`);
  return handleResponse(res, `regions/${provinceCode}`);
}

export async function fetchDistricts(provinceCode = null) {
  let url = `${API_BASE}/api/v1/districts`;
  if (provinceCode) {
    url += `?province_code=${encodeURIComponent(provinceCode)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, "districts");
}

export async function fetchBoundariesGeoJSON(geojsonUrl = null) {
  const targetUrl = geojsonUrl || "/data/boundaries/jakarta_44_kecamatan.geojson";
  const geoRes = await fetch(targetUrl).catch(() => null);
  if (geoRes && geoRes.ok) {
    return geoRes.json();
  }
  throw new Error(`API error [boundaries] failed to load GeoJSON from ${targetUrl}`);
}

export async function fetchDistrictDetail(districtCode, provinceCode = null) {
  let url = `${API_BASE}/api/v1/districts/${encodeURIComponent(districtCode)}`;
  if (provinceCode) {
    url += `?province_code=${encodeURIComponent(provinceCode)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, `districts/${districtCode}`);
}

export async function fetchDistrictFacilities(districtCode, pillar = null, provinceCode = null) {
  let url = `${API_BASE}/api/v1/facilities?district_code=${encodeURIComponent(districtCode)}&limit=100`;
  if (pillar) {
    url += `&pillar=${encodeURIComponent(pillar)}`;
  }
  if (provinceCode) {
    url += `&province_code=${encodeURIComponent(provinceCode)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, "facilities");
}

export async function fetchBlankSpots(
  districtCode,
  facilityType = "puskesmas_kelurahan",
  provinceCode = null
) {
  let url = `${API_BASE}/api/v1/spatial/blank-spots?district_code=${encodeURIComponent(districtCode)}&facility_type=${encodeURIComponent(
    facilityType
  )}`;
  if (provinceCode) {
    url += `&province_code=${encodeURIComponent(provinceCode)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, "spatial/blank-spots");
}

export async function fetchBuffers(
  districtCode,
  facilityType = "puskesmas_kelurahan",
  provinceCode = null
) {
  let url = `${API_BASE}/api/v1/spatial/buffers?district_code=${encodeURIComponent(districtCode)}&facility_type=${encodeURIComponent(
    facilityType
  )}`;
  if (provinceCode) {
    url += `&province_code=${encodeURIComponent(provinceCode)}`;
  }
  const res = await fetch(url);
  return handleResponse(res, "spatial/buffers");
}

export async function postChatMessage(payload) {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  return handleResponse(res, "chat");
}

export async function postWhatIfSimulation(payload) {
  const res = await fetch(`${API_BASE}/api/v1/simulation/what-if`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  return handleResponse(res, "simulation/what-if");
}

export async function postSuperblockSimulation(payload) {
  const res = await fetch(`${API_BASE}/api/v1/simulation/superblock`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  return handleResponse(res, "simulation/superblock");
}

export async function fetchWatchdogTelemetry() {
  const res = await fetch(`${API_BASE}/api/v1/watchdog/telemetry`);
  return handleResponse(res, "watchdog/telemetry");
}

// === Auth API calls (TODO-4) ===

export async function loginUser(email, password) {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Gagal masuk.");
  }
  const data = await res.json();
  setAuthToken(data.access_token);
  setStoredUser(data.user);
  return data;
}

export async function registerUser(email, password, displayName) {
  const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      password,
      display_name: displayName,
    }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Gagal mendaftar.");
  }
  return res.json();
}

export async function fetchMyProfile() {
  const token = getAuthToken();
  if (!token) return null;
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: getAuthHeaders(),
  });
  return handleResponse(res, "auth/me");
}

export async function logoutUser() {
  const token = getAuthToken();
  if (token) {
    try {
      await fetch(`${API_BASE}/api/v1/auth/logout`, {
        method: "POST",
        headers: getAuthHeaders(),
      });
    } catch (e) {
      // client-side drop is enough
    }
  }
  setAuthToken(null);
  setStoredUser(null);
}
