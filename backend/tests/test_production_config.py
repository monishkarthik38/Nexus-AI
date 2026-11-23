import pytest

from app.config import Settings, validate_runtime_config
from app.main import app
from httpx import ASGITransport, AsyncClient


def test_development_config_remains_available():
    validate_runtime_config(Settings(ENVIRONMENT="development"))


def test_unknown_environment_fails_closed():
    with pytest.raises(RuntimeError, match="ENVIRONMENT must be either development or production"):
        validate_runtime_config(Settings(ENVIRONMENT="prod"))


def test_production_config_rejects_development_defaults():
    config = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="supabase",
        SUPABASE_URL="https://nexus.example.supabase.co",
        SECRET_KEY="nexus-ai-dev-secret-key-change-in-production",
    )
    with pytest.raises(RuntimeError, match="Unsafe production configuration") as error:
        validate_runtime_config(config)
    assert "SECRET_KEY" in str(error.value)
    assert "PostgreSQL" in str(error.value)
    assert "QDRANT_URL" in str(error.value)


def test_production_config_accepts_remote_services_and_strong_secret():
    config = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="supabase",
        SUPABASE_URL="https://nexus.example.supabase.co",
        SECRET_KEY="a-unique-production-secret-with-more-than-32-characters",
        DATABASE_URL="postgresql+asyncpg://user:password@db.example/nexus",
        QDRANT_URL="https://qdrant.example",
        CORS_ALLOWED_ORIGINS="https://nexus.example,https://admin.nexus.example",
        STORAGE_BACKEND="supabase",
        SUPABASE_SERVICE_ROLE_KEY="server-only-test-storage-key",
        INGESTION_WORKER_DATABASE_URL="postgresql+asyncpg://nexus_worker:secret@db.example/nexus?sslmode=verify-full",
        INGESTION_INLINE_DEVELOPMENT=False,
    )
    config.DATABASE_URL = f"{config.DATABASE_URL}?sslmode=verify-full"
    config.QDRANT_API_KEY = "test-qdrant-key"
    validate_runtime_config(config)
    assert config.cors_origins == ["https://nexus.example", "https://admin.nexus.example"]
    config.INGESTION_INLINE_DEVELOPMENT = True
    with pytest.raises(RuntimeError, match="INGESTION_INLINE_DEVELOPMENT must be false"):
        validate_runtime_config(config)


def test_production_config_rejects_insecure_origins():
    config = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="supabase",
        SUPABASE_URL="https://nexus.example.supabase.co",
        SECRET_KEY="a-unique-production-secret-with-more-than-32-characters",
        DATABASE_URL="postgresql+asyncpg://user:password@db.example/nexus",
        QDRANT_URL="https://qdrant.example",
        CORS_ALLOWED_ORIGINS="http://nexus.example",
        STORAGE_BACKEND="supabase",
        SUPABASE_SERVICE_ROLE_KEY="server-only-test-storage-key",
        INGESTION_WORKER_DATABASE_URL="postgresql+asyncpg://nexus_worker:secret@db.example/nexus?sslmode=verify-full",
    )
    config.DATABASE_URL = f"{config.DATABASE_URL}?sslmode=verify-full"
    config.QDRANT_API_KEY = "test-qdrant-key"
    with pytest.raises(RuntimeError, match="Every production CORS origin must use HTTPS"):
        validate_runtime_config(config)


def test_production_config_requires_authenticated_qdrant_and_database_tls():
    config = Settings(
        ENVIRONMENT="production",
        AUTH_MODE="supabase",
        SUPABASE_URL="https://nexus.example.supabase.co",
        SECRET_KEY="a-unique-production-secret-with-more-than-32-characters",
        QDRANT_URL="https://qdrant.example",
        CORS_ALLOWED_ORIGINS="https://nexus.example",
        STORAGE_BACKEND="supabase",
        SUPABASE_SERVICE_ROLE_KEY="server-only-test-storage-key",
        INGESTION_WORKER_DATABASE_URL="postgresql+asyncpg://nexus_worker:secret@db.example/nexus?sslmode=verify-full",
    )
    config.DATABASE_URL = "postgresql+asyncpg://db.example/nexus"

    with pytest.raises(RuntimeError, match="Unsafe production configuration") as error:
        validate_runtime_config(config)

    assert "DATABASE_URL must require verified TLS" in str(error.value)
    assert "QDRANT_API_KEY is required" in str(error.value)


@pytest.mark.asyncio
async def test_security_headers_and_cors_allowlist():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
        denied = await client.get("/health", headers={"Origin": "https://untrusted.example"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "access-control-allow-origin" not in denied.headers
