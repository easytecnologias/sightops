from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from functools import lru_cache

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback defensivo
    load_dotenv = None

if load_dotenv:
    load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AppSettings:
    app_name: str
    app_env: str
    app_version: str
    app_host: str
    app_port: int
    log_level: str
    log_json: bool
    enable_docs: bool
    database_backend: str
    database_url: str
    database_host: str
    database_port: int
    database_name: str
    database_user: str
    allowed_origins: str
    trusted_proxies: str
    auth_enabled: bool
    auth_required: bool
    auth_legacy_open: bool
    auth_token_ttl_hours: int

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data.pop("database_url", None)
        return data


@lru_cache
def get_settings() -> AppSettings:
    env = str(os.getenv("APP_ENV", "development")).strip().lower()
    db_backend = str(os.getenv("DATABASE_BACKEND", "sqlite")).strip().lower() or "sqlite"
    sqlite_path = str(os.getenv("SIGHTOPS_DB_PATH", "data/sightops.db")).strip()
    normalized_sqlite = sqlite_path.replace("\\", "/")
    db_host = str(os.getenv("DATABASE_HOST", "postgres")).strip()
    db_port = int(os.getenv("DATABASE_PORT", "5432"))
    db_name = str(os.getenv("DATABASE_NAME", "sightops")).strip()
    db_user = str(os.getenv("DATABASE_USER", "sightops")).strip()
    database_url = str(
        os.getenv("DATABASE_URL")
        or (
            f"postgresql://{db_user}:{str(os.getenv('DATABASE_PASSWORD', 'sightops')).strip()}@{db_host}:{db_port}/{db_name}"
            if db_backend == "postgres"
            else f"sqlite:///{normalized_sqlite}"
        )
    ).strip()
    return AppSettings(
        app_name=str(os.getenv("APP_NAME", "cam-snapshot API")).strip(),
        app_env=env,
        app_version=str(os.getenv("APP_VERSION", "1.1.0")).strip(),
        app_host=str(os.getenv("APP_HOST", "0.0.0.0")).strip(),
        app_port=int(os.getenv("APP_PORT", "8000")),
        log_level=str(os.getenv("LOG_LEVEL", "INFO")).strip().upper(),
        log_json=_env_bool("LOG_JSON", env != "development"),
        enable_docs=_env_bool("ENABLE_DOCS", env != "production"),
        database_backend=db_backend,
        database_url=database_url,
        database_host=db_host,
        database_port=db_port,
        database_name=db_name,
        database_user=db_user,
        allowed_origins=str(os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1")).strip(),
        trusted_proxies=str(os.getenv("TRUSTED_PROXIES", "*")).strip(),
        auth_enabled=_env_bool("AUTH_ENABLED", True),
        auth_required=_env_bool("AUTH_REQUIRED", True),
        auth_legacy_open=_env_bool("AUTH_LEGACY_OPEN", False),
        auth_token_ttl_hours=int(os.getenv("AUTH_TOKEN_TTL_HOURS", "24")),
    )
