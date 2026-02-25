import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttemptType
from ezauth.models.session import Session
from ezauth.models.user import User
from ezauth.ratelimiter import RateLimiter
from ezauth.crypto import generate_code
from ezauth.services import audit, mail, passwords, sessions, tokens


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_error"):
        self.message = message
        self.code = code
        super().__init__(message)


def _parse_rate_limit(config_str: str) -> list[tuple[int, int]]:
    try:
        window, count = config_str.split(":")
        return [(int(window), int(count))]
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid rate limit format {config_str!r}, expected 'window:count'") from e


async def signup(
    db: AsyncSession,
    redis,
    *,
    app: Application,
    email: str,
    password: str | None = None,
    redirect_url: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Register a new user and send verification email."""
    # Rate limit by IP
    ip_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signup_rate_limit_ip),
        user_id=ip_address or "unknown",
        namespace=str(app.id),
    )
    if not await ip_limiter.check_and_consume():
        raise AuthError("Too many signup attempts", code="rate_limited")

    # Rate limit by email
    email_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signup_rate_limit_email),
        user_id=email.lower(),
        namespace=str(app.id),
    )
    if not await email_limiter.check_and_consume():
        raise AuthError("Too many signup attempts for this email", code="rate_limited")

    # Check if user already exists
    existing = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    if existing.scalars().first() is not None:
        raise AuthError("User already exists", code="user_exists")

    # Create user
    password_hash = passwords.hash_password(password) if password else None
    user = User(
        app_id=app.id,
        email=email,
        password_hash=password_hash,
    )
    db.add(user)
    await db.flush()

    # Create verification token/code
    use_code = getattr(app, "verification_method", "code") == "code"

    if use_code:
        code = generate_code(6)
        attempt, raw_token = await tokens.create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.verify_email,
            email=email,
            user_id=user.id,
            redirect_url=redirect_url,
            expire_minutes=settings.verification_token_expire_minutes,
            metadata={"code": code},
        )
    else:
        attempt, raw_token = await tokens.create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.verify_email,
            email=email,
            user_id=user.id,
            redirect_url=redirect_url,
            expire_minutes=settings.verification_token_expire_minutes,
        )

    mail_svc = mail.MailService(
        sender_name=app.email_from_name,
        sender_address=app.email_from_address,
    )

    if use_code:
        try:
            await mail_svc.send_template(
                "confirmation_code",
                email,
                f"Your {app.name} verification code",
                {"summary": "Verification code", "confirmation_code": code, "name": email.split("@")[0], "app_name": app.name},
            )
        except Exception:
            logger.exception(f"Failed to send verification code to {email}")
    else:
        base_url = f"https://{app.primary_domain}" if app.primary_domain else "http://localhost:8000"
        verify_url = f"{base_url}/v1/email/verify?token={raw_token}"
        try:
            await mail_svc.send_template(
                "verification_link",
                email,
                "Please verify your email address",
                {"summary": "Verify your email", "verify_url": verify_url, "app_name": app.name},
            )
        except Exception:
            logger.exception(f"Failed to send verification email to {email}")

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.signup",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"User {user.id} signed up for app {app.id}")
    return {"user_id": str(user.id), "status": "verification_sent"}


async def consume_email_link_token(
    db: AsyncSession,
    *,
    raw_token: str,
    app: Application,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str, str | None]:
    """Consume a verify_email or signin magic link token and create a session.

    Accepts both token types so the same /v1/email/verify endpoint handles
    initial email verification AND magic-link sign-in.

    Returns (user, session, access_jwt, raw_refresh_token, redirect_url).
    """
    # Try consuming as verify_email first, then as signin
    attempt = await tokens.consume_auth_attempt(
        db, raw_token=raw_token, expected_type=AuthAttemptType.verify_email
    )
    if attempt is None:
        attempt = await tokens.consume_auth_attempt(
            db, raw_token=raw_token, expected_type=AuthAttemptType.signin
        )
    if attempt is None:
        raise AuthError("Invalid or expired token", code="invalid_token")

    user_result = await db.execute(select(User).where(User.id == attempt.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise AuthError("User not found", code="user_not_found")

    # Mark email as verified if this is a verification token or if not yet verified
    if attempt.type == AuthAttemptType.verify_email or user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    # Create session
    session, access_jwt, raw_refresh = await sessions.create_session(
        db, app=app, user=user
    )

    event = (
        "user.email_verified"
        if attempt.type == AuthAttemptType.verify_email
        else "user.signin_magic_link_consumed"
    )
    await audit.log_event(
        db,
        app_id=app.id,
        event_type=event,
        user_id=user.id,
        session_id=session.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return user, session, access_jwt, raw_refresh, attempt.redirect_url


async def consume_code(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    app: Application,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str, str | None]:
    """Consume a 6-digit verification/signin code and create a session.

    Returns (user, session, access_jwt, raw_refresh_token, redirect_url).
    """
    attempt = await tokens.consume_auth_attempt_by_code(
        db, email=email, code=code, app_id=app.id,
    )
    if attempt is None:
        raise AuthError("Invalid or expired code", code="invalid_code")

    user_result = await db.execute(select(User).where(User.id == attempt.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise AuthError("User not found", code="user_not_found")

    if attempt.type == AuthAttemptType.verify_email or user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    session, access_jwt, raw_refresh = await sessions.create_session(
        db, app=app, user=user
    )

    event = (
        "user.email_verified"
        if attempt.type == AuthAttemptType.verify_email
        else "user.signin_code_consumed"
    )
    await audit.log_event(
        db,
        app_id=app.id,
        event_type=event,
        user_id=user.id,
        session_id=session.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return user, session, access_jwt, raw_refresh, attempt.redirect_url


async def signin_magic_link(
    db: AsyncSession,
    redis,
    *,
    app: Application,
    email: str,
    redirect_url: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Send a magic link sign-in email."""
    # Rate limit by IP
    ip_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signin_rate_limit_ip),
        user_id=ip_address or "unknown",
        namespace=str(app.id),
    )
    if not await ip_limiter.check_and_consume():
        raise AuthError("Too many sign-in attempts", code="rate_limited")

    # Find user
    user_result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    user = user_result.scalars().first()
    if user is None:
        # Don't reveal whether user exists — still return success
        logger.info(f"Magic link requested for non-existent user: {email}")
        return {"status": "magic_link_sent"}

    # Create signin token/code
    use_code = getattr(app, "verification_method", "code") == "code"

    if use_code:
        code = generate_code(6)
        attempt, raw_token = await tokens.create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.signin,
            email=email,
            user_id=user.id,
            redirect_url=redirect_url,
            expire_minutes=settings.magic_link_expire_minutes,
            metadata={"code": code},
        )
    else:
        attempt, raw_token = await tokens.create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.signin,
            email=email,
            user_id=user.id,
            redirect_url=redirect_url,
            expire_minutes=settings.magic_link_expire_minutes,
        )

    mail_svc = mail.MailService(
        sender_name=app.email_from_name,
        sender_address=app.email_from_address,
    )

    if use_code:
        try:
            await mail_svc.send_template(
                "confirmation_code",
                email,
                f"Your {app.name} sign-in code",
                {"summary": "Sign-in code", "confirmation_code": code, "name": email.split("@")[0], "app_name": app.name},
            )
        except Exception:
            logger.exception(f"Failed to send sign-in code to {email}")
    else:
        base_url = f"https://{app.primary_domain}" if app.primary_domain else "http://localhost:8000"
        magic_url = f"{base_url}/v1/email/verify?token={raw_token}"
        try:
            await mail_svc.send_template(
                "magic_link_signin",
                email,
                f"Sign in to {app.name}",
                {"summary": "Sign in link", "magic_url": magic_url, "app_name": app.name},
            )
        except Exception:
            logger.exception(f"Failed to send magic link email to {email}")

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.signin_magic_link",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return {"status": "magic_link_sent"}


async def signin_password(
    db: AsyncSession,
    redis,
    *,
    app: Application,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str]:
    """Sign in with email + password.

    Returns (user, session, access_jwt, raw_refresh_token).
    """
    # Rate limit by IP
    ip_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signin_rate_limit_ip),
        user_id=ip_address or "unknown",
        namespace=str(app.id),
    )
    if not await ip_limiter.check_and_consume():
        raise AuthError("Too many sign-in attempts", code="rate_limited")

    # Find user
    user_result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    user = user_result.scalars().first()
    if user is None or user.password_hash is None:
        raise AuthError("Invalid email or password", code="invalid_credentials")

    if not passwords.verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password", code="invalid_credentials")

    # Rehash if needed
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        await db.flush()

    # Create session
    session, access_jwt, raw_refresh = await sessions.create_session(
        db, app=app, user=user
    )

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.signin_password",
        user_id=user.id,
        session_id=session.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return user, session, access_jwt, raw_refresh


async def logout(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    app_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> bool:
    revoked = await sessions.revoke_session(db, session_id=session_id)
    if revoked:
        await audit.log_event(
            db,
            app_id=app_id,
            event_type="user.logout",
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    return revoked
