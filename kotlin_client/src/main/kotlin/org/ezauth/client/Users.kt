package org.ezauth.client

import kotlinx.serialization.json.JsonPrimitive

/** Backend user management (secret key). */
class Users internal constructor(private val client: BaseClient) {

    suspend fun list(
        limit: Int? = null,
        offset: Int? = null,
        email: String? = null,
    ): UserListResponse {
        val query = mutableMapOf<String, String?>()
        if (limit != null) query["limit"] = limit.toString()
        if (offset != null) query["offset"] = offset.toString()
        if (email != null) query["email"] = email
        val resp = client.fetch("/v1/users", query = query.ifEmpty { null })
        return client.json.decodeFromJsonElement(UserListResponse.serializer(), resp!!)
    }

    suspend fun create(email: String, password: String? = null): UserDetail {
        val body = jsonObject(
            "email" to JsonPrimitive(email),
            "password" to JsonPrimitive(password),
        )
        val resp = client.fetch("/v1/users", method = "POST", body = body)
        return client.json.decodeFromJsonElement(UserDetail.serializer(), resp!!)
    }

    suspend fun get(userId: String): UserDetail {
        val resp = client.fetch("/v1/users/${userId.urlEncode()}")
        return client.json.decodeFromJsonElement(UserDetail.serializer(), resp!!)
    }
}
