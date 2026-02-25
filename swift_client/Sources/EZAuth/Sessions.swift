import Foundation

/// Backend session management (secret key).
public struct Sessions: Sendable {
    let client: BaseClient

    // MARK: - Revoke session

    public func revoke(_ sessionId: String) async throws -> RevokeResponse {
        try await client.fetch(
            RevokeResponse.self,
            path: "/v1/sessions/revoke",
            method: "POST",
            query: ["session_id": sessionId]
        )
    }

    // MARK: - Create sign-in token

    public func createSignInToken(userId: String, expiresInSeconds: Int? = nil) async throws -> SignInTokenResponse {
        try await client.fetch(
            SignInTokenResponse.self,
            path: "/v1/sign_in_tokens",
            method: "POST",
            body: SignInTokenRequest(user_id: userId, expires_in_seconds: expiresInSeconds)
        )
    }
}

// MARK: - Types

public struct RevokeResponse: Decodable, Sendable {
    public let status: String
}

struct SignInTokenRequest: Encodable {
    let user_id: String
    let expires_in_seconds: Int?
}

public struct SignInTokenResponse: Decodable, Sendable {
    public let token: String
    public let refresh_token: String
    public let user_id: String
    public let session_id: String
    public let expires_at: String
}
