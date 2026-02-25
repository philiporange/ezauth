import base64
import time
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ezauth.services.auth import AuthError
from ezauth.services.bots import _validate_public_key, auth_bot, signup_bot


def _generate_keypair():
    """Generate an Ed25519 keypair, return (private_key, public_key_b64)."""
    private = Ed25519PrivateKey.generate()
    pub_bytes = private.public_key().public_bytes_raw()
    return private, base64.b64encode(pub_bytes).decode()


def _sign_message(private_key, message: str) -> str:
    sig = private_key.sign(message.encode())
    return base64.b64encode(sig).decode()


class TestValidatePublicKey:
    def test_valid_key(self):
        _, pub_b64 = _generate_keypair()
        raw = _validate_public_key(pub_b64)
        assert len(raw) == 32

    def test_invalid_base64(self):
        with pytest.raises(AuthError, match="Invalid public key encoding"):
            _validate_public_key("not-valid-base64!!!")

    def test_wrong_length(self):
        short = base64.b64encode(b"\x00" * 16).decode()
        with pytest.raises(AuthError, match="expected 32 bytes"):
            _validate_public_key(short)


class TestBotSignup:
    @pytest.mark.asyncio
    async def test_signup_success(self, db, redis, app):
        _, pub_b64 = _generate_keypair()
        challenge_id = "test-challenge-123"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "CONFIRMED", "challenge_id": challenge_id}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await signup_bot(
                db, redis, app=app,
                challenge_id=challenge_id,
                public_key_b64=pub_b64,
            )

        assert "bot_id" in result
        assert result["public_key"] == pub_b64

    @pytest.mark.asyncio
    async def test_signup_challenge_not_confirmed(self, db, redis, app):
        _, pub_b64 = _generate_keypair()

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "PENDING"}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            with pytest.raises(AuthError, match="not confirmed"):
                await signup_bot(
                    db, redis, app=app,
                    challenge_id="pending-challenge",
                    public_key_b64=pub_b64,
                )

    @pytest.mark.asyncio
    async def test_signup_challenge_reuse(self, db, redis, app):
        _, pub_b64 = _generate_keypair()
        _, pub_b64_2 = _generate_keypair()
        challenge_id = "reuse-challenge-456"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "CONFIRMED", "challenge_id": challenge_id}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            await signup_bot(
                db, redis, app=app,
                challenge_id=challenge_id,
                public_key_b64=pub_b64,
            )

            with pytest.raises(AuthError, match="already used"):
                await signup_bot(
                    db, redis, app=app,
                    challenge_id=challenge_id,
                    public_key_b64=pub_b64_2,
                )


class TestBotAuth:
    @pytest.mark.asyncio
    async def test_auth_success(self, db, redis, app):
        private, pub_b64 = _generate_keypair()
        challenge_id = "auth-test-challenge"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "CONFIRMED"}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await signup_bot(
                db, redis, app=app,
                challenge_id=challenge_id,
                public_key_b64=pub_b64,
            )

        bot_id = result["bot_id"]
        ts = int(time.time())
        message = f"ezauth:bot_auth:{app.id}:{bot_id}:{ts}"
        signature = _sign_message(private, message)

        user, session, jwt_token, refresh = await auth_bot(
            db, redis, app=app,
            bot_id=bot_id,
            timestamp=ts,
            signature_b64=signature,
        )

        assert str(user.id) == bot_id
        assert user.is_bot is True
        assert jwt_token
        assert refresh

    @pytest.mark.asyncio
    async def test_auth_wrong_key(self, db, redis, app):
        private, pub_b64 = _generate_keypair()
        wrong_private, _ = _generate_keypair()
        challenge_id = "wrong-key-challenge"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "CONFIRMED"}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await signup_bot(
                db, redis, app=app,
                challenge_id=challenge_id,
                public_key_b64=pub_b64,
            )

        bot_id = result["bot_id"]
        ts = int(time.time())
        message = f"ezauth:bot_auth:{app.id}:{bot_id}:{ts}"
        bad_sig = _sign_message(wrong_private, message)

        with pytest.raises(AuthError, match="Invalid signature"):
            await auth_bot(
                db, redis, app=app,
                bot_id=bot_id,
                timestamp=ts,
                signature_b64=bad_sig,
            )

    @pytest.mark.asyncio
    async def test_auth_expired_timestamp(self, db, redis, app):
        private, pub_b64 = _generate_keypair()
        challenge_id = "expired-ts-challenge"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "CONFIRMED"}

        with patch("ezauth.services.bots.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await signup_bot(
                db, redis, app=app,
                challenge_id=challenge_id,
                public_key_b64=pub_b64,
            )

        bot_id = result["bot_id"]
        old_ts = int(time.time()) - 600  # 10 minutes ago
        message = f"ezauth:bot_auth:{app.id}:{bot_id}:{old_ts}"
        signature = _sign_message(private, message)

        with pytest.raises(AuthError, match="Timestamp out of range"):
            await auth_bot(
                db, redis, app=app,
                bot_id=bot_id,
                timestamp=old_ts,
                signature_b64=signature,
            )
