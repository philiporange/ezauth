"""Email-based authentication: signup, magic links, codes, password sign-in.

Every flow that issues a credential goes through here. Signup and sign-in are
rate limited per IP and per email address, and both return the same response
whether or not the address is registered, so neither endpoint can be used to
enumerate accounts; a signup for an existing address sends that address a
sign-in link instead of creating a duplicate. Password sign-in runs an Argon2
verification even when no user matches, so a miss costs the same time as a hit,
and refuses accounts whose email has never been verified, which is what stops
an unverified password signup from later capturing an OAuth login for the same
address.

Redirect targets supplied by the caller are validated against the application's
primary and verified domains before they are stored on an auth attempt, so a
link delivered by the service can only ever return the browser to a domain the
application controls. Codes and link tokens are consumed through the token
service, which scopes them to the issuing application and bounds guessing.
"""

import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import generate_code
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttemptType
from ezauth.models.session import Session
from ezauth.models.user import User
from ezauth.ratelimiter import RateLimiter, parse_limits
from ezauth.redirects import app_base_url, is_allowed_redirect
from ezauth.services import audit, mail, passwords, sessions, tokens


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_error"):
        self.message = message
        self.code = code
        super().__init__(message)


async def _enforce_limit(redis, limit_config: str, key: str, app: Application, message: str):
    limiter = RateLimiter(
        redis,
        parse_limits(limit_config),
        user_id=key,
        namespace=str(app.id),
    )
    if not await limiter.check_and_consume():
        raise AuthError(message, code="rate_limited")


async def _validated_redirect(
    db: AsyncSession, app: Application, redirect_url: str | None
) -> str | None:
    """Reject a redirect target the application does not own."""
    if not redirect_url:
        return None
    if not await is_allowed_redirect(db, app, redirect_url):
        raise AuthError(
            "redirect_url is not an allowed domain for this application",
            code="invalid_redirect_url",
        )
    return redirect_url


async def enforce_code_rate_limits(
    redis, *, app: Application, email: str, ip_address: str | None
) -> None:
    """Bound how fast codes can be guessed, per IP and per address."""
    await _enforce_limit(
        redis,
        settings.code_verify_rate_limit_ip,
        f"codeverify:{ip_address or 'unknown'}",
        app,
        "Too many verification attempts",
    )
    await _enforce_limit(
        redis,
        settings.code_verify_rate_limit_email,
        f"codeverify:{email.lower()}",
        app,
        "Too many verification attempts for this email",
    )


def _mail_service(app: Application) -> mail.MailService:
    return mail.MailService(
        sender_name=app.email_from_name or app.name,
        sender_address=app.email_from_address,
    )


async def _send_code_email(app: Application, email: str, code: str, purpose: str) -> None:
    subject = (
        f"Your {app.name} verification code"
        if purpose == "verify"
        else f"Your {app.name} sign-in code"
    )
    summary = "Verification code" if purpose == "verify" else "Sign-in code"
    try:
        await _mail_service(app).send_template(
            "confirmation_code",
            email,
            subject,
            {
                "summary": summary,
                "confirmation_code": code,
                "name": email.split("@")[0],
                "app_name": app.name,
            },
        )
    except Exception:
        logger.exception("Failed to send {} code for app {}", purpose, app.id)


async def _send_link_email(app: Application, email: str, raw_token: str, purpose: str) -> None:
    link = f"{app_base_url(app)}/v1/email/verify?token={raw_token}"
    template = "verification_link" if purpose == "verify" else "magic_link_signin"
    subject = (
        "Please verify your email address" if purpose == "verify" else f"Sign in to {app.name}"
    )
    context = {"summary": subject, "app_name": app.name}
    context["verify_url" if purpose == "verify" else "magic_url"] = link
    try:
        await _mail_service(app).send_template(template, email, subject, context)
    except Exception:
        logger.exception("Failed to send {} link for app {}", purpose, app.id)


async def _issue_credential(
    db: AsyncSession,
    *,
    app: Application,
    user: User,
    email: str,
    attempt_type: AuthAttemptType,
    redirect_url: str | None,
    expire_minutes: int,
    purpose: str,
) -> None:
    """Revoke any live code for this address, then issue and send a new one."""
    await tokens.revoke_pending_attempts(
        db, app_id=app.id, email=email, type=attempt_type
    )

    use_code = getattr(app, "verification_method", "code") == "code"
    code = generate_code(6) if use_code else None

    _attempt, raw_token = await tokens.create_auth_attempt(
        db,
        app_id=app.id,
        type=attempt_type,
        email=email,
        user_id=user.id,
        redirect_url=redirect_url,
        expire_minutes=expire_minutes,
        code=code,
    )

    if use_code:
        await _send_code_email(app, email, code, purpose)
    else:
        await _send_link_email(app, email, raw_token, purpose)


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
    """Register a new user and send a verification credential.

    The response is identical whether or not the address already exists. An
    existing address is sent a sign-in credential rather than a second account.
    """
    await _enforce_limit(
        redis,
        settings.signup_rate_limit_ip,
        ip_address or "unknown",
        app,
        "Too many signup attempts",
    )
    await _enforce_limit(
        redis,
        settings.signup_rate_limit_email,
        email.lower(),
        app,
        "Too many signup attempts for this email",
    )

    redirect_url = await _validated_redirect(db, app, redirect_url)

    existing = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    existing_user = existing.scalars().first()

    if existing_user is not None:
        await _issue_credential(
            db,
            app=app,
            user=existing_user,
            email=email,
            attempt_type=AuthAttemptType.signin,
            redirect_url=redirect_url,
            expire_minutes=settings.magic_link_expire_minutes,
            purpose="signin",
        )
        return {"status": "verification_sent"}

    password_hash = passwords.hash_password(password) if password else None
    user = User(app_id=app.id, email=email, password_hash=password_hash)
    db.add(user)
    await db.flush()

    await _issue_credential(
        db,
        app=app,
        user=user,
        email=email,
        attempt_type=AuthAttemptType.verify_email,
        redirect_url=redirect_url,
        expire_minutes=settings.verification_token_expire_minutes,
        purpose="verify",
    )

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.signup",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info("User {} signed up for app {}", user.id, app.id)
    return {"status": "verification_sent"}


