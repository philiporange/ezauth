package org.ezauth.client

/** Storage usage (secret key). */
class Storage internal constructor(private val client: BaseClient) {

    suspend fun get(): StorageResponse {
        val resp = client.fetch("/v1/tables/storage")
        return client.json.decodeFromJsonElement(StorageResponse.serializer(), resp!!)
    }
}
