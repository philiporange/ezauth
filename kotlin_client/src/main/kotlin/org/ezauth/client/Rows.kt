package org.ezauth.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Row CRUD and query operations (secret key). */
class Rows internal constructor(private val client: BaseClient) {

    suspend fun insert(tableId: String, data: JsonObject): RowResponse {
        val body = jsonObject("data" to data)
        val resp = client.fetch(
            "/v1/tables/${tableId.urlEncode()}/rows",
            method = "POST",
            body = body,
        )
        return client.json.decodeFromJsonElement(RowResponse.serializer(), resp!!)
    }

    suspend fun get(tableId: String, rowId: String): RowResponse {
        val resp = client.fetch("/v1/tables/${tableId.urlEncode()}/rows/${rowId.urlEncode()}")
        return client.json.decodeFromJsonElement(RowResponse.serializer(), resp!!)
    }

    suspend fun update(tableId: String, rowId: String, data: JsonObject): RowResponse {
        val body = jsonObject("data" to data)
        val resp = client.fetch(
            "/v1/tables/${tableId.urlEncode()}/rows/${rowId.urlEncode()}",
            method = "PATCH",
            body = body,
        )
        return client.json.decodeFromJsonElement(RowResponse.serializer(), resp!!)
    }

    suspend fun delete(tableId: String, rowId: String) {
        client.fetch(
            "/v1/tables/${tableId.urlEncode()}/rows/${rowId.urlEncode()}",
            method = "DELETE",
        )
    }

    suspend fun query(
        tableId: String,
        filter: JsonElement? = null,
        sort: SortSpec? = null,
        limit: Int? = null,
        cursor: String? = null,
    ): RowListResponse {
        val entries = mutableMapOf<String, JsonElement>()
        if (filter != null) entries["filter"] = filter
        if (sort != null) entries["sort"] = client.json.encodeToJsonElement(SortSpec.serializer(), sort)
        if (limit != null) entries["limit"] = JsonPrimitive(limit)
        if (cursor != null) entries["cursor"] = JsonPrimitive(cursor)
        val body = JsonObject(entries)
        val resp = client.fetch(
            "/v1/tables/${tableId.urlEncode()}/rows/query",
            method = "POST",
            body = body,
        )
        return client.json.decodeFromJsonElement(RowListResponse.serializer(), resp!!)
    }
}
