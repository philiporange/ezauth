from pydantic import BaseModel


class Argon2Params(BaseModel):
    time_cost: int
    memory_cost: int
    parallelism: int
    hash_len: int


class ChallengeResponse(BaseModel):
    challenge: str
    difficulty: int
    algorithm: str = "argon2id"
    params: Argon2Params
    expires_in: int


class HashcashProof(BaseModel):
    challenge: str
    nonce: str
