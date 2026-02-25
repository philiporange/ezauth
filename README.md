# EZAuth

Multi-tenant authentication service. Drop-in auth for any web app — email signup, magic link sign-in, password auth, JWT sessions, JWKS, cross-domain SSO, and an admin dashboard.

Built with FastAPI, PostgreSQL, Redis, and AWS SES.

## Features

- **Multi-tenant**: Each application gets its own users, keys, sessions, and email config
- **Email auth**: Signup with verification link, magic link sign-in, password sign-in
- **RS256 JWTs**: Per-app RSA key pairs with standard JWKS endpoint for offline verification
- **Session management**: Short-lived JWT (15min) + long-lived refresh token (30 days) with rotation
- **Rate limiting**: Redis-backed per-IP and per-email rate limiting with multi-tenant isolation
- **Cross-domain SSO**: Bridge/exchange pattern for satellite domains
- **Admin dashboard**: Jinja2 + HTMX UI for managing tenants, apps, domains, users, and email templates
- **Browser SDK**: Plain JS (<5KB), zero dependencies — IIFE, ESM, and CJS builds
- **Python server SDK**: `pip install ezauth-sdk` with FastAPI/Starlette middleware
- **Hashcash proof-of-work**: Argon2id-based challenge/response on signup to prevent abuse — configurable difficulty, ~1-3s client cost, single hash server verification
- **CLI tool**: `ezauth` command-line client for signup, login, whoami, logout — solves hashcash challenges automatically
- **Custom domains**: CNAME verification with optional ACME TLS provisioning

## Quick Start

### Prerequisites

- Python 3.11+
- Docker (for PostgreSQL + Redis)
- AWS credentials configured (for SES email sending)

### 1. Clone and install

```bash
cd ezauth
cp .env.example .env
# Edit .env with your config (especially SES_SENDER, DASHBOARD_SECRET_KEY)

pip install -e ".[dev]"
```

### 2. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL 16 on port 5432 and Redis 7 on port 6379.

### 3. Run migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn ezauth.main:create_app --factory --reload
```

The server starts at `http://localhost:8000`. Verify with:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 5. Access the dashboard

Navigate to `http://localhost:8000/dashboard` and log in with the `DASHBOARD_SECRET_KEY` from your `.env`.

From the dashboard you can:
- Create tenants and applications
- View publishable keys (`pk_test_...`) and secret keys (`sk_test_...`)
- Add and verify custom domains
- Browse users
- Edit email templates

## Architecture

```
ezauth/
├── src/ezauth/
│   ├── main.py              # FastAPI app factory + lifespan
│   ├── config.py            # pydantic-settings configuration
│   ├── crypto.py            # Token generation, SHA-256, constant-time compare
│   ├── ratelimiter.py       # Redis-backed rate limiter
│   ├── dependencies.py      # FastAPI deps: DB, Redis, app resolution, session auth
│   ├── db/                  # SQLAlchemy async engine, base models, Redis pool
│   ├── models/              # 7 SQLAlchemy models (tenant, application, user, ...)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # Business logic (auth, sessions, tokens, mail, ...)
│   ├── api/
│   │   ├── frontend/        # Browser-facing routes (signup, signin, verify, SSO)
│   │   └── backend/         # Server-facing routes (users CRUD, session mgmt, JWKS)
│   ├── dashboard/           # Jinja2 + HTMX admin UI
│   └── mail/templates/      # Mustache email templates (verification, magic link, ...)
├── cli/                         # CLI tool (pip install -e cli/)
│   └── src/ezauth_cli/         # click + httpx + argon2-cffi + rich
├── sdk/
│   ├── browser/             # Plain JS browser SDK
│   └── python-server/       # Python server SDK (pip-installable)
├── tests/                   # pytest + pytest-asyncio test suite
├── alembic/                 # Database migrations
├── docker-compose.yml       # PostgreSQL 16 + Redis 7
└── pyproject.toml
```

## API Reference

### Frontend Routes (publishable key auth)

All frontend routes require an `X-Publishable-Key` header or resolve the app from the request `Host`.

#### `POST /v1/challenges`

Request a hashcash proof-of-work challenge (required before signup when hashcash is enabled).

```bash
curl -X POST http://localhost:8000/v1/challenges \
  -H "X-Publishable-Key: pk_test_..."
```

Response:
```json
{
  "challenge": "ae17805f0ffd9aeac8f98421498d40cb",
  "difficulty": 5,
  "algorithm": "argon2id",
  "params": {"time_cost": 2, "memory_cost": 19456, "parallelism": 1, "hash_len": 32},
  "expires_in": 300
}
```

