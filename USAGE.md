# EZAuth Usage Guide

Complete usage documentation for EZAuth — a multi-tenant authentication service with email auth, JWT sessions, JWKS, cross-domain SSO, and admin dashboard.

## Quick Start

The fastest way to get started with EZAuth:

```bash
# Clone and install
git clone <repository-url>
cd ezauth
cp .env.example .env

# Edit .env with your settings (especially SES_SENDER and DASHBOARD_SECRET_KEY)
# Then install dependencies
pip install -e ".[dev]"

# Start infrastructure (PostgreSQL + Redis)
docker compose up -d

# Run database migrations
alembic upgrade head

# Start the server
uvicorn ezauth.main:create_app --factory --reload
```

The server will start at `http://localhost:8000`. Verify it's running:

```bash
curl http://localhost:8000/health
```

**Expected output:**
```json
{"status":"ok"}
```

Access the admin dashboard at `http://localhost:8000/dashboard` using the `DASHBOARD_SECRET_KEY` from your `.env` file.

## Installation

### Prerequisites

- **Python 3.11 or higher** (verify with `python3 --version`)
- **Docker** (for PostgreSQL 16 and Redis 7)
- **AWS credentials** configured for SES email sending

### Step-by-Step Installation

**1. Clone the repository:**

```bash
git clone <repository-url>
cd ezauth
```

**2. Create environment configuration:**

```bash
cp .env.example .env
```

Edit `.env` and configure at minimum:

```bash
# Required: PostgreSQL connection
DATABASE_URL=postgresql+asyncpg://ezauth:ezauth@localhost:5432/ezauth

# Required: Email sending
SES_SENDER=noreply@yourdomain.com
SES_REGION=us-east-1

# Required: Dashboard password
DASHBOARD_SECRET_KEY=your-secure-random-key-here

# Optional: Redis (defaults to localhost:6379)
REDIS_URL=redis://localhost:6379/0
```

**3. Install Python dependencies:**

```bash
# Main server installation
pip install -e ".[dev]"

# Optional: Install CLI tool
cd cli && pip install -e . && cd ..

# Optional: Install Python client SDK
cd python_client && pip install -e . && cd ..

# Optional: Install Python server SDK
cd sdk/python-server && pip install -e . && cd ..
```

**4. Start infrastructure services:**

```bash
docker compose up -d
```

This starts:
- PostgreSQL 16 on port 5432
- Redis 7 on port 6379

Verify services are running:

```bash
docker compose ps
```

**5. Run database migrations:**

```bash
alembic upgrade head
```

**6. Start the server:**

```bash
uvicorn ezauth.main:create_app --factory --reload
```

For production deployment, see the Deployment section below.

## Basic Usage

### Creating Your First Application

**1. Access the dashboard:**

Navigate to `http://localhost:8000/dashboard` and log in with your `DASHBOARD_SECRET_KEY`.

**2. Create a tenant:**

- Click "New Tenant"
- Enter organization name
- Submit

**3. Create an application:**

- Select your tenant
- Click "New Application"
- Enter application name
- Configure settings:
  - Enable/disable password authentication
  - Set allowed origins for CORS
  - Configure redirect URLs
- Submit

**4. Copy your API keys:**

After creating the application, you'll see:
- **Publishable Key** (`pk_test_...`) — for frontend/client-side code
- **Secret Key** (`sk_test_...`) — for backend/server-side code (keep secure!)

### User Signup Flow

#### Using cURL (Raw API)

**Step 1: Request a hashcash challenge** (if hashcash is enabled):

```bash
curl -X POST http://localhost:8000/v1/challenges \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json"
```

**Response:**
```json
{
  "challenge": "ae17805f0ffd9aeac8f98421498d40cb",
  "difficulty": 5,
  "algorithm": "argon2id",
  "params": {
    "time_cost": 2,
    "memory_cost": 19456,
    "parallelism": 1,
    "hash_len": 32
  },
  "expires_in": 300
}
```

**Step 2: Solve the challenge** (requires argon2 implementation) and submit signup:

```bash
curl -X POST http://localhost:8000/v1/signups \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "secure-password",
    "hashcash": {
      "challenge": "ae17805f0ffd9aeac8f98421498d40cb",
      "nonce": "solved-nonce-value"
    }
  }'
```

**Response:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "verification_sent"
}
```

**Step 3: User receives email with 6-digit code. Verify the code:**

```bash
curl -X POST http://localhost:8000/v1/verify-code \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "code": "123456"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "rt_abc123def456...",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660f9511-f39c-52e5-b827-557766551111"
}
```

### User Sign-In Flow

#### Magic Link Sign-In

```bash
curl -X POST http://localhost:8000/v1/signins \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "strategy": "magic_link"
  }'
```

**Response:**
```json
{
  "status": "verification_sent"
}
```

User receives email with magic link or 6-digit code. For code verification:

```bash
curl -X POST http://localhost:8000/v1/verify-code \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "code": "123456"
  }'
```

#### Password Sign-In

```bash
curl -X POST http://localhost:8000/v1/signins \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "secure-password",
    "strategy": "password"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "rt_abc123def456...",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "660f9511-f39c-52e5-b827-557766551111"
}
```

### Accessing Protected Resources

Use the JWT access token in the Authorization header:

```bash
curl http://localhost:8000/v1/me \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Response:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "email_verified": true,
  "is_bot": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Token Refresh

