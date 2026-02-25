package org.ezauth.client

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

// ── Auth ────────────────────────────────────────────────────────────────────

@Serializable
data class SignUpResponse(
    val status: String,
    val user_id: String,
)

@Serializable
data class SignInResponse(
    val status: String? = null,
    val user_id: String? = null,
    val access_token: String? = null,
    val refresh_token: String? = null,
    val session_id: String? = null,
)

@Serializable
data class SignOutResponse(
    val status: String,
)

@Serializable
data class SessionResponse(
    val access_token: String,
    val refresh_token: String,
    val user_id: String,
    val session_id: String,
)

@Serializable
data class UserResponse(
    val user_id: String,
    val email: String,
    val email_verified: Boolean,
    val is_bot: Boolean? = null,
)

// ── Users ───────────────────────────────────────────────────────────────────

@Serializable
data class UserDetail(
    val id: String,
    val email: String,
    val email_verified: Boolean,
    val created_at: String,
    val updated_at: String,
)

@Serializable
data class UserListResponse(
    val users: List<UserDetail>,
    val total: Int,
)

// ── Sessions ────────────────────────────────────────────────────────────────

@Serializable
data class RevokeResponse(
    val status: String,
)

@Serializable
data class SignInTokenResponse(
    val token: String,
    val refresh_token: String,
    val user_id: String,
    val session_id: String,
    val expires_at: String,
)

// ── Tables ──────────────────────────────────────────────────────────────────

@Serializable
data class ColumnDefinition(
    val name: String,
    val type: String,
    val required: Boolean = false,
    val default_value: JsonElement? = null,
    val position: Int? = null,
)

@Serializable
data class ColumnResponse(
    val id: String,
    val name: String,
    val type: String,
    val required: Boolean,
    val default_value: JsonElement? = null,
    val position: Int,
    val created_at: String,
    val updated_at: String,
)

@Serializable
data class TableResponse(
    val id: String,
    val name: String,
    val created_at: String,
    val updated_at: String,
)

@Serializable
data class TableListResponse(
    val tables: List<TableResponse>,
    val total: Int,
)

@Serializable
data class TableDetailResponse(
    val id: String,
    val name: String,
    val columns: List<ColumnResponse>,
    val created_at: String,
    val updated_at: String,
)

// ── Rows ────────────────────────────────────────────────────────────────────

@Serializable
data class RowResponse(
    val id: String,
    val data: JsonObject,
    val created_at: String,
    val updated_at: String,
)

@Serializable
data class RowListResponse(
    val rows: List<RowResponse>,
    val next_cursor: String? = null,
)

@Serializable
data class SortSpec(
    val field: String,
    val dir: String = "asc",
)

// ── Storage ─────────────────────────────────────────────────────────────────

@Serializable
data class StorageResponse(
    val used_bytes: Long,
    val limit_bytes: Long,
    val used_percent: Double,
)
