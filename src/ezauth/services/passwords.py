from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hash: str) -> bool:
    try:
        return _hasher.verify(hash, password)
    except VerifyMismatchError:
        return False


def needs_rehash(hash: str) -> bool:
    return _hasher.check_needs_rehash(hash)
