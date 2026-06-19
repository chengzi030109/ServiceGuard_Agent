from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    chat_model: str = Field(default="gpt-4.1-mini", alias="CHAT_MODEL")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    use_local_fallback: bool = Field(default=True, alias="USE_LOCAL_FALLBACK")
    app_env: str = Field(default="development", alias="APP_ENV")
    require_api_key: bool = Field(default=False, alias="REQUIRE_API_KEY")
    api_keys: str = Field(default="", alias="API_KEYS")
    admin_api_keys: str = Field(default="", alias="ADMIN_API_KEYS")
    api_key_hashes: str = Field(default="", alias="API_KEY_HASHES")
    admin_api_key_hashes: str = Field(default="", alias="ADMIN_API_KEY_HASHES")
    trusted_proxy_auth_enabled: bool = Field(default=False, alias="TRUSTED_PROXY_AUTH_ENABLED")
    trusted_proxy_auth_secret: str = Field(default="", alias="TRUSTED_PROXY_AUTH_SECRET")
    trusted_proxy_secret_header: str = Field(
        default="X-ServiceGuard-Proxy-Secret",
        alias="TRUSTED_PROXY_SECRET_HEADER",
    )
    trusted_proxy_user_header: str = Field(
        default="X-ServiceGuard-User",
        alias="TRUSTED_PROXY_USER_HEADER",
    )
    trusted_proxy_role_header: str = Field(
        default="X-ServiceGuard-Role",
        alias="TRUSTED_PROXY_ROLE_HEADER",
    )
    allowed_origins: str = Field(
        default="http://localhost:8501,http://127.0.0.1:8501", alias="ALLOWED_ORIGINS"
    )
    max_upload_mb: int = Field(default=20, alias="MAX_UPLOAD_MB")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")
    data_retention_days: int = Field(default=30, alias="DATA_RETENTION_DAYS")
    audit_retention_days: int = Field(default=180, alias="AUDIT_RETENTION_DAYS")
    vector_db: str = Field(default="chroma", alias="VECTOR_DB")
    chroma_dir: str = Field(default="./data/chroma", alias="CHROMA_DIR")
    sqlite_url: str = Field(default="sqlite:///./data/serviceguard.db", alias="SQLITE_URL")
    sqlite_busy_timeout_ms: int = Field(default=5000, alias="SQLITE_BUSY_TIMEOUT_MS")
    sqlite_journal_mode: str = Field(default="WAL", alias="SQLITE_JOURNAL_MODE")
    sqlite_synchronous: str = Field(default="NORMAL", alias="SQLITE_SYNCHRONOUS")
    upload_dir: str = Field(default="./data/uploads", alias="UPLOAD_DIR")
    backup_dir: str = Field(default="./data/backups", alias="BACKUP_DIR")
    audit_anchor_dir: str = Field(default="./data/audit_anchors", alias="AUDIT_ANCHOR_DIR")
    backup_signing_key: str = Field(default="", alias="BACKUP_SIGNING_KEY")
    quarantine_prompt_injection_documents: bool = Field(
        default=True,
        alias="QUARANTINE_PROMPT_INJECTION_DOCUMENTS",
    )
    prompt_version: str = Field(default="v0.1", alias="PROMPT_VERSION")
    chunk_size: int = Field(default=700, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")
    top_k: int = Field(default=5, alias="TOP_K")
    max_batch_rows: int = Field(default=500, alias="MAX_BATCH_ROWS")
    batch_job_timeout_seconds: int = Field(default=300, alias="BATCH_JOB_TIMEOUT_SECONDS")
    max_active_batch_jobs: int = Field(default=20, alias="MAX_ACTIVE_BATCH_JOBS")
    max_active_batch_jobs_per_actor: int = Field(
        default=3,
        alias="MAX_ACTIVE_BATCH_JOBS_PER_ACTOR",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def chroma_path(self) -> Path:
        return self._resolve_path(self.chroma_dir)

    @property
    def upload_path(self) -> Path:
        return self._resolve_path(self.upload_dir)

    @property
    def backup_path(self) -> Path:
        return self._resolve_path(self.backup_dir)

    @property
    def audit_anchor_path(self) -> Path:
        return self._resolve_path(self.audit_anchor_dir)

    @property
    def sqlite_path(self) -> Path:
        if not self.sqlite_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// URLs are supported for this project")
        return self._resolve_path(self.sqlite_url.removeprefix("sqlite:///"))

    @property
    def has_remote_llm(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def parsed_api_keys(self) -> list[str]:
        return [item.strip() for item in self.api_keys.split(",") if item.strip()]

    @property
    def parsed_admin_api_keys(self) -> list[str]:
        return [item.strip() for item in self.admin_api_keys.split(",") if item.strip()]

    @property
    def parsed_api_key_hashes(self) -> list[str]:
        return [item.strip().lower() for item in self.api_key_hashes.split(",") if item.strip()]

    @property
    def parsed_admin_api_key_hashes(self) -> list[str]:
        return [
            item.strip().lower() for item in self.admin_api_key_hashes.split(",") if item.strip()
        ]

    @property
    def parsed_all_api_keys(self) -> list[str]:
        return [*self.parsed_api_keys, *self.parsed_admin_api_keys]

    @property
    def has_user_api_key_material(self) -> bool:
        return bool(self.parsed_api_keys or self.parsed_api_key_hashes)

    @property
    def has_admin_api_key_material(self) -> bool:
        return bool(self.parsed_admin_api_keys or self.parsed_admin_api_key_hashes)

    @property
    def has_any_api_key_material(self) -> bool:
        return self.has_user_api_key_material or self.has_admin_api_key_material

    @property
    def parsed_allowed_origins(self) -> list[str]:
        origins = [item.strip() for item in self.allowed_origins.split(",") if item.strip()]
        if "*" in origins:
            return ["*"]
        return origins

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def production_config_errors(self) -> list[str]:
        if not self.is_production:
            return []

        errors: list[str] = []
        if not self.require_api_key:
            errors.append("REQUIRE_API_KEY must be true when APP_ENV=production")
        if not self.has_user_api_key_material and not self.trusted_proxy_auth_enabled:
            errors.append(
                "API_KEYS/API_KEY_HASHES or TRUSTED_PROXY_AUTH_ENABLED must provide "
                "user authentication in production"
            )
        if not self.has_admin_api_key_material and not self.trusted_proxy_auth_enabled:
            errors.append(
                "ADMIN_API_KEYS/ADMIN_API_KEY_HASHES or TRUSTED_PROXY_AUTH_ENABLED must "
                "provide admin authentication in production"
            )
        if self.trusted_proxy_auth_enabled:
            if len(self.trusted_proxy_auth_secret.strip()) < 32:
                errors.append(
                    "TRUSTED_PROXY_AUTH_SECRET must be configured with at least 32 characters"
                )
            if not self.trusted_proxy_user_header.strip():
                errors.append("TRUSTED_PROXY_USER_HEADER must not be empty")
            if not self.trusted_proxy_role_header.strip():
                errors.append("TRUSTED_PROXY_ROLE_HEADER must not be empty")
            if not self.trusted_proxy_secret_header.strip():
                errors.append("TRUSTED_PROXY_SECRET_HEADER must not be empty")
        if self._has_placeholder_or_weak_key(self.parsed_all_api_keys):
            errors.append("API_KEYS and ADMIN_API_KEYS must not use placeholder or short keys")
        if self._has_invalid_key_hash(self.parsed_api_key_hashes):
            errors.append("API_KEY_HASHES must contain lowercase or uppercase SHA-256 hex digests")
        if self._has_invalid_key_hash(self.parsed_admin_api_key_hashes):
            errors.append(
                "ADMIN_API_KEY_HASHES must contain lowercase or uppercase SHA-256 hex digests"
            )
        if "*" in self.parsed_allowed_origins:
            errors.append("ALLOWED_ORIGINS cannot be '*' in production")
        if not self.rate_limit_enabled or self.rate_limit_per_minute <= 0:
            errors.append("RATE_LIMIT_ENABLED must be true with RATE_LIMIT_PER_MINUTE > 0")
        if not self.has_remote_llm:
            errors.append("OPENAI_API_KEY or an OpenAI-compatible key is required in production")
        if self.max_upload_mb <= 0:
            errors.append("MAX_UPLOAD_MB must be positive")
        if self.data_retention_days <= 0:
            errors.append("DATA_RETENTION_DAYS must be positive")
        if self.audit_retention_days <= 0:
            errors.append("AUDIT_RETENTION_DAYS must be positive")
        if self.max_batch_rows <= 0:
            errors.append("MAX_BATCH_ROWS must be positive")
        if self.batch_job_timeout_seconds <= 0:
            errors.append("BATCH_JOB_TIMEOUT_SECONDS must be positive")
        if self.max_active_batch_jobs <= 0:
            errors.append("MAX_ACTIVE_BATCH_JOBS must be positive")
        if self.max_active_batch_jobs_per_actor <= 0:
            errors.append("MAX_ACTIVE_BATCH_JOBS_PER_ACTOR must be positive")
        if self.sqlite_busy_timeout_ms <= 0:
            errors.append("SQLITE_BUSY_TIMEOUT_MS must be positive")
        if self.sqlite_journal_mode.upper() not in {
            "DELETE",
            "TRUNCATE",
            "PERSIST",
            "MEMORY",
            "WAL",
            "OFF",
        }:
            errors.append("SQLITE_JOURNAL_MODE must be a valid SQLite journal mode")
        if self.sqlite_synchronous.upper() not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            errors.append("SQLITE_SYNCHRONOUS must be OFF, NORMAL, FULL, or EXTRA")
        if not self.backup_signing_key.strip() or len(self.backup_signing_key.strip()) < 32:
            errors.append("BACKUP_SIGNING_KEY must be configured with at least 32 characters")
        return errors

    def validate_runtime_security(self) -> None:
        errors = self.production_config_errors()
        if errors:
            joined = "; ".join(errors)
            raise RuntimeError(f"Unsafe production configuration: {joined}")

    def ensure_dirs(self) -> None:
        self.chroma_path.mkdir(parents=True, exist_ok=True)
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.backup_path.mkdir(parents=True, exist_ok=True)
        self.audit_anchor_path.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def _has_placeholder_or_weak_key(self, keys: list[str]) -> bool:
        placeholder_markers = ("replace", "changeme", "example", "demo")
        for key in keys:
            lowered = key.lower()
            if len(key) < 16 or any(marker in lowered for marker in placeholder_markers):
                return True
        return False

    def _has_invalid_key_hash(self, hashes: list[str]) -> bool:
        return any(
            len(item) != 64 or not all(char in "0123456789abcdef" for char in item)
            for item in hashes
        )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
