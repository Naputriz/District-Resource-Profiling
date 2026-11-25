import test from "node:test";
import assert from "node:assert/strict";
import worker, {
  CACHE_TTL_LONG_SECONDS,
  CACHE_TTL_SHORT_SECONDS,
  buildEdgeCacheKey,
  getEdgeCachePolicy,
} from "./worker.js";

function createMockCache() {
  const store = new Map();
  return {
    store,
    async match(req) {
      const key = typeof req === "string" ? req : req.url;
      const entry = store.get(key);
      if (!entry) return undefined;
      return new Response(entry.body, {
        status: entry.status,
        statusText: entry.statusText,
        headers: new Headers(entry.headers),
      });
    },
    async put(req, resp) {
      const key = typeof req === "string" ? req : req.url;
      const body = await resp.text();
      store.set(key, {
        body,
        status: resp.status,
        statusText: resp.statusText,
        headers: new Headers(resp.headers),
      });
    },
  };
}

test("getEdgeCachePolicy enforces TTLs and bypass rules", () => {
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/regions")),
    { ttl: CACHE_TTL_LONG_SECONDS }
  );
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/meta/standards")),
    { ttl: CACHE_TTL_LONG_SECONDS }
  );
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/districts?province_code=32")),
    { ttl: CACHE_TTL_SHORT_SECONDS }
  );
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/districts/31.71.09")),
    { ttl: CACHE_TTL_SHORT_SECONDS }
  );
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/spatial/blank-spots?district_code=31.71.09")),
    { ttl: CACHE_TTL_SHORT_SECONDS }
  );
  assert.deepEqual(
    getEdgeCachePolicy(new Request("https://drp.digilabui.cloud/api/v1/facilities?district_code=31.71.09")),
    { ttl: CACHE_TTL_SHORT_SECONDS }
  );

  // Never cache Authorization / Cookie / private / mutable / health / watchdog
  assert.equal(
    getEdgeCachePolicy(
      new Request("https://drp.digilabui.cloud/api/v1/districts", {
        headers: { Authorization: "Bearer secret" },
      })
    ),
    null
  );
  assert.equal(
    getEdgeCachePolicy(
      new Request("https://drp.digilabui.cloud/api/v1/districts", {
        headers: { Cookie: "session=abc" },
      })
    ),
    null
  );
  for (const path of [
    "/api/v1/auth/me",
    "/api/v1/auth/login",
    "/api/v1/chat",
    "/api/v1/chat/history",
    "/api/v1/simulation/what-if",
    "/api/v1/watchdog/telemetry",
    "/api/v1/rag/search",
    "/health",
  ]) {
    assert.equal(
      getEdgeCachePolicy(new Request(`https://drp.digilabui.cloud${path}`)),
      null,
      `Expected null policy for ${path}`
    );
  }
  assert.equal(
    getEdgeCachePolicy(
      new Request("https://drp.digilabui.cloud/api/v1/simulation/what-if", { method: "POST" })
    ),
    null
  );
});

test("buildEdgeCacheKey includes DATA_VERSION for instant purge", () => {
  const k1 = buildEdgeCacheKey("https://drp.digilabui.cloud/api/v1/districts?province_code=32", "v1");
  const k2 = buildEdgeCacheKey("https://drp.digilabui.cloud/api/v1/districts?province_code=32", "v2");
  assert.notEqual(k1.url, k2.url);
  assert.ok(k1.url.includes("__drp_v=v1"));
  assert.ok(k2.url.includes("__drp_v=v2"));
});

