// DRP edge worker: static frontend is served from Workers Static Assets;
// API, health and data requests are forwarded to the backend through Cloudflare Tunnel.
const ORIGIN = "https://drp-origin.digilabui.cloud";
const PROXY_PREFIXES = ["/api/", "/health", "/data/", "/docs", "/openapi.json"];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (PROXY_PREFIXES.some((p) => url.pathname === p.replace(/\/$/, "") || url.pathname.startsWith(p))) {
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
      return fetch(new Request(target, {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        redirect: "manual",
      }));
    }
    return env.ASSETS.fetch(request);
  },
};
