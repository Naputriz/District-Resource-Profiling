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

`frontend/.assetsignore` excludes `js/README.md` from static asset publishing.

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