test("worker fetch caches public GETs, respects DATA_VERSION, preserves edge headers, and bypasses auth/non-200", async () => {
  const origFetch = globalThis.fetch;
  const edgeCache = createMockCache();
  let originCalls = [];
  let assetCalls = 0;

  globalThis.fetch = async (req) => {
    originCalls.push(req);
    const u = new URL(req.url);
    if (u.pathname === "/api/v1/districts/99.99.99") {
      return new Response(JSON.stringify({ detail: "Not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    return new Response(JSON.stringify({ ok: true, path: u.pathname + u.search }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };

  const makeEnv = (dataVersion = "20261125-1") => ({
    DATA_VERSION: dataVersion,
    EDGE_SHARED_SECRET: "edge-secret-xyz",
    EDGE_CACHE: edgeCache,
    ASSETS: {
      async fetch(req) {
        assetCalls += 1;
        return new Response("<html></html>", { status: 200 });
      },
    },
  });

  try {
    // 1. Static asset delegates to ASSETS
    const staticRes = await worker.fetch(
      new Request("https://drp.digilabui.cloud/index.html"),
      makeEnv()
    );
    assert.equal(staticRes.status, 200);
    assert.equal(assetCalls, 1);
    assert.equal(originCalls.length, 0);

    // 2. First districts GET -> MISS, strips forged headers, sets real IP + secret
    const req1 = new Request("https://drp.digilabui.cloud/api/v1/districts?province_code=32", {
      headers: {
        "CF-Connecting-IP": "203.0.113.10",
        "X-DRP-Client-IP": "1.2.3.4",
        "X-DRP-Edge-Secret": "forged",
      },
    });
    const res1 = await worker.fetch(req1, makeEnv("20261125-1"));
    assert.equal(res1.status, 200);
    assert.equal(res1.headers.get("X-DRP-Cache"), "MISS");
    assert.equal(originCalls.length, 1);
    assert.equal(originCalls[0].headers.get("X-DRP-Client-IP"), "203.0.113.10");
    assert.equal(originCalls[0].headers.get("X-DRP-Edge-Secret"), "edge-secret-xyz");
    assert.equal(originCalls[0].headers.get("X-Forwarded-Host"), "drp.digilabui.cloud");

    // Verify stored Cache-Control TTL in edge cache is 600s
    const storedEntry = [...edgeCache.store.values()][0];
    assert.ok(storedEntry.headers.get("Cache-Control").includes("s-maxage=600"));

    // 3. Second identical GET -> HIT, no origin call
    const res2 = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/districts?province_code=32"),
      makeEnv("20261125-1")
    );
    assert.equal(res2.status, 200);
    assert.equal(res2.headers.get("X-DRP-Cache"), "HIT");
    assert.equal(originCalls.length, 1);

    // 4. Bumping DATA_VERSION -> MISS and refetches
    const res3 = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/districts?province_code=32"),
      makeEnv("20261125-2")
    );
    assert.equal(res3.headers.get("X-DRP-Cache"), "MISS");
    assert.equal(originCalls.length, 2);

    // 5. Authorization header -> BYPASS, never hits cache
    const resAuth = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/districts?province_code=32", {
        headers: { Authorization: "Bearer tok" },
      }),
      makeEnv("20261125-1")
    );
    assert.equal(resAuth.headers.get("X-DRP-Cache"), "BYPASS");
    assert.equal(originCalls.length, 3);

    // 6. Cookie header -> BYPASS
    const resCookie = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/regions", {
        headers: { Cookie: "user=1" },
      }),
      makeEnv("20261125-1")
    );
    assert.equal(resCookie.headers.get("X-DRP-Cache"), "BYPASS");
    assert.equal(originCalls.length, 4);

    // 7. Non-200 response is never cached
    const res404a = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/districts/99.99.99"),
      makeEnv("20261125-1")
    );
    assert.equal(res404a.status, 404);
    assert.equal(res404a.headers.get("X-DRP-Cache"), "MISS");
    const res404b = await worker.fetch(
      new Request("https://drp.digilabui.cloud/api/v1/districts/99.99.99"),
      makeEnv("20261125-1")
    );
    assert.equal(res404b.status, 404);
    assert.equal(originCalls.length, 6);

    // 8. /health and /api/v1/watchdog/telemetry are BYPASS
    const resHealth = await worker.fetch(
      new Request("https://drp.digilabui.cloud/health"),
      makeEnv("20261125-1")
    );
    assert.equal(resHealth.headers.get("X-DRP-Cache"), "BYPASS");
  } finally {
    globalThis.fetch = origFetch;
  }
});
