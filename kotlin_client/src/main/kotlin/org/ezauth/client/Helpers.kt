package org.ezauth.client

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject

/** URL-encode a string for use in a path segment. */
internal fun String.urlEncode(): String =
    java.net.URLEncoder.encode(this, "UTF-8").replace("+", "%20")

/** Build a [JsonObject], automatically dropping entries whose value is [JsonNull]. */
internal fun jsonObject(vararg entries: Pair<String, JsonElement?>): JsonObject =
    JsonObject(entries.mapNotNull { (k, v) -> if (v == null || v is JsonNull) null else k to v }.toMap())
