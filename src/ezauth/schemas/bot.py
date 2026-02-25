from pydantic import BaseModel


class BotSignupRequest(BaseModel):
    challenge_id: str
    public_key: str  # base64-encoded Ed25519 public key


class BotSignupResponse(BaseModel):
    bot_id: str
    public_key: str


class BotAuthRequest(BaseModel):
    bot_id: str
    timestamp: int
    signature: str  # base64-encoded Ed25519 signature
