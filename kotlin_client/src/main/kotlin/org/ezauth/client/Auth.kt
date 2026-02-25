package org.ezauth.client

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/** Frontend auth operations (publishable key). */
class Auth internal constructor(private val client: BaseClient) {

    suspend fun signUp(
        email: String,
        password: String? = null,
        redirectUrl: String? = null,
    ): SignUpResponse {
        val body = jsonObject(
            "email" to JsonPrimitive(email),
            "password" to JsonPrimitive(password),
            "redirect_url" to JsonPrimitive(redirectUrl),
        )
        val resp = client.fetch("/v1/signups", method = "POST", body = body, auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SignUpResponse.serializer(), resp!!)
    }

    suspend fun signIn(
        email: String,
        password: String? = null,
        strategy: String? = null,
        redirectUrl: String? = null,
    ): SignInResponse {
        val resolvedStrategy = strategy ?: if (password != null) "password" else "magic_link"
        val body = jsonObject(
            "email" to JsonPrimitive(email),
            "password" to JsonPrimitive(password),
            "strategy" to JsonPrimitive(resolvedStrategy),
            "redirect_url" to JsonPrimitive(redirectUrl),
        )
        val resp = client.fetch("/v1/signins", method = "POST", body = body, auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SignInResponse.serializer(), resp!!)
    }

    suspend fun signOut(): SignOutResponse {
        val resp = client.fetch("/v1/sessions/logout", method = "POST", auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SignOutResponse.serializer(), resp!!)
    }

    suspend fun verifyCode(email: String, code: String): SessionResponse {
        val body = jsonObject(
            "email" to JsonPrimitive(email),
            "code" to JsonPrimitive(code),
        )
        val resp = client.fetch("/v1/verify-code", method = "POST", body = body, auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SessionResponse.serializer(), resp!!)
    }

    suspend fun getSession(): UserResponse {
        val resp = client.fetch("/v1/me", auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(UserResponse.serializer(), resp!!)
    }

    suspend fun refreshToken(refreshToken: String): SessionResponse {
        val body = jsonObject(
            "refresh_token" to JsonPrimitive(refreshToken),
        )
        val resp = client.fetch("/v1/tokens/session", method = "POST", body = body, auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SessionResponse.serializer(), resp!!)
    }

    suspend fun ssoExchange(token: String): SessionResponse {
        val body = jsonObject(
            "token" to JsonPrimitive(token),
        )
        val resp = client.fetch("/v1/sso/exchange", method = "POST", body = body, auth = AuthMode.PUBLISHABLE)
        return client.json.decodeFromJsonElement(SessionResponse.serializer(), resp!!)
    }
}
