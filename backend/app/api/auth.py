"""Auth endpoints (Phase 8, docs/api.md). Thin routers only -- hashing/token
logic lives in `app/security/auth.py`, persistence in `SessionRepository`."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_session_repository, get_settings_dep
from app.config.settings import Settings
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.security.auth import create_access_token, hash_password, verify_password
from app.services.session_repository import SessionRepository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
) -> UserResponse:
    existing = await repo.get_user_by_email(payload.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED")

    hashed = hash_password(payload.password)
    try:
        user = await repo.create_user(email=payload.email, hashed_password=hashed, role="user")
    except IntegrityError as exc:  # race: two concurrent registers for the same email
        raise HTTPException(status_code=409, detail="EMAIL_ALREADY_REGISTERED") from exc

    return UserResponse(id=user.id, email=user.email, role=user.role, created_at=user.created_at)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    repo: Annotated[SessionRepository, Depends(get_session_repository)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> TokenResponse:
    user = await repo.get_user_by_email(payload.email)
    # Same generic error whether the email doesn't exist or the password is
    # wrong -- never let login responses reveal which emails are registered.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")

    token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expiry_minutes=settings.jwt_expiry_minutes,
    )
    return TokenResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_expiry_minutes,
        user=UserResponse(id=user.id, email=user.email, role=user.role, created_at=user.created_at),
    )
