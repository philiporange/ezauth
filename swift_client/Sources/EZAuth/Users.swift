import Foundation

/// Backend user management (secret key).
public struct Users: Sendable {
    let client: BaseClient

    // MARK: - List users

    public func list(limit: Int? = nil, offset: Int? = nil, email: String? = nil) async throws -> UserListResponse {
        var query: [String: String?] = [:]
        if let limit { query["limit"] = String(limit) }
        if let offset { query["offset"] = String(offset) }
        if let email { query["email"] = email }

        return try await client.fetch(
            UserListResponse.self,
            path: "/v1/users",
            query: query.isEmpty ? nil : query
        )
    }

    // MARK: - Create user

    public func create(email: String, password: String? = nil) async throws -> UserDetail {
        try await client.fetch(
            UserDetail.self,
            path: "/v1/users",
            method: "POST",
            body: CreateUserRequest(email: email, password: password)
        )
    }

    // MARK: - Get user

    public func get(_ userId: String) async throws -> UserDetail {
        try await client.fetch(
            UserDetail.self,
            path: "/v1/users/\(userId.urlPathEncoded)"
        )
    }
}

// MARK: - Types

struct CreateUserRequest: Encodable {
    let email: String
    let password: String?
}

public struct UserDetail: Decodable, Sendable {
    public let id: String
    public let email: String
    public let email_verified: Bool
    public let created_at: String
    public let updated_at: String
}

public struct UserListResponse: Decodable, Sendable {
    public let users: [UserDetail]
    public let total: Int
}
