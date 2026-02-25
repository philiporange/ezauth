from jose import jwt, JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ezauth_sdk.exceptions import AuthenticationError
from ezauth_sdk.jwks import JWKSClient
from ezauth_sdk.types import AuthState


async def authenticate_request(
    request: Request,
    jwks_client: JWKSClient,
    *,
    cookie_name: str = "__session",
    audience: str | None = None,
) -> AuthState:
    """Authenticate a request by verifying the JWT from cookie or Authorization header.

    Returns AuthState with user_id, session_id, and claims.
    """
    token = request.cookies.get(cookie_name)

    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise AuthenticationError("No authentication token found")

    # Decode header to get kid
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise AuthenticationError("Invalid token header")

    kid = unverified_header.get("kid")
    if not kid:
        raise AuthenticationError("Token missing kid header")

    # Fetch the signing key
    try:
        jwk = await jwks_client.get_signing_key(kid)
    except ValueError as e:
        raise AuthenticationError(str(e))

    # Verify the token
    try:
        claims = jwt.decode(
            token,
            jwk,
            algorithms=["RS256"],
            audience=audience,
        )
    except JWTError as e:
        raise AuthenticationError(f"Token verification failed: {e}")

    return AuthState(
        user_id=claims.get("sub", ""),
        session_id=claims.get("sid", ""),
        claims=claims,
    )


class EZAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that authenticates requests via EZAuth JWT."""

    def __init__(
        self,
        app,
        *,
        auth_domain: str,
        cookie_name: str = "__session",
        audience: str | None = None,
        public_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.jwks_client = JWKSClient(auth_domain)
        self.cookie_name = cookie_name
        self.audience = audience
        self.public_paths = set(public_paths or [])

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.public_paths:
            return await call_next(request)

        try:
            auth_state = await authenticate_request(
                request,
                self.jwks_client,
                cookie_name=self.cookie_name,
                audience=self.audience,
            )
            request.state.auth = auth_state
        except AuthenticationError as e:
            return JSONResponse(
                status_code=401,
                content={"detail": e.message},
            )

        return await call_next(request)
