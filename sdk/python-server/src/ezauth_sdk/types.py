from dataclasses import dataclass


@dataclass
class AuthState:
    user_id: str
    session_id: str
    claims: dict
    authenticated: bool = True
