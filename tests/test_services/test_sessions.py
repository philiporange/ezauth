import pytest

from ezauth.services.sessions import build_jwks, mint_jwt


@pytest.mark.skipif(True, reason="Requires test database")
async def test_mint_jwt_and_build_jwks(app, user):
    token = mint_jwt(app=app, user=user, session_id=user.id)
    assert isinstance(token, str)
    assert len(token) > 50  # JWT format

    jwks = build_jwks(app)
    assert "keys" in jwks
    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kid"] == app.jwk_kid

    # Verify the token with the public key
    from jose import jwt

    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives import serialization

    private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    claims = jwt.decode(token, public_pem, algorithms=["RS256"], audience=str(app.id))
    assert claims["sub"] == str(user.id)
    assert claims["email"] == user.email
