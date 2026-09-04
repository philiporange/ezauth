"""Tests for minting session tokens and publishing verification keys."""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jose import jwt

from ezauth.services import keys as key_service
from ezauth.services.sessions import build_jwks, mint_jwt


async def test_mint_jwt_and_build_jwks(db, app, user):
    signing = await key_service.active_key(db, app)
    token = mint_jwt(
        app=app,
        user=user,
        session_id=user.id,
        signing_kid=signing.kid,
        signing_pem=signing.private_pem,
    )
    assert isinstance(token, str)
    assert len(token) > 50

    jwks = await build_jwks(db, app)
    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kid"] == signing.kid

    private_key = load_pem_private_key(signing.private_pem.encode(), password=None)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    claims = jwt.decode(token, public_pem, algorithms=["RS256"], audience=str(app.id))
    assert claims["sub"] == str(user.id)
    assert claims["email"] == user.email
    assert claims["email_verified"] is True


async def test_jwt_header_names_the_signing_key(db, app, user):
    signing = await key_service.active_key(db, app)
    token = mint_jwt(
        app=app,
        user=user,
        session_id=user.id,
        signing_kid=signing.kid,
        signing_pem=signing.private_pem,
    )
    assert jwt.get_unverified_header(token)["kid"] == signing.kid