#### `POST /v1/signups`

Register a new user and send a verification email. When hashcash is enabled, a solved proof must be included.

```bash
# 1. Get a challenge
CHALLENGE=$(curl -s -X POST http://localhost:8000/v1/challenges \
  -H "X-Publishable-Key: pk_test_..." | jq -r .challenge)

# 2. Solve the challenge (use the CLI or SDK), then submit:
curl -X POST http://localhost:8000/v1/signups \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "optional",
    "hashcash": {"challenge": "'$CHALLENGE'", "nonce": "<solved_nonce>"}
  }'
```

Response: `{"user_id": "...", "status": "verification_sent"}`

#### `POST /v1/signins`

Sign in via magic link or password.

```bash
# Magic link (default)
curl -X POST http://localhost:8000/v1/signins \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com"}'

# Password
curl -X POST http://localhost:8000/v1/signins \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "...", "strategy": "password"}'
```

#### `POST /v1/verify-code`

Verify a 6-digit code (from email) and create a session. Used by the CLI and non-browser clients.

```bash
curl -X POST http://localhost:8000/v1/verify-code \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "code": "123456"}'
```

Response: `{"access_token": "eyJ...", "refresh_token": "...", "user_id": "...", "session_id": "..."}`

#### `GET /v1/email/verify?token=...`

Consumes a verification or magic link token. Sets the `__session` cookie and redirects to the app's `redirect_url`.

#### `GET /v1/me`

Returns the authenticated user's info. Requires a valid `__session` cookie or `Authorization: Bearer <jwt>`.

```bash
curl http://localhost:8000/v1/me \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Cookie: __session=eyJ..."
```

Response: `{"user_id": "...", "email": "user@example.com", "email_verified": true}`

#### `POST /v1/tokens/session`

Refresh an expired JWT using a refresh token.

```bash
curl -X POST http://localhost:8000/v1/tokens/session \
  -H "X-Publishable-Key: pk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "..."}'
```

#### `POST /v1/sessions/logout`

Revokes the current session.

#### `GET /v1/sso/bridge?return_to=https://satellite.example.com/callback`

Initiates cross-domain SSO. Redirects to the satellite domain with an exchange token.

#### `POST /v1/sso/exchange`

Exchanges an SSO token for a session on the satellite domain.

### Backend Routes (secret key auth)

Backend routes require `Authorization: Bearer sk_test_...` or `sk_live_...`.

#### `GET /v1/users`

List users for the application.

#### `POST /v1/users`

Create a user server-side (skips email verification).

#### `GET /v1/users/{user_id}`

Get a specific user.

#### `POST /v1/sessions/revoke`

Revoke a session by ID.

#### `POST /v1/sign_in_tokens`

Create a short-lived sign-in token for server-to-server auth.

```bash
curl -X POST http://localhost:8000/v1/sign_in_tokens \
  -H "Authorization: Bearer sk_test_..." \
  -H "Content-Type: application/json" \
  -d '{"user_id": "...", "expires_in_seconds": 300}'
```

### Public Routes

#### `GET /.well-known/jwks.json`

Returns the JWKS for an application (resolved from `X-Publishable-Key` or `Host`). Used by SDKs and services to verify JWTs offline.

## Browser SDK

Zero-dependency JavaScript SDK for browser integration.

### Build

```bash
cd sdk/browser
npm install
npm run build
```

Produces `dist/ezauth.iife.js`, `dist/ezauth.esm.js`, and `dist/ezauth.cjs.js`.

### Usage

```html
<script src="https://your-cdn.com/ezauth.iife.js"></script>
<script>
  const gk = EZAuth.init({
    publishableKey: 'pk_test_...',
    authDomain: 'https://auth.example.com',
  });

  // Sign up
  await gk.signUp({ email: 'user@example.com', password: 'optional' });

  // Sign in with magic link
  await gk.signIn({ email: 'user@example.com' });

  // Handle email link callback (on redirect back)
  await gk.handleEmailLinkCallback();

  // Get current session
  const session = await gk.getSession();

  // Get JWT for API calls
  const token = await gk.getToken();

  // Sign out
  await gk.signOut();
</script>
```

Or as an ES module:

```js
import { init } from '@ezauth/browser';

const gk = init({ publishableKey: 'pk_test_...', authDomain: '...' });
```

## Python Server SDK

Verify EZAuth JWTs in your FastAPI/Starlette backend.

### Install

```bash
pip install ezauth-sdk
# or from the local package:
pip install -e sdk/python-server
```

### Usage with middleware

