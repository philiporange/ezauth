# EZAuth Swift Client

Universal Swift client for EZAuth — covers both frontend (publishable key) auth flows and backend (secret key) admin operations.

Zero dependencies. Uses Foundation `URLSession`. Requires Swift 5.9+, iOS 15+, macOS 12+.

## Install

### Swift Package Manager

```swift
// Package.swift
dependencies: [
    .package(url: "https://github.com/your-org/ezauth-swift.git", from: "0.1.0"),
],
targets: [
    .target(name: "YourApp", dependencies: ["EZAuth"]),
]
```

Or in Xcode: File > Add Package Dependencies, paste the repository URL.

## Quick start

### Backend (secret key)

```swift
import EZAuth

let ez = EZAuth(
    baseURL: "https://your-ezauth-instance.com",
    secretKey: "sk_live_..."
)

// Users
let list = try await ez.users.list(limit: 10)
let user = try await ez.users.create(email: "alice@example.com")
let found = try await ez.users.get(user.id)

// Sessions
try await ez.sessions.revoke(sessionId)
let token = try await ez.sessions.createSignInToken(userId: user.id)

// Custom tables
let table = try await ez.tables.create(
    name: "contacts",
    columns: [
        ColumnDefinition(name: "name", type: "text", required: true),
        ColumnDefinition(name: "age", type: "int"),
    ]
)

let row = try await ez.tables.rows.insert(
    tableId: table.id,
    data: ["name": "Alice", "age": 30]
)

let results = try await ez.tables.rows.query(
    tableId: table.id,
    filter: [
        "field": "age",
        "op": "gte",
        "value": 18,
    ],
    sort: SortSpec(field: "name", dir: "asc"),
    limit: 50
)

// Storage usage
let usage = try await ez.storage.get()
print("\(usage.used_percent)% used")
```

### Frontend (publishable key)

```swift
import EZAuth

let ez = EZAuth(
    baseURL: "https://your-ezauth-instance.com",
    publishableKey: "pk_live_..."
)

let signup = try await ez.auth.signUp(email: "alice@example.com", password: "s3cret")
let signin = try await ez.auth.signIn(email: "alice@example.com", password: "s3cret")
let me = try await ez.auth.getSession()
try await ez.auth.signOut()
```

## Error handling

All methods throw `EZAuthError`:

```swift
do {
    let user = try await ez.users.get("nonexistent")
} catch let error as EZAuthError {
    print(error.message) // "User not found"
    print(error.status)  // 404
}
```

## API reference

### `EZAuth(baseURL:secretKey:publishableKey:session:)`

### `ez.auth` (publishable key)

| Method | Description |
|--------|-------------|
| `signUp(email:password:redirectUrl:)` | Create a new user |
| `signIn(email:password:strategy:redirectUrl:)` | Sign in |
| `signOut()` | Sign out current session |
| `verifyCode(email:code:)` | Verify a 6-digit code |
| `getSession()` | Get current session/user |
| `refreshToken(_:)` | Refresh an access token |
| `ssoExchange(token:)` | Exchange an SSO token for a session |

### `ez.users` (secret key)

| Method | Description |
|--------|-------------|
| `list(limit:offset:email:)` | List users |
| `create(email:password:)` | Create a user |
| `get(_:)` | Get a user by ID |

### `ez.sessions` (secret key)

| Method | Description |
|--------|-------------|
| `revoke(_:)` | Revoke a session |
| `createSignInToken(userId:expiresInSeconds:)` | Create a sign-in token |

### `ez.tables` (secret key)

| Method | Description |
|--------|-------------|
| `create(name:columns:)` | Create a table |
| `list()` | List all tables |
| `get(_:)` | Get a table with columns |
| `delete(_:)` | Delete a table |

### `ez.tables.columns` (secret key)

| Method | Description |
|--------|-------------|
| `add(tableId:name:type:required:defaultValue:position:)` | Add a column |
| `update(tableId:columnId:name:required:defaultValue:position:)` | Update a column |
| `delete(tableId:columnId:)` | Delete a column |

### `ez.tables.rows` (secret key)

| Method | Description |
|--------|-------------|
| `insert(tableId:data:)` | Insert a row |
| `get(tableId:rowId:)` | Get a row |
| `update(tableId:rowId:data:)` | Update a row (partial) |
| `delete(tableId:rowId:)` | Delete a row |
| `query(tableId:filter:sort:limit:cursor:)` | Query rows |

### `ez.storage` (secret key)

| Method | Description |
|--------|-------------|
| `get()` | Get storage usage |

## JSON values

Dynamic data (row values, filter specs) uses the `JSONValue` enum:

```swift
// Literal syntax works naturally
let data: [String: JSONValue] = [
    "name": "Alice",
    "age": 30,
    "active": true,
    "score": 9.5,
    "tags": ["swift", "ios"],
    "meta": nil,
]

let filter: JSONValue = [
    "field": "age",
    "op": "gte",
    "value": 18,
]
```

## Build

```bash
swift build
```
