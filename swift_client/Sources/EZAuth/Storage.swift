import Foundation

/// Storage usage.
public struct Storage: Sendable {
    let client: BaseClient

    public func tables() async throws -> StorageResponse {
        try await client.fetch(
            StorageResponse.self,
            path: "/v1/tables/storage",
            auth: .auto
        )
    }

    public func objects() async throws -> StorageResponse {
        try await client.fetch(
            StorageResponse.self,
            path: "/v1/buckets/storage",
            auth: .auto
        )
    }
}

// MARK: - Types

public struct StorageResponse: Decodable, Sendable {
    public let used_bytes: Int
    public let limit_bytes: Int
    public let used_percent: Double
}
