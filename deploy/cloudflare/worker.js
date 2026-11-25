// DRP edge worker: static frontend is served from Workers Static Assets;
// public read-only API GETs are edge-cached with caches.default;
// all origin requests are forwarded to the backend through Cloudflare Tunnel.
const ORIGIN = "https://drp-origin.digilabui.cloud";
const PROXY_PREFIXES = ["/api/", "/health", "/data/", "/docs", "/openapi.json"];

export const CACHE_TTL_LONG_SECONDS = 3600;
export const CACHE_TTL_SHORT_SECONDS = 600;

/**
 * Returns { ttl } if the request is eligible for Cloudflare edge caching, or null otherwise.
 * Never caches requests carrying Authorization/Cookie headers or private/mutable/live routes.
 */
export function getEdgeCachePolicy(request) {
  if (!request || request.method !== "GET") {
    return null;
  }

  const headers = request.headers;
  if (headers) {
    const auth = headers.get("Authorization");
    const cookie = headers.get("Cookie");
    if ((auth && auth.trim() !== "") || (cookie && cookie.trim() !== "")) {
      return null;
    }
  }

  const url = new URL(request.url);
  const path = url.pathname;

  if (
    path.startsWith("/api/v1/auth") ||
    path.startsWith("/api/v1/chat") ||
    path.startsWith("/api/v1/simulation") ||
    path.startsWith("/api/v1/watchdog") ||
    path.startsWith("/api/v1/rag") ||
    path === "/health"
  ) {
    return null;
  }

  if (
    path === "/api/v1/regions" ||
    path.startsWith("/api/v1/regions/") ||
    path.startsWith("/api/v1/meta/")
  ) {
    return { ttl: CACHE_TTL_LONG_SECONDS };
  }

  if (
    path === "/api/v1/districts" ||
    path.startsWith("/api/v1/districts/") ||
    path === "/api/v1/spatial/blank-spots" ||
    path === "/api/v1/facilities"
  ) {
    return { ttl: CACHE_TTL_SHORT_SECONDS };
  }

  return null;
}

/**
 * Builds the edge cache key Request combining the full URL and wrangler DATA_VERSION.
 */
export function buildEdgeCacheKey(requestUrl, dataVersion = "1") {
  const keyUrl = new URL(requestUrl.toString());
  keyUrl.searchParams.set("__drp_v", String(dataVersion || "1"));
  return new Request(keyUrl.toString(), { method: "GET" });
}

function getDefaultCache(env) {
  if (env && env.EDGE_CACHE) {
    return env.EDGE_CACHE;
  }
  if (typeof caches !== "undefined" && caches && caches.default) {
    return caches.default;
  }
  return null;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (PROXY_PREFIXES.some((p) => url.pathname === p.replace(/\/$/, "") || url.pathname.startsWith(p))) {
      const policy = getEdgeCachePolicy(request);
      const cache = policy ? getDefaultCache(env) : null;
      const cacheKey = policy && cache
        ? buildEdgeCacheKey(request.url, env && env.DATA_VERSION ? env.DATA_VERSION : "1")
        : null;

      if (cache && cacheKey) {
        const cached = await cache.match(cacheKey);
        if (cached) {
          const hitHeaders = new Headers(cached.headers);
          hitHeaders.set("X-DRP-Cache", "HIT");
          return new Response(cached.body, {
            status: cached.status,
            statusText: cached.statusText,
            headers: hitHeaders,
          });
        }
      }

      const target = new URL(url.pathname + url.search, ORIGIN);
      const headers = new Headers(request.headers);
      headers.delete("X-DRP-Client-IP");
      headers.delete("X-DRP-Edge-Secret");
      headers.set("X-Forwarded-Host", url.host);
      const clientIp = request.headers.get("CF-Connecting-IP");
      if (clientIp) {
        headers.set("X-DRP-Client-IP", clientIp);
      }
      if (env && env.EDGE_SHARED_SECRET) {
        headers.set("X-DRP-Edge-Secret", env.EDGE_SHARED_SECRET);
      }

      const originResponse = await fetch(new Request(target, {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      }));

      const respHeaders = new Headers(originResponse.headers);
      if (cache && cacheKey && originResponse.status === 200 && !originResponse.headers.has("Set-Cookie")) {
        const cacheHeaders = new Headers(originResponse.headers);
        cacheHeaders.set("Cache-Control", `public, max-age=300, s-maxage=${policy.ttl}`);
        const responseToCache = new Response(originResponse.clone().body, {
          status: originResponse.status,
          statusText: originResponse.statusText,
          headers: cacheHeaders,
        });
        const putPromise = cache.put(cacheKey, responseToCache);
        if (ctx && typeof ctx.waitUntil === "function") {
          ctx.waitUntil(putPromise);
        } else {
          await putPromise;
        }
        respHeaders.set("X-DRP-Cache", "MISS");
      } else {
        respHeaders.set("X-DRP-Cache", policy ? "MISS" : "BYPASS");
      }

      return new Response(originResponse.body, {
        status: originResponse.status,
        statusText: originResponse.statusText,
        headers: respHeaders,
      });
    }
    return env.ASSETS.fetch(request);
  },
};
