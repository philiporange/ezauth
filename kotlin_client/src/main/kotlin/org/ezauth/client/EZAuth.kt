package org.ezauth.client

import okhttp3.OkHttpClient

/**
 * Universal EZAuth client for Kotlin.
 *
 * Covers both frontend (publishable key) auth flows and backend (secret key)
 * admin operations including custom tables and object storage.
 *
 * ```kotlin
 * val ez = EZAuth(
 *     baseUrl = "https://api.ezauth.org",
 *     secretKey = "sk_test_..."
 * )
 *
 * val users = ez.users.list()
 * val table = ez.tables.create(name = "contacts")
 * ```
 */
class EZAuth(
    baseUrl: String,
    secretKey: String? = null,
    publishableKey: String? = null,
    accessToken: String? = null,
    httpClient: OkHttpClient = OkHttpClient(),
) {
    private val client = BaseClient(baseUrl, secretKey, publishableKey, accessToken, httpClient)

    /** Set or update the access token for user-scoped operations. */
    var accessToken: String?
        get() = client.accessToken
        set(value) { client.accessToken = value }

    /** Frontend auth operations (publishable key). */
    val auth = Auth(client)

    /** Backend user management (secret key). */
    val users = Users(client)

    /** Backend session management (secret key). */
    val sessions = Sessions(client)

    /** Table, column, and row CRUD. */
    val tables = Tables(client)

    /** Bucket and object storage operations. */
    val buckets = Buckets(client)

    /** Storage usage. */
    val storage = Storage(client)
}