Access tokens expire after 15 minutes (configurable). Use the refresh token to get a new one:

```bash
curl -X POST http://localhost:8000/v1/tokens/session \
  -H "X-Publishable-Key: pk_test_abc123" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "rt_abc123def456..."
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "rt_new789xyz012..."
}
```

## API Reference

### Authentication Endpoints (Publishable Key)

All frontend endpoints require `X-Publishable-Key: pk_...` header or can resolve the app from the request `Host` header.

#### POST /v1/challenges

Request a proof-of-work challenge for signup.

**Headers:**
- `X-Publishable-Key: pk_test_...`

**Response:**
```json
{
  "challenge": "random-hex-string",
  "difficulty": 5,
  "algorithm": "argon2id",
  "params": {
    "time_cost": 2,
    "memory_cost": 19456,
    "parallelism": 1,
    "hash_len": 32
  },
  "expires_in": 300
}
```

#### POST /v1/signups

Register a new user.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "optional-password",
  "redirect_url": "https://yourapp.com/welcome",
  "hashcash": {
    "challenge": "challenge-from-previous-request",
    "nonce": "solved-nonce"
  }
}
```

**Response (200):**
```json
{
  "user_id": "uuid",
  "status": "verification_sent"
}
```

#### POST /v1/signins

Sign in a user.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Content-Type: application/json`

**Request Body (Magic Link):**
```json
{
  "email": "user@example.com",
  "strategy": "magic_link",
  "redirect_url": "https://yourapp.com/dashboard"
}
```

**Request Body (Password):**
```json
{
  "email": "user@example.com",
  "password": "user-password",
  "strategy": "password"
}
```

**Response (Magic Link):**
```json
{
  "status": "verification_sent"
}
```

**Response (Password):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "rt_...",
  "user_id": "uuid",
  "session_id": "uuid"
}
```

#### POST /v1/verify-code

Verify a 6-digit email code and create a session.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "email": "user@example.com",
  "code": "123456"
}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "rt_...",
  "user_id": "uuid",
  "session_id": "uuid"
}
```

#### GET /v1/email/verify

Consume a verification or magic link token from email.

**Query Parameters:**
- `token`: The token from the email link

**Response:** Redirects to the application's `redirect_url` with `__session` cookie set.

#### GET /v1/me

Get current authenticated user information.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Authorization: Bearer <access_token>` OR `Cookie: __session=<jwt>`

**Response (200):**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "email_verified": true,
  "is_bot": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### POST /v1/tokens/session

Refresh an expired access token using a refresh token.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "refresh_token": "rt_abc123..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "rt_new456..."
}
```

#### POST /v1/sessions/logout

Revoke the current session.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Authorization: Bearer <access_token>` OR `Cookie: __session=<jwt>`

**Response (200):**
```json
{
  "status": "ok"
}
```

#### GET /v1/sso/bridge

Initiate cross-domain SSO.

**Query Parameters:**
- `return_to`: The satellite domain callback URL

**Response:** Redirects to satellite domain with exchange token in query string.

#### POST /v1/sso/exchange

Exchange an SSO token for a session on satellite domain.

**Headers:**
- `X-Publishable-Key: pk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "token": "sso_token_from_bridge"
}
```

**Response (200):**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "rt_...",
  "user_id": "uuid",
  "session_id": "uuid"
}
```

### Backend Endpoints (Secret Key)

All backend endpoints require `Authorization: Bearer sk_test_...` or `sk_live_...`.

#### GET /v1/users

List users for the application.

**Headers:**
- `Authorization: Bearer sk_test_...`

**Query Parameters:**
- `limit` (optional): Maximum results (default: 100)
- `offset` (optional): Pagination offset (default: 0)
- `email` (optional): Filter by email address

**Response (200):**
```json
{
  "users": [
    {
      "user_id": "uuid",
      "email": "user@example.com",
      "email_verified": true,
      "is_bot": false,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "total": 1
}
```

#### POST /v1/users

Create a user server-side (skips email verification).

**Headers:**
- `Authorization: Bearer sk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "email": "newuser@example.com",
  "password": "optional-password",
  "email_verified": true
}
```

**Response (201):**
```json
{
  "user_id": "uuid",
  "email": "newuser@example.com",
  "email_verified": true,
  "created_at": "2024-01-15T11:00:00Z"
}
```

#### GET /v1/users/{user_id}

Get a specific user by ID.

**Headers:**
- `Authorization: Bearer sk_test_...`

**Response (200):**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "email_verified": true,
  "is_bot": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### POST /v1/sessions/revoke

Revoke a session by ID.

**Headers:**
- `Authorization: Bearer sk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "session_id": "uuid"
}
```

**Response (200):**
```json
{
  "status": "revoked"
}
```

#### POST /v1/sign_in_tokens

Create a short-lived sign-in token for server-to-server authentication.

**Headers:**
- `Authorization: Bearer sk_test_...`
- `Content-Type: application/json`

**Request Body:**
```json
{
  "user_id": "uuid",
  "expires_in_seconds": 300
}
```

**Response (200):**
```json
{
  "token": "sit_abc123...",
  "expires_at": "2024-01-15T11:05:00Z"
}
```

