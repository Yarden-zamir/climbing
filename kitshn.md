# KitSHn Recipe

This repository deploys with [KitSHn](https://github.com/Yarden-zamir/kitshn). A push to `main`
runs `.github/workflows/kitshn.yml`, which SSHes into the VPS and brings the `prod` environment up
from `compose.yml`. There are no pull request previews: the app is a stateful singleton (one Redis
holds the club's data), see `.kitshn.yaml`.

## Services

- `app`: this FastAPI app, built from `Dockerfile`. Uvicorn listens on the KitSHn Unix socket
  (`KITSHN_DEFAULT_SOCKET`), so no port and no socat sidecar. Runs with `ENVIRONMENT=production`.
  `${KITSHN_DATA_DIR}` is mounted at `/data`: `climbing.duckdb` (the whole database), `backups/`
  (daily snapshots, 14 kept) and `keys/` (VAPID keys written from params on start).
The legacy Redis data was imported on 2026-09-29 (`scripts/migrate_redis_to_duckdb.py`). The old
Redis data directory `redis/` and `redis/backup-before-duckdb.rdb` stay under the persistent dir as a
fallback; delete them once the DuckDB store has proven itself.

Keep the VAPID keys: existing push subscriptions are bound to them.

Restore from a snapshot: stop the app (`kitshn compose ... -- stop app`), replace
`/persistent/Yarden-zamir/climbing/prod/climbing.duckdb` with the snapshot, start the app.

## Routing

`Caddyfile.j2` serves `climbing.yarden-zamir.com`, `onion-climbers.com`, `www.onion-climbers.com`
and `climbing-next.yarden-zamir.com`. The last one resolves through the `*.yarden-zamir.com`
wildcard and is the way to check the deployment before the DNS records of the other hosts move to
this VPS. Remove it after the move.

## Params

GitHub Environment `prod`, names carry the `KITSHN_` prefix:

| Param | Kind | Purpose |
| --- | --- | --- |
| `BASE_URL` | variable | Public origin used for OAuth redirect URIs (`https://onion-climbers.com`) |
| `GOOGLE_CLIENT_ID` | variable | Google OAuth client |
| `GOOGLE_CLIENT_SECRET` | secret | Google OAuth client |
| `SECRET_KEY` | secret | Signs session cookies, OAuth state and JWT tokens |
| `VAPID_PRIVATE_KEY_B64`, `VAPID_PUBLIC_KEY_B64` | secret | Web push keys, base64 of the PEM files |

Values were copied from the previous host's systemd unit on 2026-09-29 and must be rotated.

## Operate

```bash
kitshn diagnose Yarden-zamir/climbing --vps-host yarden-zamir-vps-2
kitshn status Yarden-zamir/climbing --vps-host yarden-zamir-vps-2
kitshn logs Yarden-zamir/climbing app --vps-host yarden-zamir-vps-2
kitshn compose Yarden-zamir/climbing --vps-host yarden-zamir-vps-2 -- exec redis redis-cli -a "$REDIS_PASSWORD" ping
kitshn try --vps-host yarden-zamir-vps-2 --params-file <params.env> --path /api/health
```

Data scripts (for example `scripts/enrich_locations.py`) run inside the app container while the app is
stopped, because DuckDB allows one writer process:
`kitshn compose Yarden-zamir/climbing --vps-host yarden-zamir-vps-2 -- stop app`, then
`kitshn compose Yarden-zamir/climbing --vps-host yarden-zamir-vps-2 -- run --rm app uv run --no-sync python scripts/enrich_locations.py --apply`, then `-- start app`.

## Origin

- Generated from: https://github.com/Yarden-zamir/kitshn/blob/v0.2.0/src/kitshn/repo_init.py
- KitSHn commit: `v0.2.0`
