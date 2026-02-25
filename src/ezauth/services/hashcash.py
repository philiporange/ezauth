import os

import argon2.low_level

from ezauth.config import settings


class HashcashError(Exception):
    def __init__(self, message: str, code: str = "hashcash_error"):
        self.message = message
        self.code = code
        super().__init__(message)


def _compute_argon2(challenge: str, nonce: str) -> bytes:
    secret = f"{challenge}:{nonce}".encode()
    salt = bytes.fromhex(challenge)
    return argon2.low_level.hash_secret_raw(
        secret=secret,
        salt=salt,
        time_cost=settings.hashcash_time_cost,
        memory_cost=settings.hashcash_memory_cost,
        parallelism=settings.hashcash_parallelism,
        hash_len=settings.hashcash_hash_len,
        type=argon2.low_level.Type.ID,
    )


def _check_leading_zero_bits(data: bytes, difficulty: int) -> bool:
    full_bytes = difficulty // 8
    remaining_bits = difficulty % 8

    if len(data) < full_bytes + (1 if remaining_bits else 0):
        return False

    for i in range(full_bytes):
        if data[i] != 0:
            return False

    if remaining_bits:
        mask = 0xFF << (8 - remaining_bits)
        if data[full_bytes] & mask != 0:
            return False

    return True


async def create_challenge(redis) -> dict:
    challenge = os.urandom(16).hex()
    key = f"hashcash:{challenge}"
    await redis.set(key, "1", ex=settings.hashcash_challenge_ttl)
    return {
        "challenge": challenge,
        "difficulty": settings.hashcash_difficulty,
        "algorithm": "argon2id",
        "params": {
            "time_cost": settings.hashcash_time_cost,
            "memory_cost": settings.hashcash_memory_cost,
            "parallelism": settings.hashcash_parallelism,
            "hash_len": settings.hashcash_hash_len,
        },
        "expires_in": settings.hashcash_challenge_ttl,
    }


async def verify_proof(redis, challenge: str, nonce: str) -> None:
    key = f"hashcash:{challenge}"

    # Atomic get-and-delete
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = await pipe.execute()

    if results[0] is None:
        raise HashcashError("Invalid or expired challenge", code="challenge_expired")

    hash_output = _compute_argon2(challenge, nonce)

    if not _check_leading_zero_bits(hash_output, settings.hashcash_difficulty):
        raise HashcashError("Proof of work verification failed", code="invalid_proof")