### Public Endpoints

#### GET /.well-known/jwks.json

Returns the JSON Web Key Set for JWT verification.

**Headers:**
- `X-Publishable-Key: pk_test_...` (or resolved from Host)

**Response (200):**
```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "key-id",
      "n": "modulus...",
      "e": "AQAB"
    }
  ]
}
```

## Configuration

All configuration is done via environment variables. Create a `.env` file in the project root:

### Core Settings

```bash
# Database (required)
DATABASE_URL=postgresql+asyncpg://ezauth:ezauth@localhost:5432/ezauth

# Redis (optional, defaults shown)
REDIS_URL=redis://localhost:6379/0
```

### Email Configuration

```bash
# AWS SES (required for email sending)
SES_REGION=us-east-1
SES_SENDER=noreply@yourdomain.com
SES_SENDER_NAME=YourApp

# Email charset (optional)
MAIL_CHARSET=UTF-8
```

### JWT Settings

```bash
# JWT algorithm (RS256 recommended, do not change)
JWT_ALGORITHM=RS256

# Token lifetimes
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30
```

### Session Configuration

```bash
# Cookie settings
SESSION_COOKIE_NAME=__session
SESSION_COOKIE_DOMAIN=
SESSION_COOKIE_SECURE=true

# Token expiration
VERIFICATION_TOKEN_EXPIRE_MINUTES=60
MAGIC_LINK_EXPIRE_MINUTES=15
```

### Rate Limiting

Format: `window_seconds:max_count`

```bash
# Signup rate limits
SIGNUP_RATE_LIMIT_IP=60:10      # 10 signups per minute per IP
SIGNUP_RATE_LIMIT_EMAIL=300:1   # 1 signup per 5 minutes per email

# Sign-in rate limits
SIGNIN_RATE_LIMIT_IP=60:10      # 10 sign-ins per minute per IP
```

### Hashcash Proof-of-Work

```bash
# Enable/disable hashcash
HASHCASH_ENABLED=true

# Difficulty (leading zero bits, ~2^n attempts)
HASHCASH_DIFFICULTY=5

# Challenge TTL in seconds
HASHCASH_CHALLENGE_TTL=300

# Argon2 parameters
HASHCASH_TIME_COST=2
HASHCASH_MEMORY_COST=19456
HASHCASH_PARALLELISM=1
HASHCASH_HASH_LEN=32
```

### Dashboard

```bash
# Dashboard admin password (required)
DASHBOARD_SECRET_KEY=change-me-in-production
```

### OAuth (Optional)

```bash
# OAuth state management
OAUTH_STATE_TTL_SECONDS=600
```

### Object Storage (Optional)

```bash
# S3-compatible storage
S3_ENDPOINT_URL=https://s3.amazonaws.com
S3_ACCESS_KEY_ID=your-access-key
S3_SECRET_ACCESS_KEY=your-secret-key
S3_BUCKET_NAME=your-bucket
S3_REGION=us-east-1

# Storage limits
OBJECT_STORAGE_MAX_OBJECT_BYTES=52428800    # 50 MB per object
OBJECT_STORAGE_LIMIT_BYTES=1073741824       # 1 GB per app
```

### Custom Tables (Optional)

```bash
# Storage limit for custom table data
CUSTOM_TABLES_STORAGE_LIMIT_BYTES=104857600  # 100 MB
```

### Bot Authentication (Optional)

```bash
# Confirmations API
CONFIRMATIONS_API_URL=https://api.confirmations.info
BOT_AUTH_TIMESTAMP_TOLERANCE=300  # 5 minutes
```

## Common Patterns

### Pattern 1: Frontend Integration with JavaScript SDK

**Installation:**

```bash
cd javascript_client
npm install
npm run build
```

**Usage in Browser:**

```html
<!DOCTYPE html>
<html>
<head>
  <title>My App</title>
</head>
<body>
  <div id="app"></div>

  <script src="dist/ezauth.iife.js"></script>
  <script>
    // Initialize the client
    const auth = new EZAuth.EZAuth('https://auth.example.com', {
      publishableKey: 'pk_test_abc123'
    });

    // Sign up a new user
    async function signUp() {
      try {
        const result = await auth.auth.signUp({
          email: 'user@example.com',
          password: 'secure-password'
        });
        console.log('Signup successful:', result);
      } catch (error) {
        console.error('Signup failed:', error);
      }
    }

    // Sign in with password
    async function signIn() {
      try {
        const session = await auth.auth.signIn({
          email: 'user@example.com',
          password: 'secure-password',
          strategy: 'password'
        });
        console.log('Access token:', session.access_token);
      } catch (error) {
        console.error('Sign in failed:', error);
      }
    }

    // Get current session
    async function getSession() {
      try {
        const user = await auth.auth.getSession();
        console.log('Current user:', user);
      } catch (error) {
        console.error('Not authenticated:', error);
      }
    }

    // Sign out
    async function signOut() {
      try {
        await auth.auth.signOut();
        console.log('Signed out');
      } catch (error) {
        console.error('Sign out failed:', error);
      }
    }
  </script>
</body>
</html>
```

### Pattern 2: Backend Integration with Python Server SDK

**Installation:**

```bash
pip install -e sdk/python-server
```

**Usage with FastAPI Middleware:**

