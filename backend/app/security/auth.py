"""JWT-based authentication (Phase 8, docs/api.md "Auth & rate limiting",
docs/database-schema.md `users` table).

Password hashing uses `bcrypt` directly (not passlib, which has known
version-detection breakage against newer bcrypt releases) -- hashed only,
never logged or persisted in cleartext (brief §27). JWTs are signed with
`Settings.jwt_secret_key` (env-only, never hardcoded) using `PyJWT`.

`get_current_user` is the FastAPI dependency required on every
`/api/v1/research*` route except health checks (see `app/api/research.py`,
`app/main.py`). It is genuinely functional: it decodes and verifies the
Bearer token's signature/expiry, then loads the referenced user row from the
database -- a request with no token, an expired token, a tampered token, or a
token for a deleted user is rejected, never defaulted to a fake user.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

Role = Literal["user", "admin"]

_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """Narrowed, validated view of the authenticated caller -- what routes
    and authorization checks actually need, not the full ORM row."""

    id: str
    email: str
    role: Role


class TokenPayload(BaseModel):
    sub: str
    email: str
    role: Role
    exp: datetime
    iat: datetime


def hash_password(password: str) -> str:
    """bcrypt truncates at 72 bytes; encode explicitly so a very long
    password fails loudly instead of being silently truncated by a library
    default a caller might not know about."""
    if not password:
        raise ValueError("password must not be empty")
    encoded = password.encode("utf-8")[:72]
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash (e.g. corrupted row) must fail closed, not raise
        # into a 500 that could leak whether the row exists.
        return False


def create_access_token(
    *, user_id: str, email: str, role: Role, secret_key: str, algorithm: str, expiry_minutes: int
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=expiry_minutes),
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


class AuthError(HTTPException):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": code, "message": message}},
            headers={"WWW-Authenticate": "Bearer"},
        )


def decode_access_token(token: str, *, secret_key: str, algorithm: str) -> TokenPayload:
    try:
        raw = jwt.decode(token, secret_key, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("TOKEN_EXPIRED", "access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("TOKEN_INVALID", "access token is invalid") from exc
    try:
        return TokenPayload.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 - malformed payload, not a crash
        raise AuthError("TOKEN_INVALID", "access token payload is malformed") from exc


def _get_settings(request: Request):
    # Deferred import to avoid a module-level cycle with app.config.settings
    # importing back into this package (it doesn't today, but keeps the
    # dependency direction obviously one-way).
    from app.config.settings import get_settings

    return get_settings()


def _get_session_repository(request: Request):
    return request.app.state.session_repository


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> CurrentUser:
    """Required dependency on every protected route. Not a stub: validates
    the token's signature and expiry, then confirms the user still exists."""
    if credentials is None or not credentials.credentials:
        raise AuthError("AUTH_REQUIRED", "missing Authorization: Bearer <token> header")

    settings = _get_settings(request)
    payload = decode_access_token(
        credentials.credentials,
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    repo = _get_session_repository(request)
    try:
        user_uuid = UUID(payload.sub)
    except ValueError as exc:
        raise AuthError("TOKEN_INVALID", "access token subject is not a valid user id") from exc

    user = await repo.get_user_by_id(user_uuid)
    if user is None:
        raise AuthError("USER_NOT_FOUND", "the user this token was issued for no longer exists")

    return CurrentUser(id=str(user.id), email=user.email, role=user.role)  # type: ignore[arg-type]


def require_admin(current_user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """Extra dependency for admin-only routes (none exist yet in Phase 8 but
    kept available for authorization checks that need it, e.g. a future
    admin session-management endpoint)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="ADMIN_REQUIRED")
    return current_user
