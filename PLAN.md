# Bot Authentication via Public Key

## Overview

Add bot authentication alongside existing human (email/password) auth. Bots identify themselves with Ed25519 public keys instead of email addresses. To prevent mass account creation, bot signup requires a confirmed donation challenge from `https://api.confirmations.info`.

## Signup Flow

```
Bot                         EZAuth                      api.confirmations.info
 |                            |                                |
 |--- POST /challenges -------|------------------------------->|
 |<-- {challenge_id, chain, address, amount} ------------------|
 |                            |                                |
 |  (bot donates to EFF)      |                                |
 |  (monitor detects tx)      |                                |
 |                            |                                |
 |--- POST /v1/bot/signup --->|                                |
 |    {challenge_id,          |--- GET /challenges/{id} ------>|
 |     public_key}            |<-- {status: "CONFIRMED"} ------|
 |                            |                                |
 |<-- {bot_id} ---------------|                                |
```

1. Bot calls `POST https://api.confirmations.info/challenges` with `{chain, usd_amount}` (min $1). Gets back a `challenge_id` and an EFF donation address with an exact amount.
2. Bot sends the donation on-chain. The confirmations monitor detects it and marks the challenge `CONFIRMED`.
3. Bot calls `POST /v1/bot/signup` on EZAuth with `{challenge_id, public_key}`.
4. EZAuth calls `GET https://api.confirmations.info/challenges/{challenge_id}` and verifies `status == "CONFIRMED"`.
5. EZAuth stores the public key, marks the challenge_id as consumed (prevents reuse), creates the bot user.

## Auth Flow

```
Bot                         EZAuth
 |                            |
 |--- POST /v1/bot/auth ----->|
 |    {bot_id,                |
 |     timestamp,             |  verify sig, check timestamp
 |     signature}             |  create session
 |                            |
 |<-- {access_token,   -------|
 |     refresh_token}         |
```

1. Bot constructs a message: `ezauth:bot_auth:{app_id}:{bot_id}:{timestamp}` where timestamp is unix seconds.
2. Bot signs the message with its Ed25519 private key.
3. Bot calls `POST /v1/bot/auth` with `{bot_id, timestamp, signature}` (signature is base64-encoded).
4. EZAuth looks up the bot by ID, verifies the signature against the stored public key, checks the timestamp is within 5 minutes.
5. EZAuth creates a session and returns `{access_token, refresh_token, user_id, session_id}` -- same `SessionResponse` as human auth.

After auth, the bot uses the JWT exactly like a human user. Refresh, logout, `/v1/me` all work the same way.

## Data Model

Add three columns to the `users` table:

| Column | Type | Notes |
|---|---|---|
| `is_bot` | boolean | Default false. True for bot accounts. |
| `public_key_ed25519` | text, nullable | Base64-encoded 32-byte Ed25519 public key. Set for bots, null for humans. |
| `challenge_id` | text, nullable, unique | The confirmations challenge ID consumed during bot signup. Unique constraint prevents reuse. |

No new tables needed. Bot users are users -- they have sessions, appear in the backend user list, can be revoked, show up in audit logs. The `email` column is nullable for bots (bots don't have email addresses), so the existing NOT NULL constraint on `email` needs to become nullable, with a check constraint: `email IS NOT NULL OR is_bot = true`.

## New Files

**`src/ezauth/api/frontend/bots.py`** -- Two endpoints:

- `POST /v1/bot/signup` -- accepts `{challenge_id: str, public_key: str}`. Verifies with confirmations API, creates bot user.
- `POST /v1/bot/auth` -- accepts `{bot_id: str, timestamp: int, signature: str}`. Verifies Ed25519 signature, creates session.

**`src/ezauth/schemas/bot.py`** -- Request/response models:

- `BotSignupRequest` -- `{challenge_id: str, public_key: str}`
- `BotSignupResponse` -- `{bot_id: str, public_key: str}`
- `BotAuthRequest` -- `{bot_id: str, timestamp: int, signature: str}`

Auth response reuses existing `SessionResponse`.

**`alembic/versions/004_add_bot_fields.py`** -- Migration adding the three columns and loosening the email constraint.

## Changes to Existing Files

**`src/ezauth/models/user.py`** -- Add `is_bot`, `public_key_ed25519`, `challenge_id` columns. Make `email` nullable (keep the unique constraint on `(app_id, email_lower)` but only where `email IS NOT NULL`).

**`src/ezauth/api/router.py`** -- Include the bot router.

**`src/ezauth/services/auth.py`** -- Add `signup_bot()` function that calls confirmations API and creates the user. Add `auth_bot()` function that verifies Ed25519 signature and creates a session.

**`src/ezauth/config.py`** -- Add `confirmations_api_url` setting (default `https://api.confirmations.info`). Add `bot_auth_timestamp_tolerance` setting (default 300 seconds).

**`src/ezauth/dependencies.py`** -- No changes. Bot sessions use the same JWT, so `SessionDep` works as-is.

**`src/ezauth/docs/index.html`** -- Add Bot API section documenting both endpoints.

## Crypto

Ed25519 via the `cryptography` library (already a dependency). Public keys are 32 bytes, base64-encoded for transport and storage. Signatures are 64 bytes, base64-encoded.

Verification:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
key.verify(base64.b64decode(signature_b64), message.encode())
```

## Security Considerations

- **Replay protection**: Timestamp in signed message, 5-minute window, checked server-side.
- **Cross-app protection**: `app_id` is included in the signed message, so a signature for app A cannot be used on app B.
- **Challenge reuse**: Unique constraint on `challenge_id` column prevents one donation from creating multiple bots.
- **Rate limiting**: Bot signup inherits the existing IP rate limit. Bot auth gets its own rate limit (same as signin: 10/min per IP).
- **No email enumeration**: Bots don't have email, so there's nothing to enumerate.

## Tests

- `tests/test_api/test_bot_signup.py` -- Test signup with mocked confirmations API responses (confirmed, pending, expired, already-used challenge).
- `tests/test_api/test_bot_auth.py` -- Test auth with valid signature, wrong key, expired timestamp, wrong app_id.
- `tests/test_services/test_bot_crypto.py` -- Test Ed25519 sign/verify round-trip.