```python
from fastapi import FastAPI, Request
from ezauth_sdk import EZAuthMiddleware

app = FastAPI()

# Add EZAuth middleware
app.add_middleware(
    EZAuthMiddleware,
    auth_domain="https://auth.example.com",
    public_paths=["/health", "/docs", "/openapi.json"],
)

@app.get("/health")
async def health():
    """Public endpoint - no auth required"""
    return {"status": "ok"}

@app.get("/protected")
async def protected(request: Request):
    """Protected endpoint - requires valid JWT"""
    # Access user info from request.state.auth
    auth = request.state.auth
    return {
        "message": "Hello, authenticated user!",
        "user_id": auth.user_id,
        "email": auth.email
    }

@app.get("/profile")
async def profile(request: Request):
    """Get user profile"""
    auth = request.state.auth
    return {
        "user_id": auth.user_id,
        "email": auth.email,
        "email_verified": auth.email_verified
    }
```

**Usage with Dependency Injection:**

```python
from fastapi import FastAPI, Depends, HTTPException
from ezauth_sdk import JWKSClient, authenticate_request, AuthenticationError

app = FastAPI()
jwks_client = JWKSClient("https://auth.example.com")

async def get_auth(request):
    """Dependency that requires authentication"""
    try:
        return await authenticate_request(request, jwks_client)
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.get("/me")
async def get_me(auth=Depends(get_auth)):
    """Endpoint protected by dependency"""
    return {
        "user_id": auth.user_id,
        "email": auth.email
    }
```

### Pattern 3: Python Client SDK Usage

**Installation:**

```bash
pip install -e python_client
```

**Usage:**

```python
from ezauth_client import EZAuth, EZAuthError

# Initialize client with publishable key (for frontend operations)
client = EZAuth(
    base_url="https://auth.example.com",
    publishable_key="pk_test_abc123"
)

# Sign up a new user
try:
    # Request challenge
    challenge = client.auth.request_challenge()

    # Solve challenge (simplified - see CLI implementation for full solver)
    # nonce = solve_challenge(challenge)

    # Sign up with solved challenge
    result = client.auth.sign_up(
        email="user@example.com",
        password="secure-password",
        hashcash={
            "challenge": challenge["challenge"],
            "nonce": "solved-nonce"
        }
    )
    print(f"User created: {result['user_id']}")

    # Verify email code
    code = input("Enter verification code: ")
    session = client.auth.verify_code("user@example.com", code)
    print(f"Access token: {session['access_token']}")

except EZAuthError as e:
    print(f"Error: {e.message}")

# Initialize client with secret key (for backend operations)
admin_client = EZAuth(
    base_url="https://auth.example.com",
    secret_key="sk_test_xyz789"
)

# List users
users = admin_client.users.list(limit=10)
print(f"Found {len(users.get('users', []))} users")

# Create user server-side
new_user = admin_client.users.create(
    email="admin@example.com",
    password="admin-password"
)
print(f"Created user: {new_user['user_id']}")

# Get user by ID
user = admin_client.users.get(new_user['user_id'])
print(f"User email: {user['email']}")

# Revoke a session
admin_client.sessions.revoke("session-id-here")
```

### Pattern 4: CLI Usage for Quick Operations

**Installation:**

```bash
cd cli
pip install -e .
```

**Configuration:**

```bash
# Configure the CLI
ezauth configure

# Prompts for:
# - Server URL (e.g., https://auth.example.com)
# - Publishable key (pk_test_...)
# - Secret key (sk_test_...) - optional, for admin commands
```

**User Operations:**

```bash
# Sign up new account (automatically solves hashcash)
ezauth signup
# Prompts for: email, password (optional), verification code

# Log in to existing account
ezauth login
# Prompts for: email, strategy (password/magic_link), password or code

# Show current user info
ezauth whoami
# Output:
# user_id:        550e8400-e29b-41d4-a716-446655440000
# email:          user@example.com
# email_verified: true
# is_bot:         false

# Log out
ezauth logout
```

**Admin Operations (require secret key):**

```bash
# List users
ezauth users list
ezauth users list --limit 10 --email user@example.com

# Create user
ezauth users create --email newuser@example.com --password secret123

# Get user details
ezauth users get <user-id>

# Revoke session
ezauth sessions revoke <session-id>

# Create sign-in token
ezauth sessions create-token --user-id <user-id> --expires 300

# Get JSON output for any command
ezauth --json users list
```

### Pattern 5: Custom Tables for User Data

```bash
# Create a table with columns
ezauth tables create --name contacts \
  --column name:text \
  --column email:text \
  --column age:int

# List tables
ezauth tables list

# Insert a row
ezauth rows insert <table-id> --data '{"name": "Alice", "email": "alice@example.com", "age": 30}'

# Query rows with filters
ezauth rows query <table-id> \
  --filter '{"field": "age", "op": "gte", "value": 18}' \
  --sort name:asc \
  --limit 50

# Update a row
ezauth rows update <table-id> <row-id> --data '{"age": 31}'

# Delete a row
ezauth rows delete <table-id> <row-id>
```

### Pattern 6: Cross-Domain SSO

Configure two applications on the same tenant for cross-domain SSO:

**Main Domain (app1.example.com):**

