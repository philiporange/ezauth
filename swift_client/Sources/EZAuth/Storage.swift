import Foundation

/// Storage usage (secret key).
public struct Storage: Sendable {
    let client: BaseClient

    public func get() async throws -> StorageResponse {
        try await client.fetch(
            StorageResponse.self,
            path: "/v1/tables/storage"
        )
    }
}

// MARK: - Types

public struct StorageResponse: Decodable, Sendable {
    public let used_bytes: Int
    public let limit_bytes: Int
    public let used_percent: Double
}
