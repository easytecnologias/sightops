from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.paths import SIGHTOPS_DB_PATH
from app.core.settings import get_settings


@dataclass(frozen=True)
class DatabaseRuntimeStatus:
    backend: str
    configured: bool
    reachable: bool
    detail: str
    path: str = ""
    host: str = ""
    port: int = 0
    database: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "configured": self.configured,
            "reachable": self.reachable,
            "detail": self.detail,
            "path": self.path,
            "host": self.host,
            "port": self.port,
            "database": self.database,
        }


def _sqlite_status() -> DatabaseRuntimeStatus:
    exists = SIGHTOPS_DB_PATH.exists()
    return DatabaseRuntimeStatus(
        backend="sqlite",
        configured=True,
        reachable=exists,
        detail="sqlite file detected" if exists else "sqlite file not created yet",
        path=str(SIGHTOPS_DB_PATH),
    )


def _postgres_status(database_url: str) -> DatabaseRuntimeStatus:
    host = ""
    port = 5432
    database = ""
    try:
        parsed = urlparse(database_url)
        host = str(parsed.hostname or "").strip()
        port = int(parsed.port or 5432)
        database = str(parsed.path or "").lstrip("/")
        if not host or not database:
            return DatabaseRuntimeStatus(
                backend="postgres",
                configured=False,
                reachable=False,
                detail="DATABASE_URL incompleta para PostgreSQL",
                host=host,
                port=port,
                database=database,
            )
        try:
            import psycopg
        except Exception:
            return DatabaseRuntimeStatus(
                backend="postgres",
                configured=True,
                reachable=False,
                detail="driver psycopg nao instalado",
                host=host,
                port=port,
                database=database,
            )
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return DatabaseRuntimeStatus(
            backend="postgres",
            configured=True,
            reachable=True,
            detail="PostgreSQL reachable",
            host=host,
            port=port,
            database=database,
        )
    except Exception:
        return DatabaseRuntimeStatus(
            backend="postgres",
            configured=True,
            reachable=False,
            detail="PostgreSQL indisponivel",
            host=host,
            port=port,
            database=database,
        )


def database_runtime_status() -> dict[str, object]:
    settings = get_settings()
    backend = str(settings.database_backend or "sqlite").strip().lower()
    if backend == "postgres":
        return _postgres_status(settings.database_url).as_dict()
    return _sqlite_status().as_dict()
