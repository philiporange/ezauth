# Deployment

ezAuth runs on a Hetzner VPS (Debian 13/trixie, ARM64) behind Caddy.

No secrets belong in this file. Everything below uses placeholders; the real
values live in `/opt/ezauth/.env` on the server, which is not in git.

## Server access

```
ssh hetzner
```

Host is configured in `~/.ssh/config`. The deploy user is `sam`. The application runs as a dedicated `ezauth` system user (uid 997).

## Architecture

```
Internet
  │
  ├─ api.ezauth.org ──► Caddy (TLS + reverse proxy) ──► uvicorn :8001
  └─ ezauth.org ───────► Caddy (static files from /srv/ezauth)
```

- **Caddy** handles TLS (auto Let's Encrypt) and reverse-proxies to uvicorn
- **Uvicorn** runs the FastAPI app on `127.0.0.1:8001`
- **PostgreSQL 17** on localhost:5432, database `ezauth`, user `ezauth`
- **Redis 8** on localhost:6379/1

## Filesystem layout

```
/opt/ezauth/              # Application root
├── .env                  # Environment variables (secrets)
├── .venv/                # Python 3.13 virtual environment
├── alembic/              # Database migrations
├── alembic.ini           # Alembic config (reads DATABASE_URL from the env)
├── src/ezauth/           # Application source
├── sdk/                  # Browser + Python SDKs
├── cli/                  # CLI client
└── tests/

/etc/systemd/system/ezauth.service   # systemd unit
/etc/caddy/Caddyfile                 # Caddy reverse proxy config
```

## systemd service

```ini
[Unit]
Description=ezAuth API
After=network.target postgresql.service redis-server.service
Requires=postgresql.service redis-server.service

[Service]
Type=exec
User=ezauth
Group=ezauth
WorkingDirectory=/opt/ezauth
ExecStart=/opt/ezauth/.venv/bin/uvicorn ezauth.main:app \
    --host 127.0.0.1 --port 8001 \
    --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5
EnvironmentFile=/opt/ezauth/.env

[Install]
WantedBy=multi-user.target
```

`--proxy-headers --forwarded-allow-ips 127.0.0.1` is not optional. Without it
every request arrives with `client.host == 127.0.0.1`, which is Caddy, and the
per-IP rate limits on signup, sign-in and code verification degrade into one
shared bucket for the whole internet. `--forwarded-allow-ips` must name the
proxy's address, not `*`, so that a request arriving from anywhere else cannot
spoof `X-Forwarded-For`.

All four services are enabled at boot: `ezauth`, `caddy`, `postgresql`, `redis-server`.

## Caddy config

```
api.ezauth.org {
    reverse_proxy 127.0.0.1:8001
}

ezauth.org {
    root * /srv/ezauth
    file_server
}
```

## Environment variables

`/opt/ezauth/.env` holds the deployment's configuration. `.env.example` in the
repository lists every setting with its default and a description; copy it and
fill in the deployment values. The production-critical ones:

```
ENVIRONMENT=production
PUBLIC_BASE_URL=https://api.ezauth.org
DATABASE_URL=postgresql+asyncpg://ezauth:<password>@localhost:5432/ezauth
REDIS_URL=redis://localhost:6379/1
SES_REGION=<aws-region>
SES_SENDER=<verified-sender@your-domain>
SES_SENDER_NAME=ezAuth
SESSION_COOKIE_SECURE=true
DASHBOARD_ADMIN_EMAILS=<admin@your-domain>
DASHBOARD_ALLOWED_ORIGINS=https://ezauth.org
```

The application refuses to start when `ENVIRONMENT=production` and any of
`DATABASE_URL`, `REDIS_URL`, `SES_SENDER` or `PUBLIC_BASE_URL` is still at its
development default, when `PUBLIC_BASE_URL` is not https, or when
`SESSION_COOKIE_SECURE` is off. A misconfigured deploy fails at boot rather
than running with development credentials.

AWS credentials for SES come from the standard AWS chain (instance role or
`~/.aws/credentials`); set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in
`.env` only when neither is available.

## Deploy procedure

There is no CI/CD. Deployment is manual via rsync.

### 1. Sync code

```bash
rsync -avz \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='*.pyc' \
  /home/sam/Code/ezauth/ hetzner:/opt/ezauth/
```

The `.env` file is excluded to avoid overwriting production secrets.

### 2. Run migrations

Always run before restarting the service, and always after a backup. Alembic
takes the database URL from `DATABASE_URL`, so the unit's `EnvironmentFile`
has to be sourced when running it by hand:

```bash
ssh hetzner "set -a && . /opt/ezauth/.env && set +a && \
  cd /opt/ezauth && .venv/bin/alembic upgrade head"
```

Check what is pending first with `alembic current` and `alembic heads`; roll a
single revision back with `alembic downgrade -1` if a deploy has to be undone.

### 3. Restart the service

```bash
ssh hetzner "sudo systemctl restart ezauth"
```

### 4. Verify

```bash
curl -s https://api.ezauth.org/health
# {"status":"ok"}

ssh hetzner "sudo systemctl status ezauth --no-pager"
```

## Docker

`docker-compose.yml` runs Postgres, Redis and the application together, and
the app service applies `alembic upgrade head` before uvicorn starts. It reads
the Postgres credentials and the host-side ports from `.env`, and binds every
published port to `127.0.0.1`.

```bash
cp .env.example .env   # then edit
docker compose up -d --build
```

The image (see `Dockerfile`) installs only the runtime dependencies, runs as
the unprivileged `ezauth` user, and starts uvicorn with `--proxy-headers`. When
running it behind a proxy on another host, replace the `*` in the compose
command's `--forwarded-allow-ips` with the proxy's address.

## Backups

`pg_dump` in custom format, nightly, retained for 30 days:

```bash
sudo -u postgres install -d -o postgres -g postgres -m 0700 /var/backups/ezauth

sudo -u postgres pg_dump --format=custom --compress=9 \
  --file=/var/backups/ezauth/ezauth-$(date +%F).dump ezauth
```

As a systemd timer, `/etc/systemd/system/ezauth-backup.service`:

```ini
[Unit]
Description=ezAuth database backup
After=postgresql.service

[Service]
Type=oneshot
User=postgres
ExecStart=/bin/sh -c '/usr/bin/pg_dump --format=custom --compress=9 \
  --file=/var/backups/ezauth/ezauth-$(date +%%F).dump ezauth'
ExecStartPost=/usr/bin/find /var/backups/ezauth -name "ezauth-*.dump" -mtime +30 -delete
```

and `/etc/systemd/system/ezauth-backup.timer`:

```ini
[Unit]
Description=Nightly ezAuth database backup

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
ssh hetzner "sudo systemctl enable --now ezauth-backup.timer"
```

Copy the dumps off the host; a backup on the same disk as the database is not
a backup. Restore into an empty database:

```bash
sudo -u postgres createdb ezauth_restore
sudo -u postgres pg_restore --dbname=ezauth_restore /var/backups/ezauth/ezauth-2026-01-01.dump
```

Verify a restore periodically. An untested backup is an assumption.

Redis holds only rate-limit counters, hashcash challenges, OAuth state nonces
and dashboard sessions, all of which are short-lived and reconstructible, so it
is not backed up. Losing it signs dashboard users out and clears rate-limit
windows.

## Logs

The application logs to stdout, which systemd captures in the journal.

```bash
# Recent logs
ssh hetzner "sudo journalctl -u ezauth --no-pager -n 50"

# Follow logs
ssh hetzner "sudo journalctl -u ezauth -f"
```

Rotation is the journal's own, configured in `/etc/systemd/journald.conf`:

```ini
[Journal]
Storage=persistent
SystemMaxUse=2G
MaxRetentionSec=30day
```

```bash
ssh hetzner "sudo systemctl restart systemd-journald"
```

Caddy writes its own access logs; rotate them with logrotate,
`/etc/logrotate.d/caddy`:

```
/var/log/caddy/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    su caddy caddy
    postrotate
        systemctl reload caddy
    endscript
}
```

Postgres log retention is set in `postgresql.conf` with
`log_rotation_age = 1d` and `log_truncate_on_rotation = on`.

## Rotating JWK signing keys

Signing keys are per application and live in `application_keys`. One row per
application is active and signs new tokens; rotating adds a new active key and
marks the previous one retired. `/.well-known/jwks.json` publishes the active
key and every retired key that has not yet been dropped, so tokens signed
seconds before a rotation keep verifying and no client sees a 401.

Rotation is therefore two steps, and the gap between them is deliberate.

Step one, rotate. Authenticate with the application's secret key:

```bash
curl -X POST https://api.ezauth.org/v1/keys/rotate \
  -H "Authorization: Bearer sk_live_..."
```

New tokens are immediately signed with the new key. Confirm both keys are
published, and that relying parties can still verify existing tokens:

```bash
curl -s "https://api.ezauth.org/v1/keys" -H "Authorization: Bearer sk_live_..."
curl -s "https://api.ezauth.org/.well-known/jwks.json?app_id=<application-uuid>"
```

Step two, drop the retired key. Wait until every token signed by it has
expired, which is `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (15 by default) plus any
JWKS caching your relying parties do. Then:

```bash
curl -X DELETE https://api.ezauth.org/v1/keys/retired \
  -H "Authorization: Bearer sk_live_..."
```

Until this second step runs, a leaked key still verifies. For a suspected
compromise, run both steps back to back and accept that sessions signed with
the old key are cut off; for routine rotation, leave the gap.

Refresh tokens are unaffected either way, because they are opaque random
strings stored as hashes rather than signed tokens.

## Database access

```bash
ssh hetzner "sudo -u ezauth psql -d ezauth"
```

Or from the `sam` user (peer auth configured):

```bash
ssh hetzner "psql -U ezauth -d ezauth"
```

## Installing new Python dependencies

```bash
ssh hetzner "/opt/ezauth/.venv/bin/pip install -r /opt/ezauth/requirements.txt"
```

Then restart the service.

## Version info

| Component  | Version       |
|------------|---------------|
| OS         | Debian 13 (trixie), ARM64 |
| Python     | 3.13.5        |
| PostgreSQL | 17.8          |
| Redis      | 8.0.2         |
| Caddy      | 2.11.1        |
