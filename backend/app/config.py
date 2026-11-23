import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from urllib.parse import parse_qs, urlparse

class Settings(BaseSettings):
    ENVIRONMENT: str = 'development'
    HOST: str = '0.0.0.0'
    PORT: int = 8000
    FRONTEND_URL: str = 'http://localhost:3000'
    SECRET_KEY: str = 'nexus-ai-dev-secret-key-change-in-production'
    CORS_ALLOWED_ORIGINS: str = 'http://localhost:3000'
    AUTH_MODE: str = 'development'
    DEVELOPMENT_USER_ID: str = 'default_user'
    SUPABASE_JWT_SECRET: Optional[str] = None

    # Database
    DATABASE_URL: str = 'sqlite+aiosqlite:///./nexus.db'
    INGESTION_WORKER_DATABASE_URL: Optional[str] = None
    INGESTION_INLINE_DEVELOPMENT: bool = False
    SUPABASE_URL: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None

    # Object storage for documents
    STORAGE_BACKEND: str = 'local'
    STORAGE_DIR: str = './storage/documents'
    SUPABASE_STORAGE_BUCKET: str = 'nexus-documents'

    # Vector DB
    QDRANT_URL: Optional[str] = None # When empty, local embedded storage is used
    QDRANT_API_KEY: Optional[str] = None
    QDRANT_COLLECTION: str = 'nexus_documents_openai'
    QDRANT_STORAGE_PATH: str = './qdrant_storage'

    # LLM & Embeddings
    LLM_PROVIDER: str = 'openai' # 'openai', 'ollama', 'gemini' (legacy), or 'mock'
    LLM_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    LLM_MODEL: str = 'gpt-4o-mini'
    EMBEDDING_MODEL: str = 'text-embedding-3-small'
    OLLAMA_BASE_URL: str = 'http://127.0.0.1:11434'
    OLLAMA_EMBEDDING_MODEL: str = 'nomic-embed-text'
    OLLAMA_EMBEDDING_DIMENSION: int = 768

    # Langfuse Observability
    LANGFUSE_PUBLIC_KEY: Optional[str] = None
    LANGFUSE_SECRET_KEY: Optional[str] = None
    LANGFUSE_BASE_URL: str = 'https://cloud.langfuse.com'

    model_config = SettingsConfigDict(
        env_file=('.env', '../.env'),
        env_file_encoding='utf-8',
        extra='ignore'
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip().rstrip('/') for origin in self.CORS_ALLOWED_ORIGINS.split(',') if origin.strip()]

    @property
    def openai_api_key(self) -> Optional[str]:
        placeholders = {
            'your_gemini_or_openai_api_key_here',
            'your_openai_api_key_here',
        }
        for key in (self.LLM_API_KEY, self.OPENAI_API_KEY):
            if key and key.strip() and key.strip() not in placeholders:
                return key.strip()
        return None


def validate_runtime_config(config: Optional[Settings] = None) -> None:
    """Fail closed when production mode is enabled with development-only settings."""
    config = config or settings
    environment = config.ENVIRONMENT.strip().lower()
    if environment not in {'development', 'production'}:
        raise RuntimeError('ENVIRONMENT must be either development or production')
    if environment != 'production':
        return

    errors = []
    if config.INGESTION_INLINE_DEVELOPMENT:
        errors.append('INGESTION_INLINE_DEVELOPMENT must be false in production')
    if config.AUTH_MODE.strip().lower() != 'supabase':
        errors.append('AUTH_MODE must be supabase in production')
    if not config.SUPABASE_URL:
        errors.append('SUPABASE_URL is required for Supabase authentication')
    elif urlparse(config.SUPABASE_URL).scheme != 'https':
        errors.append('SUPABASE_URL must use HTTPS in production')
    if config.SECRET_KEY == 'nexus-ai-dev-secret-key-change-in-production' or len(config.SECRET_KEY) < 32:
        errors.append('SECRET_KEY must be a unique secret with at least 32 characters')
    if not config.cors_origins or '*' in config.cors_origins:
        errors.append('CORS_ALLOWED_ORIGINS must list explicit trusted origins')
    elif any(urlparse(origin).scheme != 'https' for origin in config.cors_origins):
        errors.append('Every production CORS origin must use HTTPS')
    database_url = config.DATABASE_URL.strip()
    if not database_url.startswith('postgresql+asyncpg://'):
        errors.append('DATABASE_URL must use PostgreSQL with the asyncpg driver in production')
    else:
        database_parameters = parse_qs(urlparse(database_url).query)
        ssl_modes = database_parameters.get('sslmode') or database_parameters.get('ssl') or ['']
        if ssl_modes[0] not in {'require', 'verify-ca', 'verify-full'}:
            errors.append(
                'DATABASE_URL must require verified TLS with sslmode/ssl=require, verify-ca, or verify-full'
            )
    worker_database_url = (config.INGESTION_WORKER_DATABASE_URL or '').strip()
    if not worker_database_url.startswith('postgresql+asyncpg://'):
        errors.append(
            'INGESTION_WORKER_DATABASE_URL must use the dedicated PostgreSQL worker role'
        )
    else:
        worker_parameters = parse_qs(urlparse(worker_database_url).query)
        worker_ssl_modes = worker_parameters.get('sslmode') or worker_parameters.get('ssl') or ['']
        if worker_ssl_modes[0] not in {'require', 'verify-ca', 'verify-full'}:
            errors.append(
                'INGESTION_WORKER_DATABASE_URL must require verified TLS'
            )
    if not config.QDRANT_URL:
        errors.append('QDRANT_URL must point to a remote Qdrant service in production')
    elif urlparse(config.QDRANT_URL).scheme != 'https':
        errors.append('QDRANT_URL must use HTTPS in production')
    if not config.QDRANT_API_KEY or not config.QDRANT_API_KEY.strip():
        errors.append('QDRANT_API_KEY is required for the remote production vector service')
    if config.STORAGE_BACKEND.strip().lower() != 'supabase':
        errors.append('STORAGE_BACKEND must be supabase in production')
    if not config.SUPABASE_SERVICE_ROLE_KEY or not config.SUPABASE_SERVICE_ROLE_KEY.strip():
        errors.append('SUPABASE_SERVICE_ROLE_KEY is required for private document storage')
    if not config.SUPABASE_STORAGE_BUCKET.strip():
        errors.append('SUPABASE_STORAGE_BUCKET must name a private bucket')

    if errors:
        raise RuntimeError('Unsafe production configuration: ' + '; '.join(errors))

settings = Settings()
