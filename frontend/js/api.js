/**
 * api.js
 * Centralized API client: one exported function per backend endpoint with shared error handling.
 * All requests conform to same-origin rule via config.js API_BASE.
 * Supports JWT authentication via sessionStorage (drp_auth_token).
 */

import { API_BASE, withAppVersion } from "./config.js";

// In-memory session caches & in-flight GET request deduplication
const provinceDistrictsCache = new Map();
const geojsonCache = new Map();
const districtDetailCache = new Map();
const inflightGetRequests = new Map();
let regionsCache = null;
let standardsCache = null;

export function clearSessionCaches() {
  provinceDistrictsCache.clear();
  geojsonCache.clear();
  districtDetailCache.clear();
  inflightGetRequests.clear();
  regionsCache = null;
  standardsCache = null;
}

export function getSessionCacheStats() {
  return {
    provinces: provinceDistrictsCache.size,
    geojson: geojsonCache.size,
    districtDetails: districtDetailCache.size,
    inflight: inflightGetRequests.size,
    hasRegions: Boolean(regionsCache),
    hasStandards: Boolean(standardsCache),
  };
}

function dedupedGetJson(url, endpointName) {
  if (inflightGetRequests.has(url)) {
    return inflightGetRequests.get(url);
  }
  const reqPromise = fetch(url)
    .then((res) => handleResponse(res, endpointName))
    .finally(() => {
      inflightGetRequests.delete(url);
    });
  inflightGetRequests.set(url, reqPromise);
  return reqPromise;
}

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
  if (standardsCache) return standardsCache;
  const data = await dedupedGetJson(`${API_BASE}/api/v1/meta/standards`, "meta/standards");
  standardsCache = data;
  return data;
}

export async function fetchHealthStatus() {
  return dedupedGetJson(`${API_BASE}/health`, "health");
}

export async function fetchRegions() {
  if (regionsCache) return regionsCache;
  const data = await dedupedGetJson(`${API_BASE}/api/v1/regions`, "regions");
  regionsCache = data;
  return data;
}

export async function fetchRegionDetail(provinceCode) {
  return dedupedGetJson(
    `${API_BASE}/api/v1/regions/${encodeURIComponent(provinceCode)}`,
    `regions/${provinceCode}`
  );
}

export async function fetchDistricts(provinceCode = null) {
  const cacheKey = provinceCode ? String(provinceCode).trim() : "__default__";
  if (provinceDistrictsCache.has(cacheKey)) {
    return provinceDistrictsCache.get(cacheKey);
  }
  let url = `${API_BASE}/api/v1/districts`;
  if (provinceCode) {
    url += `?province_code=${encodeURIComponent(provinceCode)}`;
  }
  const data = await dedupedGetJson(url, "districts");
  provinceDistrictsCache.set(cacheKey, data);
  if (data && data.province_code) {
    provinceDistrictsCache.set(String(data.province_code).trim(), data);
  }
  return data;
}

export async function fetchBoundariesGeoJSON(geojsonUrl = null) {
  const baseUrl = geojsonUrl || "/data/boundaries/jakarta_44_kecamatan.geojson";
  const targetUrl = withAppVersion(baseUrl);
  if (geojsonCache.has(targetUrl)) {
    return geojsonCache.get(targetUrl);
  }
  if (inflightGetRequests.has(targetUrl)) {
    return inflightGetRequests.get(targetUrl);
  }
  const reqPromise = fetch(targetUrl)
    .then(async (geoRes) => {
      if (!geoRes || !geoRes.ok) {
        throw new Error(`API error [boundaries] failed to load GeoJSON from ${targetUrl}`);
      }
      const data = await geoRes.json();
      geojsonCache.set(targetUrl, data);
      return data;
    })
    .finally(() => {
      inflightGetRequests.delete(targetUrl);
    });
  inflightGetRequests.set(targetUrl, reqPromise);
  return reqPromise;
}

export async function fetchDistrictDetail(districtCode, provinceCode = null) {
  const provKey = provinceCode ? String(provinceCode).trim() : "";
  const codeKey = String(districtCode || "").trim();
  const cacheKey = `${provKey}:${codeKey}`;
  if (districtDetailCache.has(cacheKey)) {
    return districtDetailCache.get(cacheKey);
  }
  let url = `${API_BASE}/api/v1/districts/${encodeURIComponent(districtCode)}`;
  if (provinceCode) {
    url += `?province_code=${encodeURIComponent(provinceCode)}`;
  }
  const data = await dedupedGetJson(url, `districts/${districtCode}`);
  districtDetailCache.set(cacheKey, data);
  if (data && data.kemendagri_code) {
    const resolvedProv = String(data.province_code || provKey).trim();
    districtDetailCache.set(`${resolvedProv}:${data.kemendagri_code}`, data);
  }
  return data;
}

export async function fetchDistrictFacilities(districtCode, pillar = null, provinceCode = null) {
  let url = `${API_BASE}/api/v1/facilities?district_code=${encodeURIComponent(districtCode)}&limit=100`;
  if (pillar) {
    url += `&pillar=${encodeURIComponent(pillar)}`;
  }
  if (provinceCode) {
    url += `&province_code=${encodeURIComponent(provinceCode)}`;
  }
  return dedupedGetJson(url, "facilities");
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
  return dedupedGetJson(url, "spatial/blank-spots");
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
  return dedupedGetJson(url, "spatial/buffers");
}

export async function postChatMessage(payload) {
  const res = await fetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  return handleResponse(res, "chat");
}

export async function fetchChatHistory(limit = 20) {
  const res = await fetch(
    `${API_BASE}/api/v1/chat/history?limit=${encodeURIComponent(limit)}`,
    {
      headers: getAuthHeaders(),
    }
  );
  return handleResponse(res, "chat/history");
}

export async function deleteChatHistory() {
  const res = await fetch(`${API_BASE}/api/v1/chat/history`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  return handleResponse(res, "chat/history");
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
  return dedupedGetJson(`${API_BASE}/api/v1/watchdog/telemetry`, "watchdog/telemetry");
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
