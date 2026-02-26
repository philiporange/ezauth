package org.ezauth.client

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/** Error thrown by all EZAuth client methods. */
class EZAuthError(
    /** Human-readable error message from the API. */
    override val message: String,
    /** HTTP status code (0 for local errors). */
    val status: Int,
    /** Machine-readable error code from the API, if any. */
    val code: String? = null,
) : Exception(message)

internal enum class AuthMode { SECRET, PUBLISHABLE, AUTO }

private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

internal class BaseClient(
    baseUrl: String,
    val secretKey: String?,
    val publishableKey: String?,
    var accessToken: String?,
    val httpClient: OkHttpClient,
) {
    val baseUrl: String = baseUrl.trimEnd('/')

    val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    /** Fetch that returns a decoded [JsonObject]. */
    suspend fun fetch(
        path: String,
        method: String = "GET",
        body: JsonElement? = null,
        auth: AuthMode = AuthMode.SECRET,
        query: Map<String, String?>? = null,
    ): JsonObject? {
        val request = buildRequest(path, method, body, auth, query)
        return withContext(Dispatchers.IO) {
            val response = httpClient.newCall(request).execute()
            response.use { resp ->
                if (resp.code == 204) return@withContext null

                val responseBody = resp.body?.string()

                if (!resp.isSuccessful) {
                    val detail = responseBody?.let {
                        try { json.parseToJsonElement(it).jsonObject } catch (_: Exception) { null }
                    }
                    throw EZAuthError(
                        message = detail?.get("detail")?.jsonPrimitive?.contentOrNull
                            ?: "Request failed: ${resp.code}",
                        status = resp.code,
                        code = detail?.get("code")?.jsonPrimitive?.contentOrNull,
                    )
                }

                responseBody?.let { json.parseToJsonElement(it).jsonObject }
            }
        }
    }

    /** Raw fetch that returns the OkHttp [Response]. Caller must close it. */
    suspend fun fetchRaw(
        path: String,
        method: String = "GET",
        rawBody: ByteArray? = null,
        contentType: String = "application/octet-stream",
        auth: AuthMode = AuthMode.AUTO,
        query: Map<String, String?>? = null,
    ): Response {
        val urlBuilder = "$baseUrl$path".toHttpUrl().newBuilder()
        query?.forEach { (key, value) ->
            if (value != null) urlBuilder.addQueryParameter(key, value)
        }

        val requestBody = when {
            rawBody != null -> rawBody.toRequestBody(contentType.toMediaType())
            method in listOf("POST", "PATCH", "PUT") -> "".toRequestBody(null)
            else -> null
        }

        val builder = Request.Builder()
            .url(urlBuilder.build())
            .method(method, requestBody)

        if (contentType.isNotEmpty()) {
            builder.header("Content-Type", contentType)
        }

        applyAuth(builder, auth)

        val request = builder.build()
        return withContext(Dispatchers.IO) {
            val resp = httpClient.newCall(request).execute()
            if (!resp.isSuccessful && resp.code != 204) {
                resp.use { r ->
                    val body = r.body?.string()
                    val detail = body?.let {
                        try { json.parseToJsonElement(it).jsonObject } catch (_: Exception) { null }
                    }
                    throw EZAuthError(
                        message = detail?.get("detail")?.jsonPrimitive?.contentOrNull
                            ?: "Request failed: ${r.code}",
                        status = r.code,
                        code = detail?.get("code")?.jsonPrimitive?.contentOrNull,
                    )
                }
            }
            resp
        }
    }

    private fun applyAuth(builder: Request.Builder, auth: AuthMode) {
        when (auth) {
            AuthMode.SECRET -> {
                val key = secretKey
                    ?: throw EZAuthError("secretKey is required for this operation", 0, "missing_key")
                builder.header("Authorization", "Bearer $key")
            }
            AuthMode.PUBLISHABLE -> {
                val key = publishableKey
                    ?: throw EZAuthError("publishableKey is required for this operation", 0, "missing_key")
                builder.header("X-Publishable-Key", key)
            }
            AuthMode.AUTO -> {
                if (secretKey != null) {
                    builder.header("Authorization", "Bearer $secretKey")
                } else if (publishableKey != null) {
                    builder.header("X-Publishable-Key", publishableKey)
                    val token = accessToken
                        ?: throw EZAuthError("accessToken is required for user operations", 0, "missing_token")
                    builder.header("Authorization", "Bearer $token")
                } else {
                    throw EZAuthError("secretKey or publishableKey is required", 0, "missing_key")
                }
            }
        }
    }

    private fun buildRequest(
        path: String,
        method: String,
        body: JsonElement?,
        auth: AuthMode,
        query: Map<String, String?>?,
    ): Request {
        val urlBuilder = "$baseUrl$path".toHttpUrl().newBuilder()
        query?.forEach { (key, value) ->
            if (value != null) urlBuilder.addQueryParameter(key, value)
        }

        val requestBody = when {
            body != null -> json.encodeToString(JsonElement.serializer(), body)
                .toRequestBody(JSON_MEDIA_TYPE)
            method in listOf("POST", "PATCH", "PUT") -> "".toRequestBody(JSON_MEDIA_TYPE)
            else -> null
        }

        val builder = Request.Builder()
            .url(urlBuilder.build())
            .method(method, requestBody)
            .header("Content-Type", "application/json")

        applyAuth(builder, auth)

        return builder.build()
    }
}
