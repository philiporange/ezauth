package org.ezauth.client

import kotlinx.serialization.json.JsonPrimitive

/** Bucket and object storage operations. */
class Buckets internal constructor(private val client: BaseClient) {

    /** Object management sub-namespace. */
    val objects = Objects(client)

    suspend fun create(name: String): BucketResponse {
        val body = jsonObject("name" to JsonPrimitive(name))
        val resp = client.fetch("/v1/buckets", method = "POST", body = body, auth = AuthMode.AUTO)
        return client.json.decodeFromJsonElement(BucketResponse.serializer(), resp!!)
    }

    suspend fun list(): BucketListResponse {
        val resp = client.fetch("/v1/buckets", auth = AuthMode.AUTO)
        return client.json.decodeFromJsonElement(BucketListResponse.serializer(), resp!!)
    }

    suspend fun get(bucketId: String): BucketResponse {
        val resp = client.fetch("/v1/buckets/${bucketId.urlEncode()}", auth = AuthMode.AUTO)
        return client.json.decodeFromJsonElement(BucketResponse.serializer(), resp!!)
    }

    suspend fun delete(bucketId: String) {
        client.fetch("/v1/buckets/${bucketId.urlEncode()}", method = "DELETE", auth = AuthMode.AUTO)
    }
}

/** Object CRUD operations. */
class Objects internal constructor(private val client: BaseClient) {

    suspend fun put(
        bucketId: String,
        key: String,
        data: ByteArray,
        contentType: String = "application/octet-stream",
        userId: String? = null,
    ): ObjectResponse {
        val query = mutableMapOf<String, String?>()
        if (userId != null) query["user_id"] = userId
        val resp = client.fetchRaw(
            "/v1/buckets/${bucketId.urlEncode()}/objects/$key",
            method = "PUT",
            rawBody = data,
            contentType = contentType,
            query = query.ifEmpty { null },
        )
        resp.use { r ->
            val body = r.body?.string() ?: throw EZAuthError("Empty response", 0)
            val json = client.json.parseToJsonElement(body)
            return client.json.decodeFromJsonElement(ObjectResponse.serializer(), json)
        }
    }

    /** Downloads an object. Returns a pair of (data, contentType). */
    suspend fun get(
        bucketId: String,
        key: String,
        userId: String? = null,
    ): Pair<ByteArray, String> {
        val query = mutableMapOf<String, String?>()
        if (userId != null) query["user_id"] = userId
        val resp = client.fetchRaw(
            "/v1/buckets/${bucketId.urlEncode()}/objects/$key",
            method = "GET",
            contentType = "",
            query = query.ifEmpty { null },
        )
        resp.use { r ->
            val ct = r.header("Content-Type") ?: "application/octet-stream"
            val bytes = r.body?.bytes() ?: ByteArray(0)
            return bytes to ct
        }
    }

    suspend fun delete(
        bucketId: String,
        key: String,
        userId: String? = null,
    ) {
        val query = mutableMapOf<String, String?>()
        if (userId != null) query["user_id"] = userId
        client.fetchRaw(
            "/v1/buckets/${bucketId.urlEncode()}/objects/$key",
            method = "DELETE",
            contentType = "",
            query = query.ifEmpty { null },
        ).close()
    }

    suspend fun list(
        bucketId: String,
        userId: String? = null,
        limit: Int? = null,
        cursor: String? = null,
    ): ObjectListResponse {
        val query = mutableMapOf<String, String?>()
        if (userId != null) query["user_id"] = userId
        if (limit != null) query["limit"] = limit.toString()
        if (cursor != null) query["cursor"] = cursor
        val resp = client.fetch(
            "/v1/buckets/${bucketId.urlEncode()}/objects",
            auth = AuthMode.AUTO,
            query = query.ifEmpty { null },
        )
        return client.json.decodeFromJsonElement(ObjectListResponse.serializer(), resp!!)
    }
}
