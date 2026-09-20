"""Phase 10: `Settings.check_production_safe` — the app must refuse to boot
in production on dev-safe defaults (brief §39 security bar), while every
non-production environment (including the whole rest of this test suite,
which never sets ENVIRONMENT=production) stays completely unaffected."""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_dev_environment_allows_default_jwt_secret():
    settings = Settings(environment="dev")
    assert settings.jwt_secret_key == "dev-only-insecure-secret-change-me"
    assert not settings.is_production


def test_production_rejects_default_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@host:5432/db",
        )


def test_production_rejects_short_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            environment="production",
            jwt_secret_key="too-short",
            database_url="postgresql+psycopg://u:p@host:5432/db",
        )


def test_production_requires_database_url():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            environment="production",
            jwt_secret_key="a" * 40,
            database_url=None,
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError, match="CORS_ALLOW_ORIGINS"):
        Settings(
            environment="production",
            jwt_secret_key="a" * 40,
            database_url="postgresql+psycopg://u:p@host:5432/db",
            cors_allow_origins=["*"],
        )


def test_production_accepts_a_real_config():
    settings = Settings(
        environment="production",
        jwt_secret_key="a" * 40,
        database_url="postgresql+psycopg://u:p@host:5432/db",
        cors_allow_origins=["https://app.example.com"],
    )
    assert settings.is_production


def test_prod_short_spelling_is_equivalent_to_production():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(environment="prod", database_url="postgresql+psycopg://u:p@host:5432/db")
