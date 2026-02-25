import Foundation

/// Universal EZAuth client for Swift.
///
/// Covers both frontend (publishable key) auth flows and backend (secret key)
/// admin operations including custom tables.
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

    /// Frontend auth operations (publishable key).
    public var auth: Auth { Auth(client: client) }

    /// Backend user management (secret key).
    public var users: Users { Users(client: client) }

    /// Backend session management (secret key).
    public var sessions: Sessions { Sessions(client: client) }

    /// Table, column, and row CRUD (secret key).
    public var tables: Tables { Tables(client: client) }

    /// Storage usage (secret key).
    public var storage: Storage { Storage(client: client) }

    /// Creates a new EZAuth client.
    ///
    /// - Parameters:
    ///   - baseURL: The base URL of your EZAuth instance (e.g. `"https://api.ezauth.org"`).
    ///   - secretKey: Secret key for backend operations (`sk_...`).
    ///   - publishableKey: Publishable key for frontend auth (`pk_...`).
    ///   - session: Custom `URLSession` to use. Defaults to `.shared`.
    public init(
        baseURL: String,
        secretKey: String? = nil,
        publishableKey: String? = nil,
        session: URLSession = .shared
    ) {
        self.client = BaseClient(
            baseURL: baseURL,
            secretKey: secretKey,
            publishableKey: publishableKey,
            session: session
        )
    }
}
