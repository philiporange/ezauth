"""Tests for the authentication security properties.

These cover the invariants that are expensive to get wrong: redirect targets
must belong to the application, codes must be guess-bounded, credentials must
be scoped to the application that issued them, revocation must take effect
before the access token expires, and rotation must not invalidate tokens that
were signed moments earlier.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from ezauth.config import settings
from ezauth.models.application import Application, Environment
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType
from ezauth.models.user import User
from ezauth.redirects import is_allowed_redirect
from ezauth.services import auth as auth_service
from ezauth.services import keys as key_service
from ezauth.services import sessions as session_service
from ezauth.services import tokens as token_service

# --- Redirect validation ---


@pytest.mark.parametrize(
    "url,allowed",
    [
        ("/dashboard", True),
        ("/", True),
        ("https://localhost/next", True),
        ("https://evil.com", False),
        ("//evil.com/path", False),
        ("javascript:alert(1)", False),
        ("https://localhost.evil.com", False),
        ("", False),
        (None, False),
    ],
)
async def test_redirect_targets_restricted_to_app_domains(db, app, url, allowed):
    assert await is_allowed_redirect(db, app, url) is allowed


async def test_signup_rejects_foreign_redirect(db, redis, app):
    with pytest.raises(auth_service.AuthError) as exc:
        await auth_service.signup(
            db, redis, app=app, email="redirect@example.com",
            redirect_url="https://evil.com/steal",
        )
    assert exc.value.code == "invalid_redirect_url"


# --- Code guessing limits ---


async def _pending_code_attempt(db, app, email, code):
    await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email=email,
        expire_minutes=15,
        code=code,
    )


async def test_code_is_not_stored_in_plaintext(db, app):
    await _pending_code_attempt(db, app, "hash@example.com", "123456")
    result = await db.execute(
        select(AuthAttempt).where(AuthAttempt.email == "hash@example.com")
    )
    attempt = result.scalars().first()
    assert "123456" not in str(attempt.metadata_json)
    assert attempt.metadata_json["code_hash"]


async def test_wrong_codes_burn_the_attempt(db, app):
    await _pending_code_attempt(db, app, "burn@example.com", "123456")

    for _ in range(settings.max_code_attempts - 1):
        attempt, reason = await token_service.consume_auth_attempt_by_code(
            db, email="burn@example.com", code="000000", app_id=app.id
        )
        assert attempt is None
        assert reason == token_service.INVALID_CODE

    attempt, reason = await token_service.consume_auth_attempt_by_code(
        db, email="burn@example.com", code="000000", app_id=app.id
    )
    assert reason == token_service.TOO_MANY_ATTEMPTS

    # The real code no longer works once the attempt is burned.
    attempt, reason = await token_service.consume_auth_attempt_by_code(
        db, email="burn@example.com", code="123456", app_id=app.id
    )
    assert attempt is None


async def test_correct_code_is_accepted_and_single_use(db, app):
    await _pending_code_attempt(db, app, "once@example.com", "424242")

    attempt, reason = await token_service.consume_auth_attempt_by_code(
        db, email="once@example.com", code="424242", app_id=app.id
    )
    assert attempt is not None and reason is None

    again, _ = await token_service.consume_auth_attempt_by_code(
        db, email="once@example.com", code="424242", app_id=app.id
    )
    assert again is None


async def test_issuing_a_code_revokes_earlier_ones(db, app):
    await _pending_code_attempt(db, app, "stack@example.com", "111111")
    await token_service.revoke_pending_attempts(
        db, app_id=app.id, email="stack@example.com", type=AuthAttemptType.signin
    )
    await _pending_code_attempt(db, app, "stack@example.com", "222222")

    old, _ = await token_service.consume_auth_attempt_by_code(
        db, email="stack@example.com", code="111111", app_id=app.id
    )
    assert old is None

    new, _ = await token_service.consume_auth_attempt_by_code(
        db, email="stack@example.com", code="222222", app_id=app.id
    )
    assert new is not None


# --- Application scoping ---


@pytest.fixture
async def other_app(db, tenant):
    private_pem, kid, _jwk = key_service.generate_jwk_pair()
    other = Application(
        tenant_id=tenant.id,
        name="Other App",
        environment=Environment.dev,
        publishable_key=key_service.generate_publishable_key("dev"),
        secret_key=key_service.generate_secret_key("dev"),
        primary_domain="other.example.com",
        jwk_private_pem=private_pem,
        jwk_kid=kid,
    )
    db.add(other)
    await db.flush()
    return other


async def test_link_token_cannot_be_redeemed_against_another_app(db, app, other_app):
    _attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email="scope@example.com",
        expire_minutes=15,
    )

    wrong = await token_service.consume_auth_attempt(
        db, raw_token=raw_token, app_id=other_app.id
    )
    assert wrong is None

    right = await token_service.consume_auth_attempt(
        db, raw_token=raw_token, app_id=app.id
    )
    assert right is not None


async def test_code_cannot_be_redeemed_against_another_app(db, app, other_app):
    await _pending_code_attempt(db, app, "crossapp@example.com", "999999")

    attempt, _ = await token_service.consume_auth_attempt_by_code(
        db, email="crossapp@example.com", code="999999", app_id=other_app.id
    )
    assert attempt is None


# --- Session revocation ---


async def test_revoked_session_is_no_longer_active(db, app, user):
    session, _jwt, _refresh = await session_service.create_session(db, app=app, user=user)
    assert await session_service.is_session_active(
        db, session_id=session.id, app_id=app.id
    )

    await session_service.revoke_session(db, session_id=session.id)
    assert not await session_service.is_session_active(
        db, session_id=session.id, app_id=app.id
    )


async def test_expired_session_is_not_active(db, app, user):
    session, _jwt, _refresh = await session_service.create_session(db, app=app, user=user)
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.flush()

    assert not await session_service.is_session_active(
        db, session_id=session.id, app_id=app.id
    )


async def test_setting_a_password_revokes_other_sessions(db, app, user):
    first, _jwt, _refresh = await session_service.create_session(db, app=app, user=user)
    second, _jwt2, _refresh2 = await session_service.create_session(db, app=app, user=user)

    await auth_service.set_password(db, app=app, user=user, new_password="a-new-password")

    for session in (first, second):
        assert not await session_service.is_session_active(
            db, session_id=session.id, app_id=app.id
        )


async def test_backend_token_lifetime_is_clamped(db, app, user):
    signing = await key_service.active_key(db, app)
    token = session_service.mint_jwt(
        app=app,
        user=user,
        session_id=uuid.uuid4(),
        signing_kid=signing.kid,
        signing_pem=signing.private_pem,
        lifetime_seconds=999_999_999,
    )

    from jose import jwt as jose_jwt

    claims = jose_jwt.get_unverified_claims(token)
    lifetime = claims["exp"] - claims["iat"]
    assert lifetime <= settings.max_signin_token_lifetime_seconds


# --- Account enumeration and unverified accounts ---


async def test_signup_for_existing_address_looks_identical(db, redis, app, user):
    fresh = await auth_service.signup(
        db, redis, app=app, email="brand-new@example.com"
    )
    existing = await auth_service.signup(db, redis, app=app, email=user.email)

    assert fresh == existing == {"status": "verification_sent"}

    # No second account was created for the existing address.
    result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == user.email.lower())
    )
    assert len(result.scalars().all()) == 1


async def test_password_signin_requires_a_verified_email(db, redis, app):
    from ezauth.services.passwords import hash_password

    unverified = User(
        app_id=app.id,
        email="unverified@example.com",
        password_hash=hash_password("correct-horse-battery"),
    )
    db.add(unverified)
    await db.flush()

    with pytest.raises(auth_service.AuthError) as exc:
        await auth_service.signin_password(
            db, redis, app=app,
            email="unverified@example.com",
            password="correct-horse-battery",
        )
    assert exc.value.code == "email_not_verified"


async def test_signin_for_unknown_address_reports_success(db, redis, app):
    result = await auth_service.signin_magic_link(
        db, redis, app=app, email="nobody@example.com"
    )
    assert result == {"status": "magic_link_sent"}


# --- Signing key rotation ---


async def test_rotation_keeps_earlier_tokens_verifiable(db, app, user):
    from ezauth.dependencies import decode_with_app_keys

    _session, before_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )

    await key_service.rotate_key(db, app)

    _session2, after_jwt, _refresh2 = await session_service.create_session(
        db, app=app, user=user
    )

    assert await decode_with_app_keys(db, app, before_jwt, audience=str(app.id))
    assert await decode_with_app_keys(db, app, after_jwt, audience=str(app.id))

    jwks = await session_service.build_jwks(db, app)
    assert len(jwks["keys"]) == 2


async def test_dropping_retired_keys_invalidates_their_tokens(db, app, user):
    from ezauth.dependencies import decode_with_app_keys

    _session, before_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )
    await key_service.rotate_key(db, app)
    await key_service.drop_retired_keys(db, app)

    assert await decode_with_app_keys(db, app, before_jwt, audience=str(app.id)) is None

    jwks = await session_service.build_jwks(db, app)
    assert len(jwks["keys"]) == 1


async def test_rotation_marks_exactly_one_key_active(db, app):
    await key_service.rotate_key(db, app)
    await key_service.rotate_key(db, app)

    all_keys = await key_service.verification_keys(db, app)
    assert len(all_keys) == 3
    assert sum(1 for k in all_keys if k.is_active) == 1


# --- Attempt hygiene ---


async def test_expired_attempts_are_not_consumable(db, app):
    attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email="expired@example.com",
        expire_minutes=15,
    )
    attempt.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.flush()

    assert (
        await token_service.consume_auth_attempt(db, raw_token=raw_token, app_id=app.id)
    ) is None


async def test_revoked_attempts_are_not_consumable(db, app):
    _attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email="revoked@example.com",
        expire_minutes=15,
    )
    await token_service.revoke_pending_attempts(
        db, app_id=app.id, email="revoked@example.com"
    )

    assert (
        await token_service.consume_auth_attempt(db, raw_token=raw_token, app_id=app.id)
    ) is None

    result = await db.execute(
        select(AuthAttempt).where(AuthAttempt.email == "revoked@example.com")
    )
    assert result.scalars().first().status == AuthAttemptStatus.revoked