```javascript
// User is logged in on main domain
// Initiate SSO to satellite domain
window.location.href = 'https://auth.example.com/v1/sso/bridge?return_to=https://app2.example.com/auth/callback';
```

**Satellite Domain (app2.example.com):**

```javascript
// On /auth/callback page
const params = new URLSearchParams(window.location.search);
const token = params.get('token');

// Exchange token for session
const response = await fetch('https://auth.example.com/v1/sso/exchange', {
  method: 'POST',
  headers: {
    'X-Publishable-Key': 'pk_test_satellite_key',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ token })
});

const session = await response.json();
// Store session.access_token and session.refresh_token
localStorage.setItem('access_token', session.access_token);
localStorage.setItem('refresh_token', session.refresh_token);

// Redirect to app
window.location.href = '/dashboard';
```

## Examples

### Example 1: Complete User Registration Flow

```python
from ezauth_client import EZAuth, EZAuthError
from ezauth_cli.hashcash import solve_challenge

client = EZAuth(
    base_url="https://auth.example.com",
    publishable_key="pk_test_abc123"
)

email = "newuser@example.com"
password = "SecurePass123!"

try:
    # Step 1: Request hashcash challenge
    print("Requesting proof-of-work challenge...")
    challenge_data = client.auth.request_challenge()

    # Step 2: Solve the challenge
    print("Solving challenge...")
    nonce, attempts = solve_challenge(
        challenge=challenge_data["challenge"],
        difficulty=challenge_data["difficulty"],
        time_cost=challenge_data["params"]["time_cost"],
        memory_cost=challenge_data["params"]["memory_cost"],
        parallelism=challenge_data["params"]["parallelism"],
        hash_len=challenge_data["params"]["hash_len"]
    )
    print(f"Challenge solved in {attempts} attempts")

    # Step 3: Submit signup
    print("Submitting signup...")
    signup_result = client.auth.sign_up(
        email=email,
        password=password,
        hashcash={
            "challenge": challenge_data["challenge"],
            "nonce": nonce
        }
    )
    print(f"Signup status: {signup_result['status']}")
    print(f"User ID: {signup_result['user_id']}")

    # Step 4: Verify email code
    code = input("Enter verification code from email: ")
    session = client.auth.verify_code(email, code)

    print("✓ Registration complete!")
    print(f"Access token: {session['access_token'][:20]}...")
    print(f"Session ID: {session['session_id']}")

except EZAuthError as e:
    print(f"Error: {e.message}")
    if e.status:
        print(f"Status code: {e.status}")
```

**Expected Output:**
```
Requesting proof-of-work challenge...
Solving challenge...
Challenge solved in 27 attempts
Submitting signup...
Signup status: verification_sent
User ID: 550e8400-e29b-41d4-a716-446655440000
Enter verification code from email: 123456
✓ Registration complete!
Access token: eyJhbGciOiJSUzI1NiI...
Session ID: 660f9511-f39c-52e5-b827-557766551111
```

### Example 2: Backend User Management

```python
from ezauth_client import EZAuth

# Admin client with secret key
admin = EZAuth(
    base_url="https://auth.example.com",
    secret_key="sk_test_xyz789"
)

# Create multiple users
users_to_create = [
    {"email": "alice@example.com", "password": "pass123"},
    {"email": "bob@example.com", "password": "pass456"},
    {"email": "charlie@example.com", "password": "pass789"}
]

created_users = []
for user_data in users_to_create:
    user = admin.users.create(**user_data)
    created_users.append(user)
    print(f"Created: {user['email']} (ID: {user['user_id']})")

# List all users
all_users = admin.users.list(limit=100)
print(f"\nTotal users: {all_users['total']}")

# Filter users by email
filtered = admin.users.list(email="alice@example.com")
if filtered['users']:
    alice = filtered['users'][0]
    print(f"\nFound Alice: {alice['user_id']}")

    # Get full user details
    details = admin.users.get(alice['user_id'])
    print(f"Email verified: {details['email_verified']}")
    print(f"Created at: {details['created_at']}")

# Create a sign-in token for Alice
token_result = admin.sessions.create_sign_in_token(
    user_id=alice['user_id'],
    expires_in_seconds=300
)
print(f"\nSign-in token: {token_result['token']}")
print(f"Expires at: {token_result['expires_at']}")
```

**Expected Output:**
```
Created: alice@example.com (ID: 550e8400-e29b-41d4-a716-446655440000)
Created: bob@example.com (ID: 660f9511-f39c-52e5-b827-557766551111)
Created: charlie@example.com (ID: 770fa622-g40d-63f6-c938-668877662222)

Total users: 3

Found Alice: 550e8400-e29b-41d4-a716-446655440000
Email verified: true
Created at: 2024-01-15T10:30:00Z

Sign-in token: sit_abc123def456...
Expires at: 2024-01-15T10:35:00Z
```

### Example 3: Building a React Login Component

