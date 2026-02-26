import Foundation

/// Universal EZAuth client for Swift.
///
/// Covers both frontend (publishable key) auth flows and backend (secret key)
/// admin operations including custom tables and object storage.
///
/// ```swift
/// let ez = EZAuth(
///     baseURL: "https://api.ezauth.org",
///     secretKey: "sk_test_..."
/// )
///
/// let users = try await ez.users.list()
/// let table = try await ez.tables.create(name: "contacts")
/// ```
public final class EZAuth: @unchecked Sendable {
    private let client: BaseClient

    /// Set or update the access token for user-scoped operations.
    public var accessToken: String? {
        get { client.accessToken }
        set { client.accessToken = newValue }
    }

    /// Frontend auth operations (publishable key).
    public var auth: Auth { Auth(client: client) }

    /// Backend user management (secret key).
    public var users: Users { Users(client: client) }

    /// Backend session management (secret key).
    public var sessions: Sessions { Sessions(client: client) }

    /// Table, column, and row CRUD.
    public var tables: Tables { Tables(client: client) }

    /// Bucket and object storage operations.
    public var buckets: Buckets { Buckets(client: client) }

    /// Storage usage.
    public var storage: Storage { Storage(client: client) }

    /// Creates a new EZAuth client.
    ///
    /// - Parameters:
    ///   - baseURL: The base URL of your EZAuth instance (e.g. `"https://api.ezauth.org"`).
    ///   - secretKey: Secret key for backend operations (`sk_...`).
    ///   - publishableKey: Publishable key for frontend auth (`pk_...`).
    ///   - accessToken: Access token (JWT) for user-scoped operations.
    ///   - session: Custom `URLSession` to use. Defaults to `.shared`.
    public init(
        baseURL: String,
        secretKey: String? = nil,
        publishableKey: String? = nil,
        accessToken: String? = nil,
        session: URLSession = .shared
    ) {
        self.client = BaseClient(
            baseURL: baseURL,
            secretKey: secretKey,
            publishableKey: publishableKey,
            accessToken: accessToken,
            session: session
        )
    }
}
