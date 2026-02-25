import Foundation

/// Row CRUD and query operations (secret key).
public struct Rows: Sendable {
    let client: BaseClient

    // MARK: - Insert row

    public func insert(tableId: String, data: [String: JSONValue]) async throws -> RowResponse {
        try await client.fetch(
            RowResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/rows",
            method: "POST",
            body: CreateRowRequest(data: data)
        )
    }

    // MARK: - Get row

    public func get(tableId: String, rowId: String) async throws -> RowResponse {
        try await client.fetch(
            RowResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/rows/\(rowId.urlPathEncoded)"
        )
    }

    // MARK: - Update row

    public func update(tableId: String, rowId: String, data: [String: JSONValue]) async throws -> RowResponse {
        try await client.fetch(
            RowResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/rows/\(rowId.urlPathEncoded)",
            method: "PATCH",
            body: UpdateRowRequest(data: data)
        )
    }

    // MARK: - Delete row

    public func delete(tableId: String, rowId: String) async throws {
        try await client.fetch(
            path: "/v1/tables/\(tableId.urlPathEncoded)/rows/\(rowId.urlPathEncoded)",
            method: "DELETE"
        )
    }

    // MARK: - Query rows

    public func query(
        tableId: String,
        filter: JSONValue? = nil,
        sort: SortSpec? = nil,
        limit: Int? = nil,
        cursor: String? = nil
    ) async throws -> RowListResponse {
        try await client.fetch(
            RowListResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/rows/query",
            method: "POST",
            body: QueryRowsRequest(filter: filter, sort: sort, limit: limit, cursor: cursor)
        )
    }
}

// MARK: - Types

struct CreateRowRequest: Encodable {
    let data: [String: JSONValue]
}

struct UpdateRowRequest: Encodable {
    let data: [String: JSONValue]
}

public struct RowResponse: Decodable, Sendable {
    public let id: String
    public let data: [String: JSONValue]
    public let created_at: String
    public let updated_at: String
}

public struct RowListResponse: Decodable, Sendable {
    public let rows: [RowResponse]
    public let next_cursor: String?
}

public struct SortSpec: Encodable, Sendable {
    public let field: String
    public let dir: String

    public init(field: String, dir: String = "asc") {
        self.field = field
        self.dir = dir
    }
}

struct QueryRowsRequest: Encodable {
    let filter: JSONValue?
    let sort: SortSpec?
    let limit: Int?
    let cursor: String?
}