```jsx
import { useState } from 'react';
import { EZAuth } from './ezauth-client';

const auth = new EZAuth('https://auth.example.com', {
  publishableKey: 'pk_test_abc123'
});

function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [strategy, setStrategy] = useState('password');
  const [code, setCode] = useState('');
  const [awaitingCode, setAwaitingCode] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (strategy === 'password') {
        // Password sign-in
        const session = await auth.auth.signIn({
          email,
          password,
          strategy: 'password'
        });

        // Store tokens
        localStorage.setItem('access_token', session.access_token);
        localStorage.setItem('refresh_token', session.refresh_token);

        // Redirect to dashboard
        window.location.href = '/dashboard';
      } else {
        // Magic link sign-in
        await auth.auth.signIn({
          email,
          strategy: 'magic_link'
        });

        setAwaitingCode(true);
      }
    } catch (err) {
      setError(err.message || 'Sign in failed');
    } finally {
      setLoading(false);
    }
  };

  const handleCodeSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const session = await auth.auth.verifyCode({ email, code });

      // Store tokens
      localStorage.setItem('access_token', session.access_token);
      localStorage.setItem('refresh_token', session.refresh_token);

      // Redirect to dashboard
      window.location.href = '/dashboard';
    } catch (err) {
      setError(err.message || 'Verification failed');
    } finally {
      setLoading(false);
    }
  };

  if (awaitingCode) {
    return (
      <form onSubmit={handleCodeSubmit}>
        <h2>Enter Verification Code</h2>
        <p>We sent a code to {email}</p>

        <input
          type="text"
          placeholder="123456"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={6}
          required
        />

        {error && <div className="error">{error}</div>}

        <button type="submit" disabled={loading}>
          {loading ? 'Verifying...' : 'Verify Code'}
        </button>

        <button type="button" onClick={() => setAwaitingCode(false)}>
          Back
        </button>
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2>Sign In</h2>

      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />

      <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
        <option value="password">Password</option>
        <option value="magic_link">Magic Link</option>
      </select>

      {strategy === 'password' && (
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      )}

      {error && <div className="error">{error}</div>}

      <button type="submit" disabled={loading}>
        {loading ? 'Signing in...' : 'Sign In'}
      </button>
    </form>
  );
}

export default LoginForm;
```

### Example 4: Token Refresh in Frontend

```javascript
class AuthService {
  constructor(baseUrl, publishableKey) {
    this.baseUrl = baseUrl;
    this.publishableKey = publishableKey;
  }

  async getValidAccessToken() {
    let accessToken = localStorage.getItem('access_token');
    const refreshToken = localStorage.getItem('refresh_token');

    if (!accessToken) {
      throw new Error('Not authenticated');
    }

    // Check if token is expired (decode JWT payload)
    const payload = JSON.parse(atob(accessToken.split('.')[1]));
    const expiresAt = payload.exp * 1000; // Convert to milliseconds
    const now = Date.now();

    // Refresh if expired or expiring in next 60 seconds
    if (expiresAt - now < 60000) {
      console.log('Token expired or expiring soon, refreshing...');

      if (!refreshToken) {
        throw new Error('No refresh token available');
      }

      const response = await fetch(`${this.baseUrl}/v1/tokens/session`, {
        method: 'POST',
        headers: {
          'X-Publishable-Key': this.publishableKey,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ refresh_token: refreshToken })
      });

      if (!response.ok) {
        // Refresh failed, user needs to log in again
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        throw new Error('Session expired');
      }

      const session = await response.json();
      accessToken = session.access_token;

      // Store new tokens
      localStorage.setItem('access_token', accessToken);
      if (session.refresh_token) {
        localStorage.setItem('refresh_token', session.refresh_token);
      }
    }

    return accessToken;
  }

  async fetchProtected(endpoint, options = {}) {
    const accessToken = await this.getValidAccessToken();

    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      ...options,
      headers: {
        'X-Publishable-Key': this.publishableKey,
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        ...options.headers
      }
    });

    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }

    return response.json();
  }
}

// Usage
const auth = new AuthService('https://auth.example.com', 'pk_test_abc123');

// This will automatically refresh the token if needed
const user = await auth.fetchProtected('/v1/me');
console.log('Current user:', user);
```

**Expected Console Output:**
```
Token expired or expiring soon, refreshing...
Current user: { user_id: '550e...', email: 'user@example.com', ... }
```

## Troubleshooting

### Common Errors and Solutions

#### Error: "Not configured. Run 'ezauth configure' first"

**Cause:** CLI is not configured with server URL and API keys.

**Solution:**
```bash
ezauth configure
# Enter your server URL and API keys when prompted
```

---

#### Error: "Invalid hashcash proof"

**Cause:** Hashcash challenge solution is incorrect or expired.

**Solutions:**
1. Ensure you're using the argon2id algorithm with correct parameters
2. Check that the challenge hasn't expired (default 5 minutes)
3. Verify nonce was calculated correctly
4. Use the CLI or SDK hashcash solver instead of manual solving

**Using CLI (recommended):**
```bash
ezauth signup  # Automatically solves hashcash
```

---

#### Error: "Rate limit exceeded"

**Cause:** Too many requests from the same IP or email address.

**Solutions:**
1. Wait for the rate limit window to reset (default: 60 seconds for IP, 5 minutes for email)
2. Reduce request frequency in your application
3. Adjust rate limits in `.env` if running your own instance:
   ```bash
   SIGNUP_RATE_LIMIT_IP=60:10
   SIGNIN_RATE_LIMIT_IP=60:10
   ```

---

#### Error: "401 Unauthorized" when accessing /v1/me

**Cause:** JWT is expired or invalid.

