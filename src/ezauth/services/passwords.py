"""Password hashing with Argon2id.

Wraps argon2-cffi with the library's recommended parameters and exposes a
rehash check so stored hashes are upgraded as the parameters harden. Sign-in
paths call `dummy_verify` when no user or no password hash is found, so a
request for an unknown address costs the same wall-clock time as one for a
known address and the endpoint does not leak account existence through timing.
"""

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

# Precomputed hash of a value no user can hold, used to equalise timing.
_DUMMY_HASH = _hasher.hash("ezauth-timing-equalisation-placeholder")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hash: str) -> bool:
    try:
        return _hasher.verify(hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def dummy_verify(password: str) -> None:
    """Burn an Argon2 verification so misses and hits take similar time."""
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except Exception:
        pass


def needs_rehash(hash: str) -> bool:
    return _hasher.check_needs_rehash(hash)
