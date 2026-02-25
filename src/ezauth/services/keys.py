import base64
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generate_publishable_key(environment: str = "dev") -> str:
    prefix = "pk_live_" if environment == "prod" else "pk_test_"
    return prefix + secrets.token_urlsafe(24)


def generate_secret_key(environment: str = "dev") -> str:
    prefix = "sk_live_" if environment == "prod" else "sk_test_"
    return prefix + secrets.token_urlsafe(48)


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

    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    def _int_to_base64url(n: int) -> str:
        length = (n.bit_length() + 7) // 8
        data = n.to_bytes(length, byteorder="big")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    jwk_public = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n),
        "e": _int_to_base64url(public_numbers.e),
    }

    return private_pem, kid, jwk_public
