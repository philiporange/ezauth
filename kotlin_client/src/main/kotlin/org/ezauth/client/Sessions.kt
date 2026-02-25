package org.ezauth.client

import kotlinx.serialization.json.JsonPrimitive

/** Backend session management (secret key). */
class Sessions internal constructor(private val client: BaseClient) {

    suspend fun revoke(sessionId: String): RevokeResponse {
        val resp = client.fetch(
            "/v1/sessions/revoke",
            method = "POST",
            query = mapOf("session_id" to sessionId),
        )
        return client.json.decodeFromJsonElement(RevokeResponse.serializer(), resp!!)
    }

    suspend fun createSignInToken(
        userId: String,
        expiresInSeconds: Int? = null,
    ): SignInTokenResponse {
        val body = jsonObject(
            "user_id" to JsonPrimitive(userId),
            "expires_in_seconds" to if (expiresInSeconds != null) JsonPrimitive(expiresInSeconds) else null,
        )
        val resp = client.fetch("/v1/sign_in_tokens", method = "POST", body = body)
        return client.json.decodeFromJsonElement(SignInTokenResponse.serializer(), resp!!)
    }
}