```python
from fastapi import FastAPI
from ezauth_sdk import EZAuthMiddleware

app = FastAPI()
app.add_middleware(
    EZAuthMiddleware,
    auth_domain="https://auth.example.com",
    public_paths=["/health", "/docs"],
)

@app.get("/protected")
async def protected(request):
    auth = request.state.auth
    return {"user_id": auth.user_id}
```

### Usage with dependency injection

```python
from ezauth_sdk import JWKSClient, authenticate_request, AuthenticationError

jwks_client = JWKSClient("https://auth.example.com")

async def get_auth(request):
    try:
        return await authenticate_request(request, jwks_client)
    except AuthenticationError:
        raise HTTPException(401)
```

## CLI Tool

Command-line client for interacting with an EZAuth instance. Handles hashcash proof-of-work automatically.

### Install

```bash
cd cli
pip install -e .
```

### Usage

```bash
# Configure server URL and publishable key
ezauth configure

# Sign up (solves hashcash, prompts for verification code)
ezauth signup

# Log in (password or magic link)
ezauth login

# Show current session
ezauth whoami

# Log out
ezauth logout
```

Configuration is stored in `~/.config/ezauth/config.json`.

## Database Schema

Seven tables with proper indexes and constraints:

| Table | Purpose |
|-------|---------|
| `tenants` | Top-level accounts (organizations) |
| `applications` | Apps within a tenant (dev/prod environments, keys, JWT config) |
| `users` | Users per application (case-insensitive email uniqueness) |
| `auth_attempts` | Ephemeral token records (signup, verify, magic link) — hashed, single-use |
| `sessions` | Active sessions (refresh token hash, revocation, versioning) |
| `domains` | Custom domains per app (CNAME verification) |
| `audit_log` | Append-only event log (signups, sign-ins, logouts, etc.) |

## Configuration

All settings via environment variables (see `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | — | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `SES_REGION` | `us-east-1` | AWS SES region |
| `SES_SENDER` | — | Default sender email address |
| `SES_SENDER_NAME` | `EZAuth` | Default sender display name |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | JWT lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token lifetime |
| `SESSION_COOKIE_NAME` | `__session` | Cookie name for JWT |
| `DASHBOARD_SECRET_KEY` | — | Password for dashboard login |
| `HASHCASH_ENABLED` | `true` | Require proof-of-work on signup |
| `HASHCASH_DIFFICULTY` | `5` | Leading zero bits required (~32 attempts avg) |
| `HASHCASH_CHALLENGE_TTL` | `300` | Challenge expiry in seconds |

## Security Design

- **RS256 JWTs**: Each app has its own RSA 2048 key pair. Private key never leaves the server. Public key available via JWKS for offline verification.
- **Token hashing**: All tokens (verification, magic link, refresh) stored as SHA-256 hashes. Raw tokens are never persisted.
- **Atomic consumption**: Token use is a single `UPDATE ... WHERE hash=? AND status='pending' AND expires_at > now()` — no TOCTOU race conditions.
- **Argon2id passwords**: Industry-standard password hashing with automatic rehashing on parameter upgrades.
- **Hashcash proof-of-work**: Signup requires solving an argon2id challenge (~1-3s of client computation). Challenges are single-use (atomic Redis get+delete) with a 5-minute TTL. Configurable difficulty in leading zero bits.
- **Rate limiting**: Per-IP and per-email rate limits with Redis. Multi-tenant key isolation prevents cross-app interference.
- **CORS**: Per-app allowed origins (no wildcard when credentials are enabled).
- **Path traversal protection**: Email template editor validates names against `^[a-z0-9_-]+$` with realpath verification.

## Testing

```bash
# Run unit tests (no DB/Redis required)
pytest tests/test_services/ -v

# Run all tests (requires PostgreSQL + Redis)
pytest -v
```

The test suite uses `pytest-asyncio`, `fakeredis` for Redis tests, and `factory-boy` for test data.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run with auto-reload
uvicorn ezauth.main:create_app --factory --reload

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Create a new migration
alembic revision --autogenerate -m "description"
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Web framework | FastAPI (async) |
| Database | PostgreSQL 16 via asyncpg + SQLAlchemy 2.0 |
| Cache/Rate limiting | Redis 7 |
| Migrations | Alembic (async) |
| Email | AWS SES + Chevron (Mustache) + Premailer |
| JWT | python-jose with RS256 |
| Password hashing | argon2-cffi |
| Dashboard | Jinja2 + HTMX |
| Browser SDK | Plain JS + Rollup |
| Server SDK | python-jose + httpx |
| CLI | click + httpx + argon2-cffi + rich |

## License

Private — all rights reserved.
