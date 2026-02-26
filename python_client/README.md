# ezauth-client

Python client for EZAuth — covers both frontend (publishable key) auth flows and backend (secret key) admin operations.

Requires Python 3.11+. Only dependency is [httpx](https://www.python-httpx.org/).

## Install

```bash
pip install ezauth-client
```

## Quick start

### Backend (secret key)

```python
from ezauth_client import EZAuth

ez = EZAuth(
    base_url="https://your-ezauth-instance.com",
    secret_key="sk_live_...",
)

# Users
result = ez.users.list(limit=10)
user = ez.users.create("alice@example.com")
found = ez.users.get(user["id"])

# Sessions
ez.sessions.revoke(session_id)
token = ez.sessions.create_sign_in_token(user["id"])

# Custom tables
table = ez.tables.create("contacts", columns=[
    {"name": "name", "type": "text", "required": True},
    {"name": "age", "type": "int"},
])

ez.tables.rows.insert(table["id"], {"name": "Alice", "age": 30})

result = ez.tables.rows.query(
    table["id"],
    filter={"field": "age", "op": "gte", "value": 18},
    sort={"field": "name", "dir": "asc"},
    limit=50,
)

# Buckets & objects
bucket = ez.buckets.create("avatars")
ez.buckets.objects.put(bucket["id"], "alice.png", image_bytes, "image/png")
data, content_type = ez.buckets.objects.get(bucket["id"], "alice.png")

# Storage usage
usage = ez.storage.tables()
print(f"{usage['used_percent']}% used")
```

### Frontend (publishable key)

```python
from ezauth_client import EZAuth

ez = EZAuth(
    base_url="https://your-ezauth-instance.com",
    publishable_key="pk_live_...",
)

ez.auth.sign_up("alice@example.com", password="s3cret")
session = ez.auth.sign_in("alice@example.com", password="s3cret")
me = ez.auth.get_session(access_token=session["access_token"])
ez.auth.sign_out(access_token=session["access_token"])

# OAuth
result = ez.auth.sign_in_with_oauth("google", redirect_url="https://myapp.com/callback")
print(result["authorization_url"])  # redirect the user here
```

## Error handling

All methods raise `EZAuthError` on failure:

```python
from ezauth_client import EZAuth, EZAuthError

try:
    ez.users.get("nonexistent")
except EZAuthError as e:
    print(e.message)  # "User not found"
    print(e.status)   # 404
    print(e.code)     # error code string, if provided
```

## API reference

### `EZAuth(base_url, *, secret_key?, publishable_key?, access_token?)`

### `ez.auth` (publishable key)

| Method | Description |
|--------|-------------|
| `sign_up(email, *, password?, redirect_url?, hashcash?)` | Create a new user |
| `sign_in(email, *, password?, strategy?, redirect_url?)` | Sign in |
| `sign_out(*, access_token?)` | Sign out current session |
| `verify_code(email, code)` | Verify a 6-digit code |
| `get_session(*, access_token?)` | Get current session/user |
| `refresh_token(refresh_token)` | Refresh an access token |
| `sso_exchange(token)` | Exchange an SSO token for a session |
| `sign_in_with_oauth(provider, redirect_url)` | Get OAuth authorization URL |
| `request_challenge()` | Request a hashcash challenge |

### `ez.users` (secret key)

| Method | Description |
|--------|-------------|
| `list(*, limit?, offset?, email?)` | List users |
| `create(email, *, password?)` | Create a user |
| `get(user_id)` | Get a user by ID |

### `ez.sessions` (secret key)

| Method | Description |
|--------|-------------|
| `revoke(session_id)` | Revoke a session |
| `create_sign_in_token(user_id, *, expires_in_seconds?)` | Create a sign-in token |

### `ez.tables` (secret key or publishable key + session)

| Method | Description |
|--------|-------------|
| `create(name, *, columns?)` | Create a table |
| `list()` | List all tables |
| `get(table_id)` | Get a table with columns |
| `delete(table_id)` | Delete a table |

### `ez.tables.columns`

| Method | Description |
|--------|-------------|
| `add(table_id, name, type, *, required?, default_value?, position?)` | Add a column |
| `update(table_id, column_id, *, name?, required?, default_value?, position?)` | Update a column |
| `delete(table_id, column_id)` | Delete a column |

### `ez.tables.rows`

| Method | Description |
|--------|-------------|
| `insert(table_id, data, *, user_id?)` | Insert a row |
| `get(table_id, row_id)` | Get a row |
| `update(table_id, row_id, data)` | Update a row (partial) |
| `delete(table_id, row_id)` | Delete a row |
| `query(table_id, *, filter?, sort?, limit?, cursor?)` | Query rows |

### `ez.buckets` (secret key or publishable key + session)

| Method | Description |
|--------|-------------|
| `create(name)` | Create a bucket |
| `list()` | List all buckets |
| `get(bucket_id)` | Get a bucket |
| `delete(bucket_id)` | Delete a bucket |

### `ez.buckets.objects`

| Method | Description |
|--------|-------------|
| `put(bucket_id, key, data, content_type?, *, user_id?)` | Upload an object |
| `get(bucket_id, key, *, user_id?)` | Download an object — returns `(bytes, content_type)` |
| `delete(bucket_id, key, *, user_id?)` | Delete an object |
| `list(bucket_id, *, user_id?, limit?, cursor?)` | List objects |

### `ez.storage`

| Method | Description |
|--------|-------------|
| `tables()` | Get table storage usage |
| `objects()` | Get object storage usage |