async def consume_email_link_token(
    db: AsyncSession,
    *,
    raw_token: str,
    app: Application,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str, str | None]:
    """Consume a verify_email or signin magic link token and create a session.

    Returns (user, session, access_jwt, raw_refresh_token, redirect_url).
    """
    attempt = await tokens.consume_auth_attempt(
        db, raw_token=raw_token, app_id=app.id, expected_type=AuthAttemptType.verify_email
    )
    if attempt is None:
        attempt = await tokens.consume_auth_attempt(
            db, raw_token=raw_token, app_id=app.id, expected_type=AuthAttemptType.signin
        )
    if attempt is None:
        raise AuthError("Invalid or expired token", code="invalid_token")

    return await _complete_attempt(
        db, attempt=attempt, app=app, ip_address=ip_address, user_agent=user_agent
    )


async def consume_code(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    app: Application,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str, str | None]:
    """Consume a 6-digit verification or sign-in code and create a session."""
    attempt, reason = await tokens.consume_auth_attempt_by_code(
        db,
        email=email,
        code=code,
        app_id=app.id,
        expected_types=[AuthAttemptType.verify_email, AuthAttemptType.signin],
    )
    if attempt is None:
        if reason == tokens.TOO_MANY_ATTEMPTS:
            raise AuthError(
                "Too many incorrect attempts, request a new code",
                code="too_many_attempts",
            )
        raise AuthError("Invalid or expired code", code="invalid_code")

    return await _complete_attempt(
        db, attempt=attempt, app=app, ip_address=ip_address, user_agent=user_agent
    )


async def _complete_attempt(
    db: AsyncSession,
    *,
    attempt,
    app: Application,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[User, Session, str, str, str | None]:
    """Turn a consumed attempt into a session, verifying app ownership."""
    user_result = await db.execute(select(User).where(User.id == attempt.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise AuthError("User not found", code="user_not_found")
    if user.app_id != app.id:
        raise AuthError("Invalid or expired token", code="invalid_token")

    if attempt.type == AuthAttemptType.verify_email or user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        await db.flush()

    session, access_jwt, raw_refresh = await sessions.create_session(db, app=app, user=user)

    event = (
        "user.email_verified"
        if attempt.type == AuthAttemptType.verify_email
        else "user.signin_consumed"
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
    """Send a magic link or code for sign-in, without revealing whether the user exists."""
    await _enforce_limit(
        redis,
        settings.signin_rate_limit_ip,
        ip_address or "unknown",
        app,
        "Too many sign-in attempts",
    )
    await _enforce_limit(
        redis,
        settings.signin_rate_limit_email,
        email.lower(),
        app,
        "Too many sign-in attempts for this email",
    )

    redirect_url = await _validated_redirect(db, app, redirect_url)

    user_result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    user = user_result.scalars().first()
    if user is None:
        return {"status": "magic_link_sent"}

    await _issue_credential(
        db,
        app=app,
        user=user,
        email=email,
        attempt_type=AuthAttemptType.signin,
        redirect_url=redirect_url,
        expire_minutes=settings.magic_link_expire_minutes,
        purpose="signin",
    )

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
    """Sign in with email and password.

    Returns (user, session, access_jwt, raw_refresh_token).
    """
    await _enforce_limit(
        redis,
        settings.signin_rate_limit_ip,
        ip_address or "unknown",
        app,
        "Too many sign-in attempts",
    )
    await _enforce_limit(
        redis,
        settings.signin_rate_limit_email,
        f"pw:{email.lower()}",
        app,
        "Too many sign-in attempts for this email",
    )

    user_result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == email.lower())
    )
    user = user_result.scalars().first()

    if user is None or user.password_hash is None:
        passwords.dummy_verify(password)
        raise AuthError("Invalid email or password", code="invalid_credentials")

    if not passwords.verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password", code="invalid_credentials")

    if user.email_verified_at is None:
        raise AuthError(
            "Verify your email address before signing in",
            code="email_not_verified",
        )

    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
        await db.flush()

    session, access_jwt, raw_refresh = await sessions.create_session(db, app=app, user=user)

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


async def set_password(
    db: AsyncSession,
    *,
    app: Application,
    user: User,
    new_password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Set a user's password and revoke their other sessions."""
    if len(new_password) < 8:
        raise AuthError("Password must be at least 8 characters", code="weak_password")

    user.password_hash = passwords.hash_password(new_password)
    await db.flush()

    await sessions.revoke_user_sessions(db, user_id=user.id, app_id=app.id)

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.password_set",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


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
