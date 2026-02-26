import Foundation

/// Error thrown by all EZAuth client methods.
public struct EZAuthError: Error, Sendable {
    /// Human-readable error message from the API.
    public let message: String
    /// HTTP status code (0 for local errors).
    public let status: Int
    /// Machine-readable error code from the API, if any.
    public let code: String?

    public init(message: String, status: Int, code: String? = nil) {
        self.message = message
        self.status = status
        self.code = code
    }
}

extension EZAuthError: LocalizedError {
    public var errorDescription: String? { message }
}

// MARK: - Auth mode

enum AuthMode {
    case secret
    case publishable
    case auto
}

// MARK: - Base HTTP client

class BaseClient: @unchecked Sendable {
    let baseURL: String
    let secretKey: String?
    let publishableKey: String?
    var accessToken: String?
    let session: URLSession
    let decoder: JSONDecoder
    let encoder: JSONEncoder

    init(baseURL: String, secretKey: String?, publishableKey: String?, accessToken: String?, session: URLSession) {
        self.baseURL = baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL
        self.secretKey = secretKey
        self.publishableKey = publishableKey
        self.accessToken = accessToken
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - Core fetch (JSON)

    func fetch<T: Decodable>(
        _ type: T.Type,
        path: String,
        method: String = "GET",
        body: (any Encodable)? = nil,
        auth: AuthMode = .secret,
        query: [String: String?]? = nil
    ) async throws -> T {
        let request = try buildRequest(path: path, method: method, body: body, auth: auth, query: query)
        let (data, response) = try await session.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw EZAuthError(message: "Invalid response", status: 0)
        }

        if http.statusCode == 204 {
            if let empty = EmptyResponse() as? T {
                return empty
            }
            throw EZAuthError(message: "Unexpected 204 response", status: 204)
        }

        guard (200..<300).contains(http.statusCode) else {
            let detail = try? decoder.decode(ErrorBody.self, from: data)
            throw EZAuthError(
                message: detail?.detail ?? "Request failed: \(http.statusCode)",
                status: http.statusCode,
                code: detail?.code
            )
        }

        return try decoder.decode(T.self, from: data)
    }

    /// Fire-and-forget variant for DELETE / 204 endpoints.
    func fetch(
        path: String,
        method: String = "GET",
        body: (any Encodable)? = nil,
        auth: AuthMode = .secret,
        query: [String: String?]? = nil
    ) async throws {
        let request = try buildRequest(path: path, method: method, body: body, auth: auth, query: query)
        let (data, response) = try await session.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw EZAuthError(message: "Invalid response", status: 0)
        }

        guard (200..<300).contains(http.statusCode) else {
            let detail = try? decoder.decode(ErrorBody.self, from: data)
            throw EZAuthError(
                message: detail?.detail ?? "Request failed: \(http.statusCode)",
                status: http.statusCode,
                code: detail?.code
            )
        }
    }

    // MARK: - Raw data fetch (for binary upload/download)

    func fetchData(
        path: String,
        method: String = "GET",
        rawBody: Data? = nil,
        contentType: String = "application/octet-stream",
        auth: AuthMode = .auto,
        query: [String: String?]? = nil
    ) async throws -> (Data, HTTPURLResponse) {
        let request = try buildRawRequest(
            path: path, method: method, rawBody: rawBody,
            contentType: contentType, auth: auth, query: query
        )
        let (data, response) = try await session.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw EZAuthError(message: "Invalid response", status: 0)
        }

        guard (200..<300).contains(http.statusCode) else {
            let detail = try? decoder.decode(ErrorBody.self, from: data)
            throw EZAuthError(
                message: detail?.detail ?? "Request failed: \(http.statusCode)",
                status: http.statusCode,
                code: detail?.code
            )
        }

        return (data, http)
    }

    // MARK: - Auth helpers

    private func applyAuth(to request: inout URLRequest, mode: AuthMode) throws {
        switch mode {
        case .secret:
            guard let key = secretKey else {
                throw EZAuthError(message: "secretKey is required for this operation", status: 0, code: "missing_key")
            }
            request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        case .publishable:
            guard let key = publishableKey else {
                throw EZAuthError(message: "publishableKey is required for this operation", status: 0, code: "missing_key")
            }
            request.setValue(key, forHTTPHeaderField: "X-Publishable-Key")
        case .auto:
            if let key = secretKey {
                request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            } else if let key = publishableKey {
                request.setValue(key, forHTTPHeaderField: "X-Publishable-Key")
                guard let token = accessToken else {
                    throw EZAuthError(message: "accessToken is required for user operations", status: 0, code: "missing_token")
                }
                request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            } else {
                throw EZAuthError(message: "secretKey or publishableKey is required", status: 0, code: "missing_key")
            }
        }
    }

    // MARK: - Request builders

    private func buildRequest(
        path: String,
        method: String,
        body: (any Encodable)?,
        auth: AuthMode,
        query: [String: String?]?
    ) throws -> URLRequest {
        let url = try buildURL(path: path, query: query)

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        try applyAuth(to: &request, mode: auth)

        if let body {
            request.httpBody = try encoder.encode(body)
        }

        return request
    }

    private func buildRawRequest(
        path: String,
        method: String,
        rawBody: Data?,
        contentType: String,
        auth: AuthMode,
        query: [String: String?]?
    ) throws -> URLRequest {
        let url = try buildURL(path: path, query: query)

        var request = URLRequest(url: url)
        request.httpMethod = method

        if !contentType.isEmpty {
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }

        try applyAuth(to: &request, mode: auth)

        if let rawBody {
            request.httpBody = rawBody
        }

        return request
    }

    private func buildURL(path: String, query: [String: String?]?) throws -> URL {
        var urlString = "\(baseURL)\(path)"

        if let query, !query.isEmpty {
            guard var components = URLComponents(string: urlString) else {
                throw EZAuthError(message: "Invalid URL: \(urlString)", status: 0)
            }
            components.queryItems = query.compactMap { key, value in
                guard let value else { return nil }
                return URLQueryItem(name: key, value: value)
            }
            guard let built = components.url else {
                throw EZAuthError(message: "Invalid URL: \(urlString)", status: 0)
            }
            urlString = built.absoluteString
        }

        guard let url = URL(string: urlString) else {
            throw EZAuthError(message: "Invalid URL: \(urlString)", status: 0)
        }

        return url
    }
}

// MARK: - Internal helpers

struct ErrorBody: Decodable {
    let detail: String?
    let code: String?
}

/// Placeholder type for 204 No Content responses.
public struct EmptyResponse: Decodable, Sendable {
    public init() {}
}
