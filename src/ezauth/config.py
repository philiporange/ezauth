from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Database
    database_url: str = "postgresql+asyncpg://ezauth:ezauth@localhost:5432/ezauth"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AWS SES
    ses_region: str = "us-east-1"
    ses_sender: str = "do-not-reply@example.com"
    ses_sender_name: str = "EZAuth"

    # JWT
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    # Session
    session_cookie_name: str = "__session"
    session_cookie_domain: str = ""
    session_cookie_secure: bool = True

    # Rate limits: list of (window_seconds, max_count)
    signup_rate_limit_ip: str = "60:10"  # 10 per minute per IP
    signup_rate_limit_email: str = "300:1"  # 1 per 5 min per email
    signin_rate_limit_ip: str = "60:10"

    # Auth tokens
    verification_token_expire_minutes: int = 60
    magic_link_expire_minutes: int = 15

    # Dashboard
    dashboard_secret_key: str = "change-me-in-production"

    # Hashcash proof-of-work
    hashcash_enabled: bool = True
    hashcash_difficulty: int = 5
    hashcash_challenge_ttl: int = 300
    hashcash_time_cost: int = 2
    hashcash_memory_cost: int = 19456
    hashcash_parallelism: int = 1
    hashcash_hash_len: int = 32

    # Mail charset
    mail_charset: str = "UTF-8"

    # Bot authentication
    confirmations_api_url: str = "https://api.confirmations.info"
    bot_auth_timestamp_tolerance: int = 300  # 5 minutes

    # Custom tables
    custom_tables_storage_limit_bytes: int = 104857600  # 100 MB

    # OAuth
    oauth_state_ttl_seconds: int = 600  # 10 min TTL for CSRF state nonce in Redis

    # S3 object storage
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-east-1"
    object_storage_max_object_bytes: int = 52428800  # 50 MB
    object_storage_limit_bytes: int = 1073741824  # 1 GB per app


settings = Settings()
