import Foundation

/// Table and column CRUD.
public struct Tables: Sendable {
    let client: BaseClient

    /// Column management sub-namespace.
    public var columns: Columns { Columns(client: client) }

    /// Row management sub-namespace.
    public var rows: Rows { Rows(client: client) }

    // MARK: - Create table

    public func create(name: String, columns: [ColumnDefinition]? = nil) async throws -> TableDetailResponse {
        try await client.fetch(
            TableDetailResponse.self,
            path: "/v1/tables",
            method: "POST",
            body: CreateTableRequest(name: name, columns: columns),
            auth: .auto
        )
    }

    // MARK: - List tables

    public func list() async throws -> TableListResponse {
        try await client.fetch(
            TableListResponse.self,
            path: "/v1/tables",
            auth: .auto
        )
    }

    // MARK: - Get table

    public func get(_ tableId: String) async throws -> TableDetailResponse {
        try await client.fetch(
            TableDetailResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)",
            auth: .auto
        )
    }

    // MARK: - Delete table

    public func delete(_ tableId: String) async throws {
        try await client.fetch(
            path: "/v1/tables/\(tableId.urlPathEncoded)",
            method: "DELETE",
            auth: .auto
        )
    }
}

// MARK: - Columns sub-namespace

public struct Columns: Sendable {
    let client: BaseClient

    public func add(
        tableId: String,
        name: String,
        type: String,
        required: Bool = false,
        defaultValue: JSONValue? = nil,
        position: Int? = nil
    ) async throws -> ColumnResponse {
        try await client.fetch(
            ColumnResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/columns",
            method: "POST",
            body: CreateColumnRequest(
                name: name,
                type: type,
                required: required,
                default_value: defaultValue,
                position: position
            ),
            auth: .auto
        )
    }

    public func update(
        tableId: String,
        columnId: String,
        name: String? = nil,
        required: Bool? = nil,
        defaultValue: JSONValue? = nil,
        position: Int? = nil
    ) async throws -> ColumnResponse {
        try await client.fetch(
            ColumnResponse.self,
            path: "/v1/tables/\(tableId.urlPathEncoded)/columns/\(columnId.urlPathEncoded)",
            method: "PATCH",
            body: UpdateColumnRequest(
                name: name,
                required: required,
                default_value: defaultValue,
                position: position
            ),
            auth: .auto
        )
    }

    public func delete(tableId: String, columnId: String) async throws {
        try await client.fetch(
            path: "/v1/tables/\(tableId.urlPathEncoded)/columns/\(columnId.urlPathEncoded)",
            method: "DELETE",
            auth: .auto
        )
    }
}

// MARK: - Request types

struct CreateTableRequest: Encodable {
    let name: String
    let columns: [ColumnDefinition]?
}

/// Column definition used when creating a table.
public struct ColumnDefinition: Encodable, Sendable {
    public let name: String
    public let type: String
    public let required: Bool
    public let default_value: JSONValue?
    public let position: Int?

    public init(name: String, type: String, required: Bool = false, defaultValue: JSONValue? = nil, position: Int? = nil) {
        self.name = name
        self.type = type
        self.required = required
        self.default_value = defaultValue
        self.position = position
    }
}

struct CreateColumnRequest: Encodable {
    let name: String
    let type: String
    let required: Bool
    let default_value: JSONValue?
    let position: Int?
}

struct UpdateColumnRequest: Encodable {
    let name: String?
    let required: Bool?
    let default_value: JSONValue?
    let position: Int?
}

// MARK: - Response types

public struct TableResponse: Decodable, Sendable {
    public let id: String
    public let name: String
    public let created_at: String
    public let updated_at: String
}

public struct TableListResponse: Decodable, Sendable {
    public let tables: [TableResponse]
    public let total: Int
}

public struct TableDetailResponse: Decodable, Sendable {
    public let id: String
    public let name: String
    public let columns: [ColumnResponse]
    public let created_at: String
    public let updated_at: String
}

public struct ColumnResponse: Decodable, Sendable {
    public let id: String
    public let name: String
    public let type: String
    public let required: Bool
    public let default_value: JSONValue?
    public let position: Int
    public let created_at: String
    public let updated_at: String
}
