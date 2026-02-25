from pydantic import BaseModel, EmailStr

from ezauth.schemas.hashcash import HashcashProof


class SignupRequest(BaseModel):
    email: EmailStr
    password: str | None = None
    redirect_url: str | None = None
    hashcash: HashcashProof | None = None


class SigninRequest(BaseModel):
    email: EmailStr
    password: str | None = None
    redirect_url: str | None = None
    strategy: str = "magic_link"  # "magic_link" or "password"


class AuthResponse(BaseModel):
    status: str
    user_id: str | None = None


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    user_id: str
    session_id: str


class MeResponse(BaseModel):
    user_id: str
    email: str | None = None
    email_verified: bool
    is_bot: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class SignInTokenRequest(BaseModel):
    user_id: str
    expires_in_seconds: int = 300
