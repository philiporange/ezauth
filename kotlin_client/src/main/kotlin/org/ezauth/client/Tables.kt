package org.ezauth.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/** Table and column CRUD (secret key). */
class Tables internal constructor(private val client: BaseClient) {

    /** Column management sub-namespace. */
    val columns = Columns(client)

    /** Row management sub-namespace. */
    val rows = Rows(client)

    suspend fun create(
        name: String,
        columns: List<ColumnDefinition>? = null,
    ): TableDetailResponse {
        val entries = mutableMapOf<String, JsonElement>(
            "name" to JsonPrimitive(name),
        )
        if (columns != null) {
            entries["columns"] = client.json.encodeToJsonElement(
                kotlinx.serialization.builtins.ListSerializer(ColumnDefinition.serializer()),
                columns,
            )
        }
        val body = kotlinx.serialization.json.JsonObject(entries)
        val resp = client.fetch("/v1/tables", method = "POST", body = body)
        return client.json.decodeFromJsonElement(TableDetailResponse.serializer(), resp!!)
    }

    suspend fun list(): TableListResponse {
        val resp = client.fetch("/v1/tables")
        return client.json.decodeFromJsonElement(TableListResponse.serializer(), resp!!)
    }

    suspend fun get(tableId: String): TableDetailResponse {
        val resp = client.fetch("/v1/tables/${tableId.urlEncode()}")
        return client.json.decodeFromJsonElement(TableDetailResponse.serializer(), resp!!)
    }

    suspend fun delete(tableId: String) {
        client.fetch("/v1/tables/${tableId.urlEncode()}", method = "DELETE")
    }
}

/** Column management operations (secret key). */
class Columns internal constructor(private val client: BaseClient) {

    suspend fun add(
        tableId: String,
        name: String,
        type: String,
        required: Boolean = false,
        defaultValue: JsonElement? = null,
        position: Int? = null,
    ): ColumnResponse {
        val body = jsonObject(
            "name" to JsonPrimitive(name),
            "type" to JsonPrimitive(type),
            "required" to JsonPrimitive(required),
            "default_value" to defaultValue,
            "position" to if (position != null) JsonPrimitive(position) else null,
        )
        val resp = client.fetch(
            "/v1/tables/${tableId.urlEncode()}/columns",
            method = "POST",
            body = body,
        )
        return client.json.decodeFromJsonElement(ColumnResponse.serializer(), resp!!)
    }

    suspend fun update(
        tableId: String,
        columnId: String,
        name: String? = null,
        required: Boolean? = null,
        defaultValue: JsonElement? = null,
        position: Int? = null,
    ): ColumnResponse {
        val entries = mutableMapOf<String, JsonElement>()
        if (name != null) entries["name"] = JsonPrimitive(name)
        if (required != null) entries["required"] = JsonPrimitive(required)
        if (defaultValue != null) entries["default_value"] = defaultValue
        if (position != null) entries["position"] = JsonPrimitive(position)
        val body = kotlinx.serialization.json.JsonObject(entries)
        val resp = client.fetch(
            "/v1/tables/${tableId.urlEncode()}/columns/${columnId.urlEncode()}",
            method = "PATCH",
            body = body,
        )
        return client.json.decodeFromJsonElement(ColumnResponse.serializer(), resp!!)
    }

    suspend fun delete(tableId: String, columnId: String) {
        client.fetch(
            "/v1/tables/${tableId.urlEncode()}/columns/${columnId.urlEncode()}",
            method = "DELETE",
        )
    }
}
