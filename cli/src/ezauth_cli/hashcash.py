import os
import time

import argon2.low_level
from rich.live import Live
from rich.text import Text


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


def solve_challenge(
    challenge: str,
    difficulty: int,
    time_cost: int,
    memory_cost: int,
    parallelism: int,
    hash_len: int,
) -> tuple[str, int]:
    salt = bytes.fromhex(challenge)
    attempts = 0
    start = time.monotonic()

    with Live(Text("Solving proof of work..."), refresh_per_second=4) as live:
        while True:
            nonce = os.urandom(16).hex()
            secret = f"{challenge}:{nonce}".encode()

            hash_output = argon2.low_level.hash_secret_raw(
                secret=secret,
                salt=salt,
                time_cost=time_cost,
                memory_cost=memory_cost,
                parallelism=parallelism,
                hash_len=hash_len,
                type=argon2.low_level.Type.ID,
            )

            attempts += 1
            elapsed = time.monotonic() - start
            live.update(
                Text(f"Solving proof of work... {attempts} attempts, {elapsed:.1f}s elapsed")
            )

            if _check_leading_zero_bits(hash_output, difficulty):
                return nonce, attempts
