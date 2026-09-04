"""Application credentials: publishable keys, secret keys and RSA signing keys.

Each application signs its tokens with an RSA key stored in `application_keys`.
Exactly one key is active and signs new tokens; rotating adds a new active key
and retires the previous one rather than replacing it, because tokens signed
seconds before a rotation must keep verifying until they expire. Retired keys
stay published in JWKS until they are dropped, which is the operation to run
once the longest-lived token signed by a compromised key has expired.

Applications created before signing keys were tracked separately still carry
their key on the application row; `ensure_keys` migrates such a row into the
table on first use, so both shapes resolve through one code path.
"""

import base64
import secrets
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.application import Application
from ezauth.models.application_key import ApplicationKey


def generate_publishable_key(environment: str = "dev") -> str:
    prefix = "pk_live_" if environment == "prod" else "pk_test_"
    return prefix + secrets.token_urlsafe(24)


def generate_secret_key(environment: str = "dev") -> str:
    prefix = "sk_live_" if environment == "prod" else "sk_test_"
    return prefix + secrets.token_urlsafe(48)


def _int_to_base64url(n: int) -> str:
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, byteorder="big")).rstrip(b"=").decode()


def generate_jwk_pair() -> tuple[str, str, dict]:
    """Generate an RSA 2048 key pair.

    Returns (private_pem, kid, jwk_public_dict).
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    kid = secrets.token_urlsafe(16)
    public_numbers = private_key.public_key().public_numbers()

    jwk_public = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n),
        "e": _int_to_base64url(public_numbers.e),
    }

    return private_pem, kid, jwk_public


def public_jwk(kid: str, private_pem: str) -> dict:
    """Build the public JWK for a stored private key."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    public_numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n),
        "e": _int_to_base64url(public_numbers.e),
    }


async def ensure_keys(db: AsyncSession, app: Application) -> list[ApplicationKey]:
    """Return an application's keys, adopting its inline key if it has none."""
    result = await db.execute(
        select(ApplicationKey)
        .where(ApplicationKey.app_id == app.id)
        .order_by(ApplicationKey.is_active.desc(), ApplicationKey.created_at.desc())
    )
    keys = list(result.scalars().all())
    if keys:
        return keys

    adopted = ApplicationKey(
        app_id=app.id,
        kid=app.jwk_kid,
        private_pem=app.jwk_private_pem,
        is_active=True,
    )
    db.add(adopted)
    await db.flush()
    return [adopted]


async def active_key(db: AsyncSession, app: Application) -> ApplicationKey:
    """The key new tokens are signed with."""
    keys = await ensure_keys(db, app)
    for key in keys:
        if key.is_active:
            return key
    return keys[0]


async def verification_keys(db: AsyncSession, app: Application) -> list[ApplicationKey]:
    """Every key whose signatures should still be accepted."""
    return await ensure_keys(db, app)


async def rotate_key(db: AsyncSession, app: Application) -> ApplicationKey:
    """Add a new active signing key and retire the previous one."""
    keys = await ensure_keys(db, app)
    now = datetime.now(timezone.utc)

    for key in keys:
        if key.is_active:
            key.is_active = False
            key.retired_at = now

    private_pem, kid, _jwk = generate_jwk_pair()
    new_key = ApplicationKey(
        app_id=app.id, kid=kid, private_pem=private_pem, is_active=True
    )
    db.add(new_key)

    app.jwk_private_pem = private_pem
    app.jwk_kid = kid

    await db.flush()
    return new_key


async def drop_retired_keys(db: AsyncSession, app: Application) -> int:
    """Delete retired keys, so a compromised key stops verifying entirely."""
    keys = await ensure_keys(db, app)
    removed = 0
    for key in keys:
        if not key.is_active:
            await db.delete(key)
            removed += 1
    await db.flush()
    return removed
