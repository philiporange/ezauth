package org.ezauth.client

/** Storage usage. */
class Storage internal constructor(private val client: BaseClient) {

    suspend fun tables(): StorageResponse {
        val resp = client.fetch("/v1/tables/storage", auth = AuthMode.AUTO)
        return client.json.decodeFromJsonElement(StorageResponse.serializer(), resp!!)
    }

    suspend fun objects(): StorageResponse {
        val resp = client.fetch("/v1/buckets/storage", auth = AuthMode.AUTO)
        return client.json.decodeFromJsonElement(StorageResponse.serializer(), resp!!)
    }
}
