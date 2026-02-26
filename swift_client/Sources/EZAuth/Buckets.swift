import Foundation

/// Bucket and object storage operations.
public struct Buckets: Sendable {
    let client: BaseClient

    /// Object management sub-namespace.
    public var objects: Objects { Objects(client: client) }

    // MARK: - Create bucket

    public func create(name: String) async throws -> BucketResponse {
        try await client.fetch(
            BucketResponse.self,
            path: "/v1/buckets",
            method: "POST",
            body: CreateBucketRequest(name: name),
            auth: .auto
        )
    }

    // MARK: - List buckets

    public func list() async throws -> BucketListResponse {
        try await client.fetch(
            BucketListResponse.self,
            path: "/v1/buckets",
            auth: .auto
        )
    }

    // MARK: - Get bucket

    public func get(_ bucketId: String) async throws -> BucketResponse {
        try await client.fetch(
            BucketResponse.self,
            path: "/v1/buckets/\(bucketId.urlPathEncoded)",
            auth: .auto
        )
    }

    // MARK: - Delete bucket

    public func delete(_ bucketId: String) async throws {
        try await client.fetch(
            path: "/v1/buckets/\(bucketId.urlPathEncoded)",
            method: "DELETE",
            auth: .auto
        )
    }
}

// MARK: - Objects sub-namespace

/// Object CRUD operations.
public struct Objects: Sendable {
    let client: BaseClient

    /// Upload an object. Returns metadata about the uploaded object.
    public func put(
        bucketId: String,
        key: String,
        data: Data,
        contentType: String = "application/octet-stream",
        userId: String? = nil
    ) async throws -> ObjectResponse {
        var query: [String: String?] = [:]
        if let userId { query["user_id"] = userId }

        let (responseData, _) = try await client.fetchData(
            path: "/v1/buckets/\(bucketId.urlPathEncoded)/objects/\(key)",
            method: "PUT",
            rawBody: data,
            contentType: contentType,
            query: query.isEmpty ? nil : query
        )
        return try client.decoder.decode(ObjectResponse.self, from: responseData)
    }

    /// Download an object. Returns `(data, contentType)`.
    public func get(
        bucketId: String,
        key: String,
        userId: String? = nil
    ) async throws -> (Data, String) {
        var query: [String: String?] = [:]
        if let userId { query["user_id"] = userId }

        let (data, http) = try await client.fetchData(
            path: "/v1/buckets/\(bucketId.urlPathEncoded)/objects/\(key)",
            method: "GET",
            contentType: "",
            query: query.isEmpty ? nil : query
        )
        let ct = http.value(forHTTPHeaderField: "Content-Type") ?? "application/octet-stream"
        return (data, ct)
    }

    /// Delete an object.
    public func delete(
        bucketId: String,
        key: String,
        userId: String? = nil
    ) async throws {
        var query: [String: String?] = [:]
        if let userId { query["user_id"] = userId }

        _ = try await client.fetchData(
            path: "/v1/buckets/\(bucketId.urlPathEncoded)/objects/\(key)",
            method: "DELETE",
            contentType: "",
            query: query.isEmpty ? nil : query
        )
    }

    /// List objects in a bucket.
    public func list(
        bucketId: String,
        userId: String? = nil,
        limit: Int? = nil,
        cursor: String? = nil
    ) async throws -> ObjectListResponse {
        var query: [String: String?] = [:]
        if let userId { query["user_id"] = userId }
        if let limit { query["limit"] = String(limit) }
        if let cursor { query["cursor"] = cursor }

        return try await client.fetch(
            ObjectListResponse.self,
            path: "/v1/buckets/\(bucketId.urlPathEncoded)/objects",
            auth: .auto,
            query: query.isEmpty ? nil : query
        )
    }
}

// MARK: - Request types

struct CreateBucketRequest: Encodable {
    let name: String
}

// MARK: - Response types

public struct BucketResponse: Decodable, Sendable {
    public let id: String
    public let name: String
    public let created_at: String
    public let updated_at: String
}

public struct BucketListResponse: Decodable, Sendable {
    public let buckets: [BucketResponse]
    public let total: Int
}

public struct ObjectResponse: Decodable, Sendable {
    public let id: String
    public let key: String
    public let content_type: String
    public let size_bytes: Int
    public let user_id: String
    public let created_at: String
    public let updated_at: String
}

public struct ObjectListResponse: Decodable, Sendable {
    public let objects: [ObjectResponse]
    public let next_cursor: String?
}
