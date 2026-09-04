"""Application settings loaded from the environment.

Every setting is read from environment variables or a local `.env` file via
pydantic-settings. Values that are unsafe outside development (default database
credentials, the placeholder mail sender, a missing public base URL) are
rejected at import time when `environment` is set to `production`, so a
misconfigured deployment fails to boot instead of running with dev defaults.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings

DEV_DATABASE_URL = "postgresql+asyncpg://ezauth:ezauth@localhost:5432/ezauth"
DEV_REDIS_URL = "redis://localhost:6379/0"
DEV_SES_SENDER = "do-not-reply@example.com"
DEV_PUBLIC_BASE_URL = "http://localhost:8000"


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # Deployment environment: "development" or "production".
    environment: str = "development"

    # Public origin this service is reachable at, used to build links in email
    # and OAuth redirect URIs when an application has no primary domain.
    public_base_url: str = DEV_PUBLIC_BASE_URL

    # Database
    database_url: str = DEV_DATABASE_URL
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800

    # Redis
    redis_url: str = DEV_REDIS_URL

    # AWS SES
    ses_region: str = "us-east-1"
    ses_sender: str = DEV_SES_SENDER
    ses_sender_name: str = "ezAuth"

    # JWT
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    # Upper bound for backend-minted sign-in tokens.
    max_signin_token_lifetime_seconds: int = 86400

    # Session
    session_cookie_name: str = "__session"
    refresh_cookie_name: str = "__refresh"
    refresh_cookie_path: str = "/v1/tokens"
    session_cookie_domain: str = ""
    session_cookie_secure: bool = True
    # Suffix cookie names with an application discriminator so two
    # applications sharing a domain do not overwrite each other's session.
    session_cookie_per_app: bool = True
    # Check the sessions table on every cookie/bearer request so that logout
    # and revocation take effect before the access token expires.
    session_revocation_check: bool = True

    # Rate limits: "window_seconds:max_count"
    signup_rate_limit_ip: str = "60:10"  # 10 per minute per IP
    signup_rate_limit_email: str = "300:1"  # 1 per 5 min per email
    signin_rate_limit_ip: str = "60:10"
    signin_rate_limit_email: str = "300:3"
    code_verify_rate_limit_ip: str = "300:20"
    code_verify_rate_limit_email: str = "300:5"
    admin_auth_rate_limit_ip: str = "3600:10"
    admin_auth_rate_limit_email: str = "3600:5"
    admin_verify_rate_limit_ip: str = "3600:20"
    admin_verify_rate_limit_email: str = "3600:10"
    # Maximum wrong-code guesses before an auth attempt is burned.
    max_code_attempts: int = 5

    # Auth tokens
    verification_token_expire_minutes: int = 60
    magic_link_expire_minutes: int = 15

    # Dashboard
    # Comma-separated emails granted full (superadmin) dashboard access
    dashboard_admin_emails: str = ""
    dashboard_session_ttl_seconds: int = 43200  # 12 hours
    # Comma-separated origins allowed to call /dashboard with credentials.
    dashboard_allowed_origins: str = ""

    # Shared secret for internal endpoints reached through the reverse proxy.
    internal_api_secret: str = ""

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
    oauth_state_cookie_name: str = "__oauth_state"

    # S3 object storage
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-east-1"
    object_storage_max_object_bytes: int = 52428800  # 50 MB
    object_storage_limit_bytes: int = 1073741824  # 1 GB per app

    # Retention for the background cleanup task.
    cleanup_interval_seconds: int = 3600
    auth_attempt_retention_days: int = 7
    expired_session_retention_days: int = 30
    audit_log_retention_days: int = 365

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def dashboard_admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.dashboard_admin_emails.split(",") if e.strip()]

    @property
    def dashboard_allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.dashboard_allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _reject_dev_defaults_in_production(self) -> "Settings":
        if not self.is_production:
            return self
        problems = []
        if self.database_url == DEV_DATABASE_URL:
            problems.append("DATABASE_URL still uses the development credentials")
        if self.redis_url == DEV_REDIS_URL:
            problems.append("REDIS_URL still uses the development default")
        if self.ses_sender == DEV_SES_SENDER:
            problems.append("SES_SENDER is still the example.com placeholder")
        if self.public_base_url == DEV_PUBLIC_BASE_URL:
            problems.append("PUBLIC_BASE_URL is still http://localhost:8000")
        if not self.public_base_url.startswith("https://"):
            problems.append("PUBLIC_BASE_URL must be https in production")
        if not self.session_cookie_secure:
            problems.append("SESSION_COOKIE_SECURE must be true in production")
        if problems:
            raise ValueError(
                "Refusing to start with development defaults in production: "
                + "; ".join(problems)
            )
        return self


settings = Settings()
