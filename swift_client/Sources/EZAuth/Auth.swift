import Foundation

/// Frontend auth operations (publishable key).
public struct Auth: Sendable {
    let client: BaseClient

    // MARK: - Hashcash

    /// Request a hashcash proof-of-work challenge.
    public func requestChallenge() async throws -> HashcashChallenge {
        try await client.fetch(
            HashcashChallenge.self,
            path: "/v1/challenges",
            method: "POST",
            auth: .publishable
        )
    }

    // MARK: - Sign up

    /// Create a user. Proof of work is on by default on the server, so unless
    /// `hashcash` is supplied a challenge is requested and solved first. Pass
    /// `solveHashcash: false` against a server that has it turned off.
    public func signUp(
        email: String,
        password: String? = nil,
        redirectUrl: String? = nil,
        hashcash: HashcashProof? = nil,
        solveHashcash: Bool = true
    ) async throws -> SignUpResponse {
        var proof = hashcash
        if proof == nil, solveHashcash {
            let challenge = try await requestChallenge()
            proof = await Task.detached(priority: .userInitiated) {
                Hashcash.solve(challenge)
            }.value
        }

        return try await client.fetch(
            SignUpResponse.self,
            path: "/v1/signups",
            method: "POST",
            body: SignUpRequest(
                email: email, password: password, redirect_url: redirectUrl, hashcash: proof
            ),
            auth: .publishable
        )
    }

    // MARK: - Sign in

    public func signIn(email: String, password: String? = nil, strategy: String? = nil, redirectUrl: String? = nil) async throws -> SignInResponse {
        let resolvedStrategy = strategy ?? (password != nil ? "password" : "magic_link")
        return try await client.fetch(
            SignInResponse.self,
            path: "/v1/signins",
            method: "POST",
            body: SignInRequest(email: email, password: password, strategy: resolvedStrategy, redirect_url: redirectUrl),
            auth: .publishable
        )
    }

    // MARK: - Sign out

    public func signOut() async throws -> SignOutResponse {
        try await client.fetch(
            SignOutResponse.self,
            path: "/v1/sessions/logout",
            method: "POST",
            auth: .publishable,
            bearer: true
        )
    }

    // MARK: - Verify code

    public func verifyCode(email: String, code: String) async throws -> SessionResponse {
        try await client.fetch(
            SessionResponse.self,
            path: "/v1/verify-code",
            method: "POST",
            body: VerifyCodeRequest(email: email, code: code),
            auth: .publishable
        )
    }

    // MARK: - Get session

    public func getSession() async throws -> UserResponse {
        try await client.fetch(
            UserResponse.self,
            path: "/v1/me",
            auth: .publishable,
            bearer: true
        )
    }

    // MARK: - Refresh token

    public func refreshToken(_ refreshToken: String) async throws -> SessionResponse {
        try await client.fetch(
            SessionResponse.self,
            path: "/v1/tokens/session",
            method: "POST",
            body: RefreshTokenRequest(refresh_token: refreshToken),
            auth: .publishable
        )
    }

    // MARK: - SSO exchange

    public func ssoExchange(token: String) async throws -> SessionResponse {
        try await client.fetch(
            SessionResponse.self,
            path: "/v1/sso/exchange",
            method: "POST",
            body: SSOExchangeRequest(token: token),
            auth: .publishable
        )
    }

    // MARK: - OAuth

    public func signInWithOAuth(provider: String, redirectUrl: String) async throws -> OAuthAuthorizeResponse {
        try await client.fetch(
            OAuthAuthorizeResponse.self,
            path: "/v1/oauth/\(provider)/authorize",
            auth: .publishable,
            query: ["redirect_url": redirectUrl]
        )
    }
}

// MARK: - Request / Response types

struct SignUpRequest: Encodable {
    let email: String
    let password: String?
    let redirect_url: String?
    let hashcash: HashcashProof?
}

public struct SignUpResponse: Decodable, Sendable {
    public let status: String
    public let user_id: String
}

struct SignInRequest: Encodable {
    let email: String
    let password: String?
    let strategy: String
    let redirect_url: String?
}

public struct SignInResponse: Decodable, Sendable {
    public let status: String?
    public let user_id: String?
    public let access_token: String?
    public let refresh_token: String?
    public let session_id: String?
}

public struct SignOutResponse: Decodable, Sendable {
    public let status: String
}

struct VerifyCodeRequest: Encodable {
    let email: String
    let code: String
}

public struct SessionResponse: Decodable, Sendable {
    public let access_token: String
    public let refresh_token: String
    public let user_id: String
    public let session_id: String
}

public struct UserResponse: Decodable, Sendable {
    public let user_id: String
    public let email: String
    public let email_verified: Bool
    public let is_bot: Bool?
}

struct RefreshTokenRequest: Encodable {
    let refresh_token: String
}

struct SSOExchangeRequest: Encodable {
    let token: String
}

public struct OAuthAuthorizeResponse: Decodable, Sendable {
    public let authorization_url: String
}
