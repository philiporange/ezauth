# EZAuth Kotlin Client

Universal Kotlin client for EZAuth — covers both frontend (publishable key) auth flows and backend (secret key) admin operations.

Uses OkHttp for HTTP, kotlinx.serialization for JSON, and Kotlin coroutines for async. Targets JVM 17+ and Android.

## Install

### Gradle (Kotlin DSL)

```kotlin
dependencies {
    implementation("org.ezauth:ezauth-client:0.1.0")
}
```

### Gradle (Groovy)

```groovy
dependencies {
    implementation 'org.ezauth:ezauth-client:0.1.0'
}
```

## Quick start

### Backend (secret key)

```kotlin
import org.ezauth.client.*
import kotlinx.serialization.json.JsonPrimitive

val ez = EZAuth(
    baseUrl = "https://your-ezauth-instance.com",
    secretKey = "sk_live_...",
)

// Users
val list = ez.users.list(limit = 10)
val user = ez.users.create(email = "alice@example.com")
val found = ez.users.get(user.id)

// Sessions
ez.sessions.revoke(sessionId)
val token = ez.sessions.createSignInToken(userId = user.id)

// Custom tables
val table = ez.tables.create(
    name = "contacts",
    columns = listOf(
        ColumnDefinition(name = "name", type = "text", required = true),
        ColumnDefinition(name = "age", type = "int"),
    ),
)

val row = ez.tables.rows.insert(
    tableId = table.id,
    data = buildJsonObject {
        put("name", JsonPrimitive("Alice"))
        put("age", JsonPrimitive(30))
    },
)

val results = ez.tables.rows.query(
    tableId = table.id,
    filter = buildJsonObject {
        put("field", JsonPrimitive("age"))
        put("op", JsonPrimitive("gte"))
        put("value", JsonPrimitive(18))
    },
    sort = SortSpec(field = "name", dir = "asc"),
    limit = 50,
)

// Storage usage
val usage = ez.storage.get()
println("${usage.used_percent}% used")
```

### Frontend (publishable key)

```kotlin
import org.ezauth.client.*

val ez = EZAuth(
    baseUrl = "https://your-ezauth-instance.com",
    publishableKey = "pk_live_...",
)

val signup = ez.auth.signUp(email = "alice@example.com", password = "s3cret")
val signin = ez.auth.signIn(email = "alice@example.com", password = "s3cret")
val me = ez.auth.getSession()
ez.auth.signOut()
```

## Error handling

All methods throw `EZAuthError`:

```kotlin
try {
    ez.users.get("nonexistent")
} catch (e: EZAuthError) {
    println(e.message) // "User not found"
    println(e.status)  // 404
}
```

## Custom OkHttpClient

Pass your own `OkHttpClient` for timeouts, interceptors, etc.:

```kotlin
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

val ez = EZAuth(
    baseUrl = "https://your-ezauth-instance.com",
    secretKey = "sk_live_...",
    httpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build(),
)
```

## API reference

### `EZAuth(baseUrl, secretKey?, publishableKey?, httpClient?)`

### `ez.auth` (publishable key)

| Method | Description |
|--------|-------------|
| `signUp(email, password?, redirectUrl?)` | Create a new user |
| `signIn(email, password?, strategy?, redirectUrl?)` | Sign in |
| `signOut()` | Sign out current session |
| `verifyCode(email, code)` | Verify a 6-digit code |
| `getSession()` | Get current session/user |
| `refreshToken(refreshToken)` | Refresh an access token |
| `ssoExchange(token)` | Exchange an SSO token for a session |
| `signInWithOAuth(provider, redirectUrl)` | Get OAuth authorization URL |

### `ez.users` (secret key)

| Method | Description |
|--------|-------------|
| `list(limit?, offset?, email?)` | List users |
| `create(email, password?)` | Create a user |
| `get(userId)` | Get a user by ID |

### `ez.sessions` (secret key)

| Method | Description |
|--------|-------------|
| `revoke(sessionId)` | Revoke a session |
| `createSignInToken(userId, expiresInSeconds?)` | Create a sign-in token |

### `ez.tables` (secret key)

| Method | Description |
|--------|-------------|
| `create(name, columns?)` | Create a table |
| `list()` | List all tables |
| `get(tableId)` | Get a table with columns |
| `delete(tableId)` | Delete a table |

### `ez.tables.columns` (secret key)

| Method | Description |
|--------|-------------|
| `add(tableId, name, type, required?, defaultValue?, position?)` | Add a column |
| `update(tableId, columnId, name?, required?, defaultValue?, position?)` | Update a column |
| `delete(tableId, columnId)` | Delete a column |

### `ez.tables.rows` (secret key)

| Method | Description |
|--------|-------------|
| `insert(tableId, data)` | Insert a row |
| `get(tableId, rowId)` | Get a row |
| `update(tableId, rowId, data)` | Update a row (partial) |
| `delete(tableId, rowId)` | Delete a row |
| `query(tableId, filter?, sort?, limit?, cursor?)` | Query rows |

### `ez.storage` (secret key)

| Method | Description |
|--------|-------------|
| `get()` | Get storage usage |

## Build

```bash
./gradlew build
```