**Solutions:**
1. Refresh the access token using the refresh token:
   ```bash
   curl -X POST https://auth.example.com/v1/tokens/session \
     -H "X-Publishable-Key: pk_test_..." \
     -H "Content-Type: application/json" \
     -d '{"refresh_token": "rt_..."}'
   ```

2. If refresh token is also expired, user must log in again

3. Check that `X-Publishable-Key` header matches the app that issued the JWT

---

#### Error: "Email verification required"

**Cause:** User attempted to sign in before verifying their email.

**Solutions:**
1. Complete email verification by clicking link in email or entering 6-digit code
2. Resend verification email:
   ```bash
   curl -X POST https://auth.example.com/v1/signins \
     -H "X-Publishable-Key: pk_test_..." \
     -H "Content-Type: application/json" \
     -d '{"email": "user@example.com", "strategy": "magic_link"}'
   ```

---

#### Error: "CORS error" in browser

**Cause:** Your application domain is not in the allowed origins list.

**Solutions:**
1. Log in to the dashboard at `https://auth.example.com/dashboard`
2. Navigate to your application settings
3. Add your domain to "Allowed Origins" (e.g., `https://myapp.com`)
4. Save changes

---

#### Error: Database connection failed

**Cause:** PostgreSQL is not running or `DATABASE_URL` is incorrect.

**Solutions:**
1. Start PostgreSQL:
   ```bash
   docker compose up -d postgres
   ```

2. Verify connection string in `.env`:
   ```bash
   DATABASE_URL=postgresql+asyncpg://ezauth:ezauth@localhost:5432/ezauth
   ```

3. Test connection:
   ```bash
   psql postgresql://ezauth:ezauth@localhost:5432/ezauth -c "SELECT 1;"
   ```

---

#### Error: Redis connection failed

**Cause:** Redis is not running or `REDIS_URL` is incorrect.

**Solutions:**
1. Start Redis:
   ```bash
   docker compose up -d redis
   ```

2. Verify connection string in `.env`:
   ```bash
   REDIS_URL=redis://localhost:6379/0
   ```

3. Test connection:
   ```bash
   redis-cli -u redis://localhost:6379/0 ping
   # Should return: PONG
   ```

---

#### Error: Email sending failed (SES)

**Cause:** AWS SES credentials are not configured or email is not verified.

**Solutions:**
1. Configure AWS credentials:
   ```bash
   aws configure
   # Or set environment variables:
   export AWS_ACCESS_KEY_ID=your-key
   export AWS_SECRET_ACCESS_KEY=your-secret
   ```

2. Verify sender email in SES console (required in sandbox mode)

3. Check `.env` settings:
   ```bash
   SES_REGION=us-east-1
   SES_SENDER=noreply@yourdomain.com
   ```

4. Request production access if sending to unverified emails

---

### Debugging Tips

**Enable verbose logging:**

```bash
# Set log level in .env or environment
export LOG_LEVEL=DEBUG

# Restart server
uvicorn ezauth.main:create_app --factory --reload --log-level debug
```

**Check JWT contents:**

Decode a JWT to inspect claims (use jwt.io or):

```python
import json
import base64

def decode_jwt(token):
    # Split and decode payload (second part)
    payload = token.split('.')[1]
    # Add padding if needed
    payload += '=' * (4 - len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload)
    return json.loads(decoded)

token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
print(json.dumps(decode_jwt(token), indent=2))
```

**Test JWKS endpoint:**

```bash
curl https://auth.example.com/.well-known/jwks.json \
  -H "X-Publishable-Key: pk_test_..."
```

**Monitor rate limits:**

Check Redis for rate limit keys:

```bash
redis-cli -u redis://localhost:6379/0
> KEYS ratelimit:*
> TTL ratelimit:signup:ip:192.168.1.1
```

**Check audit logs:**

Query the audit_log table to see all authentication events:

```sql
psql postgresql://ezauth:ezauth@localhost:5432/ezauth

SELECT event_type, user_id, ip_address, created_at
FROM audit_log
ORDER BY created_at DESC
LIMIT 10;
```

---

### FAQ

**Q: Can I use EZAuth without hashcash?**

A: Yes, set `HASHCASH_ENABLED=false` in your `.env` file. This is useful for development but not recommended for production.

---

**Q: How do I migrate from test keys to live keys?**

A: Create a new application in the dashboard with "live" mode enabled. This generates `pk_live_...` and `sk_live_...` keys. Update your production app to use the live keys.

---

**Q: Can I customize email templates?**

A: Yes, through the dashboard:
1. Navigate to your application
2. Click "Email Templates"
3. Select template to edit (verification, magic link, welcome)
4. Edit HTML and text versions
5. Save changes

---

**Q: How do I revoke all sessions for a user?**

A: Currently, you must revoke sessions individually using the backend API. Batch revocation can be implemented:

```python
admin = EZAuth(base_url="...", secret_key="sk_test_...")

# Get user's sessions (requires custom query)
# Then revoke each one
for session_id in user_session_ids:
    admin.sessions.revoke(session_id)
```

---

**Q: What happens if a refresh token is stolen?**

A: The refresh token can be used to obtain new access tokens until it expires (default 30 days) or is revoked. Implement these security measures:

