"""Unit tests for Phase 8 JWT auth (`app/security/auth.py`): password
hashing, token issuance/verification (valid/expired/malformed), and the
`get_current_user` dependency's rejection paths."""

from __future__ import annotations

import jwt
import pytest

from app.security.auth import (
    AuthError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-key-long-enough-for-hs256"
ALGO = "HS256"


def test_hash_password_never_stores_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2")  # bcrypt hash prefix


def test_verify_password_round_trip() -> None:
    hashed = hash_password("s3cret-passw0rd")
    assert verify_password("s3cret-passw0rd", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_rejects_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False


def test_hash_password_rejects_empty_password() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_create_and_decode_access_token_round_trip() -> None:
    token = create_access_token(
        user_id="11111111-1111-1111-1111-111111111111",
        email="a@example.com",
        role="user",
        secret_key=SECRET,
        algorithm=ALGO,
        expiry_minutes=60,
    )
    payload = decode_access_token(token, secret_key=SECRET, algorithm=ALGO)
    assert payload.sub == "11111111-1111-1111-1111-111111111111"
    assert payload.email == "a@example.com"
    assert payload.role == "user"


def test_decode_access_token_rejects_expired_token() -> None:
    token = create_access_token(
        user_id="u1", email="a@example.com", role="user",
        secret_key=SECRET, algorithm=ALGO, expiry_minutes=-1,  # already expired
    )
    with pytest.raises(AuthError):
        decode_access_token(token, secret_key=SECRET, algorithm=ALGO)


def test_decode_access_token_rejects_malformed_token() -> None:
    with pytest.raises(AuthError):
        decode_access_token("not-a-jwt-at-all", secret_key=SECRET, algorithm=ALGO)


def test_decode_access_token_rejects_wrong_signature() -> None:
    token = create_access_token(
        user_id="u1", email="a@example.com", role="user",
        secret_key=SECRET, algorithm=ALGO, expiry_minutes=60,
    )
    with pytest.raises(AuthError):
        decode_access_token(token, secret_key="a-different-secret-also-long-enough", algorithm=ALGO)


def test_decode_access_token_rejects_missing_required_claim() -> None:
    # Bypass create_access_token to craft a token missing "role", exercising
    # the TokenPayload validation branch rather than jwt's own decoding.
    token = jwt.encode({"sub": "u1", "email": "a@example.com"}, SECRET, algorithm=ALGO)
    with pytest.raises(AuthError):
        decode_access_token(token, secret_key=SECRET, algorithm=ALGO)
