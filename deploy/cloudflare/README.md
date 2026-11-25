# Cloudflare Worker + Tunnel Deployment

## Architecture

```text
Browser
  |
  v  HTTPS (drp.digilabui.cloud / drp.digilabui.workers.dev)
Cloudflare Worker ("drp")
  |-- static files (/, /css/*, /js/*, /data/boundaries/*) --> Workers Static Assets (../../frontend)
  |-- /api/*, /health, /data/*, /docs, /openapi.json
  |     (strips visitor X-DRP-* headers; sets X-DRP-Client-IP & X-DRP-Edge-Secret)
  v
Cloudflare Tunnel (drp-origin.digilabui.cloud)
  v  host network -> 127.0.0.1:8000
Backend container (FastAPI) --> PostGIS & Redis containers
```

`frontend/.assetsignore` excludes `_headers` and `js/README.md` from static asset publishing.

## Caching & Cache Purging

1. **Workers Static Assets (`frontend/_headers`):**
   - `/` and `/index.html`: `Cache-Control: no-cache` so browsers always fetch the latest entrypoint and versioned asset links on deploy.
   - `/js/*`: `Cache-Control: no-cache` (the browser revalidates with the ETag; `modulepreload` in `index.html` makes these checks run in parallel, so no module can be older than the page).
   - `/css/*`: `Cache-Control: public, max-age=300`.
   - `/data/boundaries/*`: `Cache-Control: public, max-age=86400, stale-while-revalidate=604800`.
   - `frontend/index.html` includes `<link rel="modulepreload">` for the entire ES-module graph to avoid sequential import waterfalls.
2. **Cloudflare Edge API Cache (`deploy/cloudflare/worker.js` + `wrangler.jsonc`):**
   - Public read-only `GET` requests are cached in `caches.default` keyed by full URL + `__drp_v=<DATA_VERSION>` and emit `X-DRP-Cache: HIT | MISS | BYPASS`:
     - `3600 s` edge TTL: `/api/v1/regions`, `/api/v1/regions/*`, `/api/v1/meta/*`
     - `600 s` edge TTL: `/api/v1/districts`, `/api/v1/districts/*`, `/api/v1/spatial/blank-spots`, `/api/v1/facilities`
   - Requests with `Authorization` or `Cookie` headers, `/api/v1/auth/*`, `/api/v1/chat*`, `/api/v1/simulation/*`, `/api/v1/rag/*`, `/api/v1/watchdog*`, `/health`, non-`GET` methods, and non-`200` responses are never cached.
3. **Backend Redis & Browser Session Cache:**
   - FastAPI caches province district lists (`cache:compliance:scores:<prov>`), single kecamatan scorecards (`cache:compliance:scorecard:<code>`), regions (`cache:regions:*`), and standards (`cache:meta:standards:<db>`) in Redis (`REDIS_CACHE_TTL`, 24 h), warmed asynchronously on startup across all `ACTIVE_PROVINCES`, and emits `Cache-Control: public, max-age=300` on those public `GET`s.
   - The frontend caches province lists, GeoJSON boundaries, and kecamatan details in in-memory `Map`s per browser session, deduplicates parallel `GET`s, and renders GeoJSON district outlines immediately while compliance scores load.

### How to Purge / Invalidate Caches

- **Frontend code or boundary GeoJSON update:** Bump `APP_VERSION` in `frontend/js/config.js` and the matching `?v=` query parameter on `/css/style.css`, `/css/regions.css`, `/js/main.js`, and its `modulepreload` tag in `frontend/index.html`, then redeploy the Worker (`npx wrangler deploy`). JS modules are always revalidated (`no-cache`), CSS within 5 minutes, and boundary GeoJSON URLs carry `?v=` so they change immediately.
- **Database / compliance data reload:**
  1. Rerunning `pipeline/load_region.py` or `pipeline/boundary_loader.py` now deletes the stale backend Redis keys itself (`cache:compliance:scores:<prov>`, legacy `cache:compliance:scores` when province is `31`, `cache:compliance:scorecard:<prov>.*`, `cache:regions:*`, and `cache:agent:*`) so the backend rebuilds them in its canonical shape. For manual DB edits or `regulatory_standards` changes, flush Redis keys (`cache:compliance:*`, `cache:regions:*`, `cache:meta:standards:*`, `cache:agent:*`) and restart `backend` (which re-warms Redis in the background).
  2. The Cloudflare edge API cache still needs a `DATA_VERSION` bump in `deploy/cloudflare/wrangler.jsonc` and `npx wrangler deploy` from `deploy/cloudflare` to purge immediately (otherwise stale responses remain until edge TTL expires: `1 h` for `/api/v1/regions*` & `/api/v1/meta/*`, `10 min` for `/api/v1/districts*`, `/api/v1/spatial/blank-spots`, & `/api/v1/facilities`).

## 1. Set Worker Secret

Generate a random shared secret and upload it to the Worker (must match `EDGE_SHARED_SECRET` in the backend):

```bash
cd deploy/cloudflare
npx wrangler secret put EDGE_SHARED_SECRET
```

## 2. Deploy Worker

```bash
cd deploy/cloudflare
npx wrangler deploy
```

## 3. Redeploy Backend (from a clean git archive export)

Export the branch into a deploy directory (do not run production compose directly from the shared dev working tree):

```bash
DEPLOY_DIR=$HOME/deploy/drp-$(git rev-parse --short HEAD)
mkdir -p "$DEPLOY_DIR"
git archive HEAD | tar -x -C "$DEPLOY_DIR"
```

Create `$DEPLOY_DIR/docker/.env` with at least:

```env
BACKEND_PORT=127.0.0.1:8000
AUTH_JWT_SECRET=<random-secret>
EDGE_SHARED_SECRET=<same-secret-as-worker>
ACTIVE_PROVINCES=31,32,33,34,35,36
```

(`ACTIVE_PROVINCES` defaults to `31` if omitted; list only provinces already loaded in the live database.)

Run `migrate_multiregion.py` on the database before starting a new backend.

Rebuild and restart only `backend` and `watchdog` (keeping `db` and `cache` running):

```bash
cd "$DEPLOY_DIR"
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --build --no-deps backend watchdog
```

## 4. Adding a Region to Live

For the full staging-to-live procedure (loading with `pipeline/load_region.py`, schema migration, single-transaction copy, Redis scorecard cache flush, and Worker/backend redeploy), see [`docs/REGIONS.md`](../../docs/REGIONS.md).

## 5. Cloudflare Tunnel Container

`cloudflared` runs in its own container with `--network host` so it can reach `127.0.0.1:8000` on the host, using a `tunnel.env` file (`TUNNEL_TOKEN=<token>`, mode `0600`) outside the repo:

```bash
docker run -d --name drp_tunnel --restart unless-stopped --network host --env-file /path/to/tunnel.env cloudflare/cloudflared:latest tunnel --no-autoupdate run
```

## Testing Note

The local campus network blocks `*.digilabui.cloud`. Verify live deployments from the server via the `workers.dev` URL (`https://drp.digilabui.workers.dev/health`).
