# @ezauth/client

Universal JavaScript client for EZAuth — covers both frontend (publishable key) auth flows and backend (secret key) admin operations.

Zero dependencies. Works in Node.js 18+ and all modern browsers.

## Install

```bash
npm install @ezauth/client
```

## Quick start

### Backend (secret key)

```js
import { EZAuth } from '@ezauth/client'

const ez = new EZAuth({
  baseUrl: 'https://your-ezauth-instance.com',
  secretKey: 'sk_live_...',
})

// Users
const { users, total } = await ez.users.list({ limit: 10 })
const user = await ez.users.create({ email: 'alice@example.com' })
const found = await ez.users.get(user.id)

// Sessions
await ez.sessions.revoke(sessionId)
const token = await ez.sessions.createSignInToken({ userId: user.id })

// Custom tables
const table = await ez.tables.create({
  name: 'contacts',
  columns: [
    { name: 'name', type: 'text', required: true },
    { name: 'age', type: 'int' },
  ],
})

await ez.tables.rows.insert(table.id, {
  data: { name: 'Alice', age: 30 },
})

const { rows } = await ez.tables.rows.query(table.id, {
  filter: { field: 'age', op: 'gte', value: 18 },
  sort: { field: 'name', dir: 'asc' },
  limit: 50,
})

// Storage usage
const usage = await ez.storage.get()
console.log(`${usage.used_percent}% used`)
```

### Frontend (publishable key)

```js
import { EZAuth } from '@ezauth/client'

const ez = new EZAuth({
  baseUrl: 'https://your-ezauth-instance.com',
  publishableKey: 'pk_live_...',
})

await ez.auth.signUp({ email: 'alice@example.com', password: 's3cret' })
const session = await ez.auth.signIn({ email: 'alice@example.com', password: 's3cret' })
const me = await ez.auth.getSession()
await ez.auth.signOut()
```

## Error handling

All methods throw `EZAuthError` on failure:

```js
import { EZAuth, EZAuthError } from '@ezauth/client'

try {
  await ez.users.get('nonexistent')
} catch (err) {
  if (err instanceof EZAuthError) {
    console.error(err.message) // "User not found"
    console.error(err.status)  // 404
  }
}
```

## API reference

### `new EZAuth({ baseUrl, secretKey?, publishableKey? })`

### `ez.auth` (publishable key)

| Method | Description |
|--------|-------------|
| `signUp({ email, password?, redirectUrl? })` | Create a new user |
| `signIn({ email, password?, strategy?, redirectUrl? })` | Sign in |
| `signOut()` | Sign out current session |
| `verifyCode({ email, code })` | Verify a 6-digit code |
| `getSession()` | Get current session/user |
| `refreshToken(refreshToken)` | Refresh an access token |
| `ssoExchange(token)` | Exchange an SSO token for a session |
| `signInWithOAuth({ provider, redirectUrl })` | Get OAuth authorization URL |

### `ez.users` (secret key)

| Method | Description |
|--------|-------------|
| `list({ limit?, offset?, email? })` | List users |
| `create({ email, password? })` | Create a user |
| `get(userId)` | Get a user by ID |

### `ez.sessions` (secret key)

| Method | Description |
|--------|-------------|
| `revoke(sessionId)` | Revoke a session |
| `createSignInToken({ userId, expiresInSeconds? })` | Create a sign-in token |

### `ez.tables` (secret key)

| Method | Description |
|--------|-------------|
| `create({ name, columns? })` | Create a table |
| `list()` | List all tables |
| `get(tableId)` | Get a table with columns |
| `delete(tableId)` | Delete a table |

### `ez.tables.columns` (secret key)

| Method | Description |
|--------|-------------|
| `add(tableId, { name, type, required?, defaultValue?, position? })` | Add a column |
| `update(tableId, columnId, { name?, required?, defaultValue?, position? })` | Update a column |
| `delete(tableId, columnId)` | Delete a column |

### `ez.tables.rows` (secret key)

| Method | Description |
|--------|-------------|
| `insert(tableId, { data })` | Insert a row |
| `get(tableId, rowId)` | Get a row |
| `update(tableId, rowId, { data })` | Update a row (partial) |
| `delete(tableId, rowId)` | Delete a row |
| `query(tableId, { filter?, sort?, limit?, cursor? })` | Query rows |

### `ez.storage` (secret key)

| Method | Description |
|--------|-------------|
| `get()` | Get storage usage |

## Build

```bash
npm install
npm run build
```

Outputs `dist/ezauth.esm.js`, `dist/ezauth.cjs.js`, and `dist/ezauth.iife.js`.