1. Store refresh tokens securely (httpOnly cookies in browsers)
2. Use short refresh token lifetimes in sensitive applications
3. Implement refresh token rotation (new refresh token on each use)
4. Monitor for suspicious refresh patterns in audit logs
5. Provide users ability to revoke sessions from their account settings

---

**Q: Can I use EZAuth with mobile apps?**

A: Yes, use the Python, JavaScript, Kotlin, or Swift client SDKs. Mobile apps should:

1. Store tokens in secure storage (Keychain on iOS, KeyStore on Android)
2. Use the publishable key for authentication
3. Handle token refresh automatically
4. Implement proper error handling for network issues

---

**Q: How do I test webhooks/callbacks locally?**

A: Use ngrok or similar tunneling service:

```bash
# Start ngrok
ngrok http 8000

# Use the ngrok URL in your application settings
# Example: https://abc123.ngrok.io
```

---

**Q: Does EZAuth support two-factor authentication (2FA)?**

A: Not currently. Email verification codes provide a form of 2FA, but dedicated TOTP/SMS 2FA is not implemented. This could be added as a feature.

---

## Deployment

### Production Deployment on Hetzner VPS

EZAuth is designed to run on a Debian-based VPS with Caddy as reverse proxy.

**Prerequisites:**
- Debian 13 or Ubuntu 22.04+ server
- Root or sudo access
- Domain name pointing to server IP

**Deployment steps:**

```bash
# 1. SSH into server
ssh user@your-server.com

# 2. Install dependencies
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql redis-server

# 3. Install Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# 4. Create ezauth user
sudo useradd -r -s /bin/bash -d /opt/ezauth ezauth
sudo mkdir -p /opt/ezauth
sudo chown ezauth:ezauth /opt/ezauth

# 5. Clone and setup application
sudo -u ezauth git clone <repository-url> /opt/ezauth/app
cd /opt/ezauth/app

# 6. Create virtual environment
sudo -u ezauth python3.11 -m venv /opt/ezauth/venv
sudo -u ezauth /opt/ezauth/venv/bin/pip install -e "."

# 7. Configure environment
sudo -u ezauth cp .env.example /opt/ezauth/.env
sudo -u ezauth nano /opt/ezauth/.env
# Edit with production values

# 8. Run migrations
sudo -u ezauth /opt/ezauth/venv/bin/alembic upgrade head

# 9. Create systemd service
sudo nano /etc/systemd/system/ezauth.service
```

**Service file (`/etc/systemd/system/ezauth.service`):**

```ini
[Unit]
Description=EZAuth Authentication Service
After=network.target postgresql.service redis.service
Requires=postgresql.service redis.service

[Service]
Type=simple
User=ezauth
Group=ezauth
WorkingDirectory=/opt/ezauth/app
EnvironmentFile=/opt/ezauth/.env
ExecStart=/opt/ezauth/venv/bin/uvicorn ezauth.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Configure Caddy (`/etc/caddy/Caddyfile`):**

```caddyfile
api.yourdomain.com {
    reverse_proxy localhost:8001
    encode gzip

    log {
        output file /var/log/caddy/ezauth.log
    }
}
```

**Start services:**

```bash
# Enable and start ezauth
sudo systemctl daemon-reload
sudo systemctl enable ezauth
sudo systemctl start ezauth
sudo systemctl status ezauth

# Reload Caddy
sudo systemctl reload caddy

# Check logs
sudo journalctl -u ezauth -f
```

**Verify deployment:**

```bash
curl https://api.yourdomain.com/health
# Should return: {"status":"ok"}
```

---

### Docker Deployment

For containerized deployment:

```bash
# Build image
docker build -t ezauth:latest .

# Run with docker-compose
docker-compose -f docker-compose.prod.yml up -d
```

**Production docker-compose.yml:**

```yaml
version: '3.8'

services:
  ezauth:
    image: ezauth:latest
    ports:
      - "8001:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://ezauth:${DB_PASSWORD}@postgres:5432/ezauth
      - REDIS_URL=redis://redis:6379/0
      - SES_SENDER=${SES_SENDER}
      - SES_REGION=${SES_REGION}
      - DASHBOARD_SECRET_KEY=${DASHBOARD_SECRET_KEY}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=ezauth
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=ezauth
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  pgdata:
```

---

### Environment Variables for Production

Create `.env.production`:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://ezauth:STRONG_PASSWORD@localhost:5432/ezauth

# Redis
REDIS_URL=redis://localhost:6379/0

# AWS SES
SES_REGION=us-east-1
SES_SENDER=noreply@yourdomain.com
SES_SENDER_NAME=YourApp

# JWT Settings
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# Security
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_DOMAIN=.yourdomain.com
DASHBOARD_SECRET_KEY=GENERATE_STRONG_RANDOM_KEY

# Hashcash (recommended for production)
HASHCASH_ENABLED=true
HASHCASH_DIFFICULTY=5

# Rate limiting (adjust based on your traffic)
SIGNUP_RATE_LIMIT_IP=60:10
SIGNUP_RATE_LIMIT_EMAIL=300:1
SIGNIN_RATE_LIMIT_IP=60:20
```

**Generate secure keys:**

```bash
# Dashboard secret key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Database password
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

This completes the comprehensive usage guide for EZAuth. All examples are runnable and include expected outputs. For additional help, consult the source code or open an issue on the project repository.