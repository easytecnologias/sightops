from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - fallback defensivo
    psycopg = None
    dict_row = None

from app.core.paths import (
    DATA_DIR,
    INVENTORY_JSON_PATH,
    DVR_INVENTORY_JSON_PATH,
    NVR_INVENTORY_JSON_PATH,
    SIGHTOPS_DB_PATH,
)
from app.core.migrations import apply_migrations
from app.core.tenant_context import get_current_tenant_slug, tenant_scoped_key, tenant_scoped_path





class _DbCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return int(getattr(self._cursor, "rowcount", 0) or 0)

    def fetchone(self) -> Any:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return dict(row) if isinstance(row, dict) else row

    def fetchall(self) -> List[Any]:
        rows = self._cursor.fetchall()
        return [dict(r) if isinstance(r, dict) else r for r in rows]


class _PgConnWrapper:
    def __init__(self, conn: Any):
        self._conn = conn

    def __enter__(self) -> "_PgConnWrapper":
        self._conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return self._conn.__exit__(exc_type, exc, tb)

    def close(self) -> None:
        self._conn.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def execute(self, query: str, params: Any = ()) -> _DbCursor:
        cur = self._conn.cursor()
        cur.execute(_sql_for_backend("postgres", query), params)
        return _DbCursor(cur)

    def executescript(self, sql_script: str) -> None:
        _exec_many_statements(self, "postgres", sql_script)


def _db_backend() -> str:
    raw = str(os.getenv("DATABASE_BACKEND", "sqlite")).strip().lower()
    return raw if raw in ("sqlite", "postgres") else "sqlite"


def _postgres_db_url() -> str:
    direct = str(os.getenv("DATABASE_URL") or "").strip()
    if direct and direct.startswith("postgres"):
        return direct
    host = str(os.getenv("DATABASE_HOST") or "postgres").strip()
    port = int(os.getenv("DATABASE_PORT") or "5432")
    name = str(os.getenv("DATABASE_NAME") or "sightops").strip()
    user = str(os.getenv("DATABASE_USER") or "sightops").strip()
    password = str(os.getenv("DATABASE_PASSWORD") or "sightops").strip()
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def _redact_url_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.password is None:
            return raw
        username = parts.username or ""
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        userinfo = f"{username}:***" if username else ""
        netloc = f"{userinfo}@{host}{port}" if userinfo else f"{host}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


def _conn_for_backend(backend: str) -> Any:
    backend_norm = str(backend or "sqlite").strip().lower()
    if backend_norm == "postgres":
        if psycopg is None:
            raise RuntimeError("psycopg nao instalado para db postgres")
        return psycopg.connect(_postgres_db_url(), row_factory=dict_row)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(SIGHTOPS_DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON;")
    return c


def _sql_for_backend(backend: str, query: str) -> str:
    if str(backend or "sqlite").strip().lower() != "postgres":
        return query
    return (
        str(query or "")
        .replace("?", "%s")
        .replace("datetime('now')", "CURRENT_TIMESTAMP")
        .replace(" COLLATE NOCASE", "")
    )


def _exec_many_statements(c: Any, backend: str, schema_sql: str) -> None:
    if str(backend or "sqlite").strip().lower() == "postgres":
        for stmt in [x.strip() for x in str(schema_sql or "").split(";") if x.strip()]:
            c.execute(stmt)
        return
    c.executescript(schema_sql)


def _current_tenant_slug() -> str:
    return str(get_current_tenant_slug() or "default").strip() or "default"


def _sqlite_columns(c: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r["name"]) for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()




def _fetchone_on(c: Any, backend: str, query: str, params: tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    row = c.execute(_sql_for_backend(backend, query), params).fetchone()
    if row is None:
        return None
    return dict(row)


def _fetchall_on(c: Any, backend: str, query: str, params: tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(_sql_for_backend(backend, query), params).fetchall()]


def _execute_on(c: Any, backend: str, query: str, params: tuple[Any, ...] = ()) -> Any:
    return c.execute(_sql_for_backend(backend, query), params)


def _postgres_set_sequence(c: Any, table: str, value: int) -> None:
    c.execute("SELECT setval(pg_get_serial_sequence(%s, 'id'), %s, true)", (table, max(1, int(value or 1))))


def _conn() -> Any:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _db_backend() == "postgres":
        if psycopg is None:
            raise RuntimeError("psycopg nao instalado para db postgres")
        return _PgConnWrapper(psycopg.connect(_postgres_db_url(), row_factory=dict_row))
    c = sqlite3.connect(str(SIGHTOPS_DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON;")
    return c


def _tenant_scoped_keys_satisfied(c: Any, backend: str) -> bool:
    """Pos-condicao da migration 002 do banco principal.

    Verdadeira quando as tabelas ja tem tenant_slug **e** nenhuma UNIQUE sem
    tenant_slug sobrou. Um banco que recebeu so metade disso por remendo antigo
    (o caso da producao) devolve False e a 002 roda pra terminar o servico.
    """
    try:
        if str(backend).strip().lower() == "postgres":
            row = c.execute(
                """
                SELECT
                    (SELECT COUNT(1) FROM information_schema.columns
                      WHERE column_name = 'tenant_slug'
                        AND table_name IN ('sites', 'ip_cameras', 'recorders', 'recorder_channels')) AS cols,
                    (SELECT COUNT(1)
                       FROM pg_constraint con
                       JOIN pg_class cls ON cls.oid = con.conrelid
                      WHERE con.contype = 'u'
                        AND cls.relname IN ('sites', 'ip_cameras', 'recorders')
                        AND NOT EXISTS (
                            SELECT 1 FROM unnest(con.conkey) AS k
                            JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = k
                            WHERE att.attname = 'tenant_slug')) AS legacy
                """
            ).fetchone()
            item = dict(row or {})
            return int(item.get("cols") or 0) >= 4 and int(item.get("legacy") or 0) == 0

        for table in ("sites", "ip_cameras", "recorders", "recorder_channels"):
            if "tenant_slug" not in _sqlite_columns(c, table):
                return False
        rows = c.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name IN ('sites','ip_cameras','recorders')"
        ).fetchall()
        for row in rows or []:
            ddl = str(dict(row).get("sql") or "")
            for chunk in re.findall(r"UNIQUE\s*\(([^)]*)\)", ddl, flags=re.IGNORECASE):
                if "tenant_slug" not in chunk.lower():
                    return False
        return True
    except Exception:
        return False


def _json_state_tenant_scope_satisfied(c: Any, backend: str) -> bool:
    try:
        if str(backend).strip().lower() == "postgres":
            row = c.execute(
                """
                SELECT
                    (SELECT COUNT(1) FROM information_schema.columns
                      WHERE table_name = 'json_state'
                        AND column_name = 'tenant_slug') AS cols,
                    (SELECT COUNT(1)
                       FROM pg_indexes
                      WHERE tablename = 'json_state'
                        AND indexdef ILIKE '%tenant_slug%'
                        AND indexdef ILIKE '%k%') AS idx
                """
            ).fetchone()
            item = dict(row or {})
            return int(item.get("cols") or 0) >= 1 and int(item.get("idx") or 0) >= 1

        if "tenant_slug" not in _sqlite_columns(c, "json_state"):
            return False
        rows = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='json_state'").fetchall()
        ddl = " ".join(str(dict(row).get("sql") or "") for row in rows or [])
        return "tenant_slug" in ddl.lower() and "unique" in ddl.lower()
    except Exception:
        return False


def init_db() -> Dict[str, Any]:
    backend = _db_backend()
    with _conn() as c:
        migration_status = apply_migrations(
            c,
            backend=backend,
            component="main",
            adopt_probe_tables=("sites", "ip_cameras", "recorders"),
            postconditions={2: _tenant_scoped_keys_satisfied, 9: _json_state_tenant_scope_satisfied},
        )
        tenant = _current_tenant_slug()
        total = int(c.execute("SELECT COUNT(1) AS n FROM sites WHERE tenant_slug=?", (tenant,)).fetchone()["n"])
    return {
        "ok": True,
        "backend": backend,
        "db_path": str(SIGHTOPS_DB_PATH) if backend == "sqlite" else "",
        "database_url": _redact_url_secret(_postgres_db_url()) if backend == "postgres" else "",
        "tenant": tenant,
        "sites": total,
        "schema_version": migration_status.get("current_version"),
        "migrations_applied": migration_status.get("applied_now"),
        "migrations_adopted": migration_status.get("adopted"),
    }


def _load_json_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        obj = json.loads(path.read_text(encoding="utf-8") or "[]")
        return obj if isinstance(obj, list) else []
    except Exception:
        return []


def list_sites(source: str = "") -> List[Dict[str, Any]]:
    src = str(source or "").strip().lower()
    tenant = _current_tenant_slug()
    with _conn() as c:
        names: set[str] = set()

        if src == "ip":
            rows_all_sites = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(name,'')) AS name
                FROM sites
                WHERE tenant_slug = ?
                  AND active = 1
                  AND trim(COALESCE(name,'')) <> ''
                  AND upper(trim(name)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            rows_site = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(s.name,'')) AS name
                FROM ip_cameras ic
                LEFT JOIN sites s ON s.id = ic.site_id
                WHERE ic.tenant_slug = ?
                  AND trim(COALESCE(s.name,'')) <> '' AND upper(trim(s.name)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            rows_local = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(local,'')) AS name
                FROM ip_cameras
                WHERE tenant_slug = ?
                  AND trim(COALESCE(local,'')) <> '' AND upper(trim(local)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            for bucket in (rows_all_sites, rows_site, rows_local):
                for r in bucket:
                    n = str(r["name"] or "").strip()
                    if n:
                        names.add(n)
        elif src in ("dvr", "nvr"):
            rows_site = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(s.name,'')) AS name
                FROM recorders r
                LEFT JOIN sites s ON s.id = r.site_id
                WHERE r.tenant_slug = ?
                  AND r.source = ?
                  AND trim(COALESCE(s.name,'')) <> ''
                  AND upper(trim(s.name)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant, src),
            ).fetchall()
            rows_rec_local = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(r.local,'')) AS name
                FROM recorders r
                WHERE r.tenant_slug = ?
                  AND r.source = ?
                  AND trim(COALESCE(r.local,'')) <> ''
                  AND upper(trim(r.local)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant, src),
            ).fetchall()
            rows_ch_local = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(rc.local,'')) AS name
                FROM recorder_channels rc
                JOIN recorders r ON r.id = rc.recorder_id
                WHERE r.tenant_slug = ?
                  AND r.source = ?
                  AND trim(COALESCE(rc.local,'')) <> ''
                  AND upper(trim(rc.local)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant, src),
            ).fetchall()
            for bucket in (rows_site, rows_rec_local, rows_ch_local):
                for r in bucket:
                    n = str(r["name"] or "").strip()
                    if n:
                        names.add(n)
        else:
            rows = c.execute(
                """
                SELECT DISTINCT trim(COALESCE(s.name,'')) AS name
                FROM ip_cameras ic
                LEFT JOIN sites s ON s.id = ic.site_id
                WHERE ic.tenant_slug = ? AND trim(COALESCE(s.name,'')) <> '' AND upper(trim(s.name)) <> 'GERAL'
                UNION
                SELECT DISTINCT trim(COALESCE(ic.local,'')) AS name
                FROM ip_cameras ic
                WHERE ic.tenant_slug = ? AND trim(COALESCE(ic.local,'')) <> '' AND upper(trim(ic.local)) <> 'GERAL'
                UNION
                SELECT DISTINCT trim(COALESCE(s.name,'')) AS name
                FROM recorders r
                LEFT JOIN sites s ON s.id = r.site_id
                WHERE r.tenant_slug = ? AND trim(COALESCE(s.name,'')) <> '' AND upper(trim(s.name)) <> 'GERAL'
                UNION
                SELECT DISTINCT trim(COALESCE(r.local,'')) AS name
                FROM recorders r
                WHERE r.tenant_slug = ? AND trim(COALESCE(r.local,'')) <> '' AND upper(trim(r.local)) <> 'GERAL'
                UNION
                SELECT DISTINCT trim(COALESCE(rc.local,'')) AS name
                FROM recorder_channels rc
                WHERE rc.tenant_slug = ? AND trim(COALESCE(rc.local,'')) <> '' AND upper(trim(rc.local)) <> 'GERAL'
                ORDER BY name COLLATE NOCASE
                """,
                (tenant, tenant, tenant, tenant, tenant),
            ).fetchall()
            for r in rows:
                n = str(r["name"] or "").strip()
                if n:
                    names.add(n)

    return [{"name": n} for n in sorted(names, key=lambda x: x.lower())]


def upsert_site(name: str, description: str = "", active: bool = True) -> Dict[str, Any]:
    n = str(name or "").strip()
    if not n:
        raise ValueError("name obrigatorio")
    tenant = _current_tenant_slug()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO sites(tenant_slug, name, description, active)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(tenant_slug, name) DO UPDATE SET
              description=excluded.description,
              active=excluded.active
            """,
            (tenant, n, str(description or "").strip(), 1 if bool(active) else 0),
        )
        row = c.execute(
            "SELECT id, tenant_slug, name, description, active FROM sites WHERE tenant_slug=? AND name=?",
            (tenant, n),
        ).fetchone()
    return dict(row) if row else {}


def _site_id_for_name(c: sqlite3.Connection, site_name: str) -> Optional[int]:
    n = str(site_name or "").strip()
    if not n:
        return None
    tenant = _current_tenant_slug()
    c.execute(
        """
        INSERT INTO sites(tenant_slug, name, description, active)
        VALUES(?, ?, '', 1)
        ON CONFLICT(tenant_slug, name) DO NOTHING
        """,
        (tenant, n),
    )
    r = c.execute("SELECT id FROM sites WHERE tenant_slug=? AND name=?", (tenant, n)).fetchone()
    return int(r["id"]) if r else None


def _site_name_from_row(row: Dict[str, Any]) -> str:
    for k in ("site", "site_name", "unidade", "grupo", "group", "local", "LOCAL"):
        v = str(row.get(k) or "").strip()
        if v:
            return v
    return ""


def migrate_json_to_db() -> Dict[str, Any]:
    init_db()
    tenant = _current_tenant_slug()
    ip_rows = _load_json_rows(INVENTORY_JSON_PATH)
    dvr_rows = _load_json_rows(DVR_INVENTORY_JSON_PATH)
    nvr_rows = _load_json_rows(NVR_INVENTORY_JSON_PATH)
    with _conn() as c:
        ip_count = 0
        for r in ip_rows:
            if not isinstance(r, dict):
                continue
            ip = str(r.get("ip") or r.get("host") or "").strip()
            if not ip:
                continue
            site_id = _site_id_for_name(c, _site_name_from_row(r))
            c.execute(
                """
                INSERT INTO ip_cameras(
                  tenant_slug, site_id, ip, host, http_port, title, local, status, mac, fabricante, modelo, snapshot_url, imgbb_url, raw_json, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(tenant_slug, ip) DO UPDATE SET
                  site_id=excluded.site_id,
                  host=excluded.host,
                  http_port=excluded.http_port,
                  title=excluded.title,
                  local=excluded.local,
                  status=excluded.status,
                  mac=excluded.mac,
                  fabricante=excluded.fabricante,
                  modelo=excluded.modelo,
                  snapshot_url=excluded.snapshot_url,
                  imgbb_url=excluded.imgbb_url,
                  raw_json=excluded.raw_json,
                  updated_at=datetime('now')
                """,
                (
                    tenant,
                    site_id,
                    ip,
                    str(r.get("host") or ip),
                    int(r.get("http_port") or 80),
                    str(r.get("title") or r.get("titulo") or ""),
                    str(r.get("local") or ""),
                    str(r.get("status") or ""),
                    str(r.get("mac") or ""),
                    str(r.get("fabricante") or ""),
                    str(r.get("modelo") or ""),
                    str(r.get("snapshot_url") or ""),
                    str(r.get("imgbb_url") or ""),
                    json.dumps(r, ensure_ascii=False),
                ),
            )
            ip_count += 1

        rec_count = 0
        ch_count = 0
        for source, rows in (("dvr", dvr_rows), ("nvr", nvr_rows)):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                host = str(r.get("host") or "").strip()
                if not host:
                    continue
                http_port = int(r.get("http_port") or 80)
                site_id = _site_id_for_name(c, _site_name_from_row(r))
                c.execute(
                    """
                    INSERT INTO recorders(tenant_slug, site_id, source, host, http_port, mac, modelo, fabricante, local, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(tenant_slug, source, host, http_port) DO UPDATE SET
                      site_id=excluded.site_id,
                      mac=excluded.mac,
                      modelo=excluded.modelo,
                      fabricante=excluded.fabricante,
                      local=excluded.local,
                      updated_at=datetime('now')
                    """,
                    (
                        tenant,
                        site_id,
                        source,
                        host,
                        http_port,
                        str(r.get("nvr_mac") or r.get("dvr_mac") or r.get("mac") or ""),
                        str(r.get("nvr_model") or r.get("dvr_model") or r.get("modelo") or ""),
                        str(r.get("fabricante") or ""),
                        str(r.get("local") or ""),
                    ),
                )
                rec = c.execute(
                    "SELECT id FROM recorders WHERE tenant_slug=? AND source=? AND host=? AND http_port=?",
                    (tenant, source, host, http_port),
                ).fetchone()
                if not rec:
                    continue
                recorder_id = int(rec["id"])
                rec_count += 1

                channel = int(r.get("channel") or 0)
                if channel <= 0:
                    continue
                c.execute(
                    """
                    INSERT INTO recorder_channels(
                      tenant_slug, recorder_id, channel, title, status, local, camera_ip, camera_mac, camera_model, snapshot_url, imgbb_url, raw_json, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(recorder_id, channel) DO UPDATE SET
                      tenant_slug=excluded.tenant_slug,
                      title=excluded.title,
                      status=excluded.status,
                      local=excluded.local,
                      camera_ip=excluded.camera_ip,
                      camera_mac=excluded.camera_mac,
                      camera_model=excluded.camera_model,
                      snapshot_url=excluded.snapshot_url,
                      imgbb_url=excluded.imgbb_url,
                      raw_json=excluded.raw_json,
                      updated_at=datetime('now')
                    """,
                    (
                        tenant,
                        recorder_id,
                        channel,
                        str(r.get("title") or ""),
                        str(r.get("status") or ""),
                        str(r.get("local") or ""),
                        str(r.get("camera_ip") or ""),
                        str(r.get("camera_mac") or r.get("mac_camera") or r.get("mac") or ""),
                        str(r.get("camera_model") or r.get("modelo") or ""),
                        str(r.get("snapshot_url") or ""),
                        str(r.get("imgbb_url") or ""),
                        json.dumps(r, ensure_ascii=False),
                    ),
                )
                ch_count += 1

    return {
        "ok": True,
        "db_path": str(SIGHTOPS_DB_PATH),
        "migrated": {
            "ip_cameras": ip_count,
            "recorders_rows_seen": rec_count,
            "recorder_channels": ch_count,
        },
    }


def db_status() -> Dict[str, Any]:
    if _db_backend() == "sqlite" and not SIGHTOPS_DB_PATH.exists():
        return {"ok": True, "backend": "sqlite", "exists": False, "db_path": str(SIGHTOPS_DB_PATH)}
    init_db()
    tenant = _current_tenant_slug()
    with _conn() as c:
        tables = {
            "sites": int(c.execute("SELECT COUNT(1) AS n FROM sites WHERE tenant_slug=?", (tenant,)).fetchone()["n"]),
            "ip_cameras": int(c.execute("SELECT COUNT(1) AS n FROM ip_cameras WHERE tenant_slug=?", (tenant,)).fetchone()["n"]),
            "recorders": int(c.execute("SELECT COUNT(1) AS n FROM recorders WHERE tenant_slug=?", (tenant,)).fetchone()["n"]),
            "recorder_channels": int(c.execute("SELECT COUNT(1) AS n FROM recorder_channels WHERE tenant_slug=?", (tenant,)).fetchone()["n"]),
            "json_state": int(c.execute("SELECT COUNT(1) AS n FROM json_state WHERE tenant_slug=?", (tenant,)).fetchone()["n"]),
        }
        totals = {
            "sites": int(c.execute("SELECT COUNT(1) AS n FROM sites").fetchone()["n"]),
            "ip_cameras": int(c.execute("SELECT COUNT(1) AS n FROM ip_cameras").fetchone()["n"]),
            "recorders": int(c.execute("SELECT COUNT(1) AS n FROM recorders").fetchone()["n"]),
            "recorder_channels": int(c.execute("SELECT COUNT(1) AS n FROM recorder_channels").fetchone()["n"]),
            "json_state": tables["json_state"],
        }
    return {
        "ok": True,
        "backend": _db_backend(),
        "exists": True,
        "db_path": str(SIGHTOPS_DB_PATH) if _db_backend() == "sqlite" else "",
        "database_url": _redact_url_secret(_postgres_db_url()) if _db_backend() == "postgres" else "",
        "tenant": tenant,
        "counts": tables,
        "total_counts": totals,
    }


def migrate_db_storage(source_backend: str = "sqlite", target_backend: str = "postgres", force: bool = False) -> Dict[str, Any]:
    src_backend = str(source_backend or "sqlite").strip().lower()
    dst_backend = str(target_backend or "postgres").strip().lower()
    if src_backend not in ("sqlite", "postgres") or dst_backend not in ("sqlite", "postgres"):
        raise ValueError("backend invalido")
    if src_backend == dst_backend:
        raise ValueError("source e target nao podem ser iguais")

    src = _conn_for_backend(src_backend)
    dst = _conn_for_backend(dst_backend)
    try:
        if src_backend == "sqlite":
            init_db()
        # O destino tambem nasce pelas migrations -- nunca por um literal de
        # schema paralelo, que era como os dois caminhos divergiam antes.
        dst_wrapped = _PgConnWrapper(dst) if dst_backend == "postgres" else dst
        apply_migrations(
            dst_wrapped,
            backend=dst_backend,
            component="main",
            adopt_probe_tables=("sites", "ip_cameras", "recorders"),
            postconditions={2: _tenant_scoped_keys_satisfied, 9: _json_state_tenant_scope_satisfied},
        )

        src_counts = {
            "sites": int((_fetchone_on(src, src_backend, "SELECT COUNT(1) AS n FROM sites") or {}).get("n") or 0),
            "json_state": int((_fetchone_on(src, src_backend, "SELECT COUNT(1) AS n FROM json_state") or {}).get("n") or 0),
            "ip_cameras": int((_fetchone_on(src, src_backend, "SELECT COUNT(1) AS n FROM ip_cameras") or {}).get("n") or 0),
            "recorders": int((_fetchone_on(src, src_backend, "SELECT COUNT(1) AS n FROM recorders") or {}).get("n") or 0),
            "recorder_channels": int((_fetchone_on(src, src_backend, "SELECT COUNT(1) AS n FROM recorder_channels") or {}).get("n") or 0),
        }
        dst_has_data = sum(
            int((_fetchone_on(dst, dst_backend, f"SELECT COUNT(1) AS n FROM {table}") or {}).get("n") or 0)
            for table in ("sites", "json_state", "ip_cameras", "recorders", "recorder_channels")
        )
        if dst_has_data > 0 and not force:
            raise ValueError("target main storage ja possui dados; use force=1 para sobrescrever")

        if force:
            for table in ("recorder_channels", "recorders", "ip_cameras", "json_state", "settings_kv", "sites"):
                _execute_on(dst, dst_backend, f"DELETE FROM {table}")

        sites = _fetchall_on(src, src_backend, "SELECT id, name, description, active, created_at FROM sites ORDER BY id")
        settings_kv = _fetchall_on(src, src_backend, "SELECT k, v, updated_at FROM settings_kv ORDER BY k")
        json_state = _fetchall_on(src, src_backend, "SELECT tenant_slug, k, v, updated_at FROM json_state ORDER BY tenant_slug, k")
        ip_cameras = _fetchall_on(
            src,
            src_backend,
            """
            SELECT id, site_id, ip, host, http_port, title, local, status, mac, fabricante, modelo,
                   snapshot_url, imgbb_url, raw_json, updated_at
            FROM ip_cameras
            ORDER BY id
            """,
        )
        recorders = _fetchall_on(
            src,
            src_backend,
            """
            SELECT id, site_id, source, host, http_port, mac, modelo, fabricante, local, updated_at
            FROM recorders
            ORDER BY id
            """,
        )
        recorder_channels = _fetchall_on(
            src,
            src_backend,
            """
            SELECT id, recorder_id, channel, title, status, local, camera_ip, camera_mac, camera_model,
                   snapshot_url, imgbb_url, raw_json, updated_at
            FROM recorder_channels
            ORDER BY id
            """,
        )

        for row in sites:
            _execute_on(
                dst,
                dst_backend,
                "INSERT INTO sites(id, name, description, active, created_at) VALUES(?, ?, ?, ?, ?)",
                (row["id"], row["name"], row.get("description") or "", row["active"], row["created_at"]),
            )
        for row in settings_kv:
            _execute_on(
                dst,
                dst_backend,
                "INSERT INTO settings_kv(k, v, updated_at) VALUES(?, ?, ?)",
                (row["k"], row["v"], row["updated_at"]),
            )
        for row in json_state:
            _execute_on(
                dst,
                dst_backend,
                "INSERT INTO json_state(tenant_slug, k, v, updated_at) VALUES(?, ?, ?, ?)",
                (row.get("tenant_slug") or "default", row["k"], row["v"], row["updated_at"]),
            )
        for row in ip_cameras:
            _execute_on(
                dst,
                dst_backend,
                """
                INSERT INTO ip_cameras(
                    id, site_id, ip, host, http_port, title, local, status, mac, fabricante, modelo,
                    snapshot_url, imgbb_url, raw_json, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row.get("site_id"), row["ip"], row.get("host") or "", row.get("http_port") or 80,
                    row.get("title") or "", row.get("local") or "", row.get("status") or "", row.get("mac") or "",
                    row.get("fabricante") or "", row.get("modelo") or "", row.get("snapshot_url") or "",
                    row.get("imgbb_url") or "", row.get("raw_json") or "", row["updated_at"],
                ),
            )
        for row in recorders:
            _execute_on(
                dst,
                dst_backend,
                """
                INSERT INTO recorders(id, site_id, source, host, http_port, mac, modelo, fabricante, local, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row.get("site_id"), row["source"], row["host"], row.get("http_port") or 80,
                    row.get("mac") or "", row.get("modelo") or "", row.get("fabricante") or "", row.get("local") or "",
                    row["updated_at"],
                ),
            )
        for row in recorder_channels:
            _execute_on(
                dst,
                dst_backend,
                """
                INSERT INTO recorder_channels(
                    id, recorder_id, channel, title, status, local, camera_ip, camera_mac, camera_model,
                    snapshot_url, imgbb_url, raw_json, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], row["recorder_id"], row["channel"], row.get("title") or "", row.get("status") or "",
                    row.get("local") or "", row.get("camera_ip") or "", row.get("camera_mac") or "",
                    row.get("camera_model") or "", row.get("snapshot_url") or "", row.get("imgbb_url") or "",
                    row.get("raw_json") or "", row["updated_at"],
                ),
            )

        if dst_backend == "postgres":
            _postgres_set_sequence(dst, "sites", max([int(x["id"]) for x in sites], default=1))
            _postgres_set_sequence(dst, "ip_cameras", max([int(x["id"]) for x in ip_cameras], default=1))
            _postgres_set_sequence(dst, "recorders", max([int(x["id"]) for x in recorders], default=1))
            _postgres_set_sequence(dst, "recorder_channels", max([int(x["id"]) for x in recorder_channels], default=1))

        if dst_backend == "sqlite":
            dst.commit()
        else:
            dst.commit()
        return {
            "ok": True,
            "source_backend": src_backend,
            "target_backend": dst_backend,
            "force": bool(force),
            "source_counts": src_counts,
            "copied": {
                "sites": len(sites),
            "settings_kv": len(settings_kv),
            "json_state": len(json_state),
            "ip_cameras": len(ip_cameras),
            "recorders": len(recorders),
            "recorder_channels": len(recorder_channels),
        },
            "target_database_url": _redact_url_secret(_postgres_db_url()) if dst_backend == "postgres" else "",
            "target_db_path": str(SIGHTOPS_DB_PATH) if dst_backend == "sqlite" else "",
        }
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def _json_state_key_parts(key: str) -> tuple[str, str]:
    raw = str(key or "").strip()
    marker = "__tenant__"
    if marker in raw:
        base, tenant = raw.rsplit(marker, 1)
        tenant_slug = str(tenant or "").strip().lower() or _current_tenant_slug()
        return tenant_slug, str(base or "").strip()
    return _current_tenant_slug(), raw


def set_json_state(key: str, obj: Any) -> Dict[str, Any]:
    tenant, k = _json_state_key_parts(key)
    if not k:
        raise ValueError("key obrigatoria")
    payload = json.dumps(obj if obj is not None else {}, ensure_ascii=False)
    try:
        init_db()
        with _conn() as c:
            c.execute(
                """
                INSERT INTO json_state(tenant_slug, k, v, updated_at)
                VALUES(?, ?, ?, datetime('now'))
                ON CONFLICT(tenant_slug, k) DO UPDATE SET
                  v=excluded.v,
                  updated_at=datetime('now')
                """,
                (tenant, k, payload),
            )
    except Exception:
        return {"ok": False, "tenant": tenant, "key": k}
    return {"ok": True, "tenant": tenant, "key": k}


def get_json_state(key: str, default: Any = None) -> Any:
    tenant, k = _json_state_key_parts(key)
    if not k:
        return default
    if _db_backend() == "sqlite" and not SIGHTOPS_DB_PATH.exists():
        return default
    try:
        init_db()
        with _conn() as c:
            r = c.execute("SELECT v FROM json_state WHERE tenant_slug=? AND k=?", (tenant, k)).fetchone()
    except Exception:
        return default
    if not r:
        return default
    try:
        return json.loads(str(r["v"] or "null"))
    except Exception:
        return default


def load_app_settings() -> Dict[str, Any]:
    state = get_json_state(tenant_scoped_key("app_settings"), None)
    if isinstance(state, dict):
        return state
    p = tenant_scoped_path("settings.json")
    try:
        if p.exists():
            obj = json.loads(p.read_text(encoding="utf-8") or "{}")
            if isinstance(obj, dict):
                set_json_state(tenant_scoped_key("app_settings"), obj)
                return obj
    except Exception:
        pass
    return {}


def save_app_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    obj = settings if isinstance(settings, dict) else {}
    try:
        set_json_state(tenant_scoped_key("app_settings"), obj)
    except Exception:
        # fallback de escrita legado
        p = tenant_scoped_path("settings.json")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {"ok": True}


def _legacy_state_import_enabled() -> bool:
    raw = str(os.getenv("ENABLE_LEGACY_STATE_IMPORT", "")).strip().lower()
    if raw:
        return raw in ("1", "true", "yes", "on")
    return str(os.getenv("APP_ENV", "")).strip().lower() not in ("production", "prod")


def load_olt_cpe_state() -> Dict[str, Any]:
    key = tenant_scoped_key("olt_cpe_macs")
    state = get_json_state(key, None)
    if isinstance(state, dict):
        return state
    if not _legacy_state_import_enabled():
        return {}
    p = DATA_DIR / "olt-cpe-macs.json"
    try:
        if p.exists():
            obj = json.loads(p.read_text(encoding="utf-8") or "{}")
            if isinstance(obj, dict):
                set_json_state(key, obj)
                return obj
    except Exception:
        pass
    return {}


def save_olt_cpe_state(obj: Dict[str, Any]) -> Dict[str, Any]:
    payload = obj if isinstance(obj, dict) else {}
    try:
        set_json_state(tenant_scoped_key("olt_cpe_macs"), payload)
    except Exception:
        # fallback de escrita legado
        p = tenant_scoped_path("olt-cpe-macs.json")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {"ok": True}


def load_switch_mac_state() -> Dict[str, Any]:
    key = tenant_scoped_key("switch_mac_table")
    state = get_json_state(key, None)
    if isinstance(state, dict):
        return state
    if not _legacy_state_import_enabled():
        return {}
    p = DATA_DIR / "switch-mac-table.json"
    try:
        if p.exists():
            obj = json.loads(p.read_text(encoding="utf-8") or "{}")
            if isinstance(obj, dict):
                set_json_state(key, obj)
                return obj
    except Exception:
        pass
    return {}


def save_switch_mac_state(obj: Dict[str, Any]) -> Dict[str, Any]:
    payload = obj if isinstance(obj, dict) else {}
    try:
        set_json_state(tenant_scoped_key("switch_mac_table"), payload)
    except Exception:
        p = tenant_scoped_path("switch-mac-table.json")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return {"ok": True}


def query_inventory(source: str = "ip", site: str = "", only_online: bool = False) -> List[Dict[str, Any]]:
    src = str(source or "ip").strip().lower()
    site = str(site or "").strip()
    tenant = _current_tenant_slug()
    with _conn() as c:
        if src == "ip":
            q = """
            SELECT ic.*, s.name AS site_name
            FROM ip_cameras ic
            LEFT JOIN sites s ON s.id = ic.site_id
            WHERE ic.tenant_slug = ?
              AND (? = '' OR s.name = ? OR lower(trim(ic.local)) = lower(trim(?)))
            """
            params: List[Any] = [tenant, site, site, site]
            if only_online:
                q += " AND lower(ic.status) = 'online'"
            q += " ORDER BY COALESCE(s.name,''), ic.ip"
            return [dict(r) for r in c.execute(q, params).fetchall()]

        q2 = """
        SELECT rc.*, r.source, r.host, r.http_port, r.modelo AS recorder_model, r.fabricante AS recorder_vendor,
               s.name AS site_name
        FROM recorder_channels rc
        JOIN recorders r ON r.id = rc.recorder_id
        LEFT JOIN sites s ON s.id = r.site_id
        WHERE r.tenant_slug = ?
          AND r.source = ? AND (? = '' OR s.name = ? OR lower(trim(COALESCE(rc.local, r.local, ''))) = lower(trim(?)))
        """
        params2: List[Any] = [tenant, src, site, site, site]
        if only_online:
            q2 += " AND lower(rc.status) = 'online'"
        q2 += " ORDER BY COALESCE(s.name,''), r.host, rc.channel"
        return [dict(r) for r in c.execute(q2, params2).fetchall()]


def assign_site(
    source: str,
    site_name: str,
    *,
    ip: str = "",
    host: str = "",
    channel: Optional[int] = None,
) -> Dict[str, Any]:
    src = str(source or "").strip().lower()
    if src not in ("ip", "dvr", "nvr"):
        raise ValueError("source invalido (use ip|dvr|nvr)")
    tenant = _current_tenant_slug()
    with _conn() as c:
        site_id = _site_id_for_name(c, site_name)
        updated = 0
        if src == "ip":
            if ip:
                cur = c.execute(
                    "UPDATE ip_cameras SET site_id=?, updated_at=datetime('now') WHERE tenant_slug=? AND ip=?",
                    (site_id, tenant, ip),
                )
                updated = int(cur.rowcount or 0)
            else:
                cur = c.execute(
                    "UPDATE ip_cameras SET site_id=?, updated_at=datetime('now') WHERE tenant_slug=?",
                    (site_id, tenant),
                )
                updated = int(cur.rowcount or 0)
            return {"ok": True, "source": src, "site": site_name, "updated_rows": updated}

        if not host:
            raise ValueError("host obrigatorio para dvr/nvr")
        cur = c.execute(
            "UPDATE recorders SET site_id=?, updated_at=datetime('now') WHERE tenant_slug=? AND source=? AND host=?",
            (site_id, tenant, src, host),
        )
        updated = int(cur.rowcount or 0)
        if channel is not None and int(channel) > 0:
            cur2 = c.execute(
                """
                UPDATE recorders
                SET site_id=?, updated_at=datetime('now')
                WHERE id IN (
                  SELECT r.id FROM recorders r
                  JOIN recorder_channels rc ON rc.recorder_id=r.id
                  WHERE r.tenant_slug=? AND r.source=? AND r.host=? AND rc.channel=?
                )
                """,
                (site_id, tenant, src, host, int(channel)),
            )
            updated = int(cur2.rowcount or 0)
        return {"ok": True, "source": src, "site": site_name, "updated_rows": updated}


def upsert_ip_inventory_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    init_db()
    tenant = _current_tenant_slug()
    seen = 0
    with _conn() as c:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            ip = str(r.get("ip") or r.get("host") or "").strip()
            if not ip:
                continue
            site_id = _site_id_for_name(c, _site_name_from_row(r))
            c.execute(
                """
                INSERT INTO ip_cameras(
                  tenant_slug, site_id, ip, host, http_port, title, local, status, mac, fabricante, modelo, snapshot_url, imgbb_url, raw_json, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(tenant_slug, ip) DO UPDATE SET
                  site_id=excluded.site_id,
                  host=excluded.host,
                  http_port=excluded.http_port,
                  title=excluded.title,
                  local=excluded.local,
                  status=excluded.status,
                  mac=excluded.mac,
                  fabricante=excluded.fabricante,
                  modelo=excluded.modelo,
                  snapshot_url=excluded.snapshot_url,
                  imgbb_url=excluded.imgbb_url,
                  raw_json=excluded.raw_json,
                  updated_at=datetime('now')
                """,
                (
                    tenant,
                    site_id,
                    ip,
                    str(r.get("host") or ip),
                    int(r.get("http_port") or 80),
                    str(r.get("title") or r.get("titulo") or ""),
                    str(r.get("local") or ""),
                    str(r.get("status") or ""),
                    str(r.get("mac") or ""),
                    str(r.get("fabricante") or ""),
                    str(r.get("modelo") or ""),
                    str(r.get("snapshot_url") or ""),
                    str(r.get("imgbb_url") or ""),
                    json.dumps(r, ensure_ascii=False),
                ),
            )
            seen += 1
    return {"ok": True, "upserted": seen}


def upsert_recorder_inventory_rows(source: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    src = str(source or "").strip().lower()
    if src not in ("dvr", "nvr"):
        raise ValueError("source invalido para recorder (use dvr|nvr)")
    init_db()
    tenant = _current_tenant_slug()
    rec_seen = 0
    ch_seen = 0
    with _conn() as c:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            host = str(r.get("host") or "").strip()
            if not host:
                continue
            http_port = int(r.get("http_port") or 80)
            site_id = _site_id_for_name(c, _site_name_from_row(r))
            c.execute(
                """
                INSERT INTO recorders(tenant_slug, site_id, source, host, http_port, mac, modelo, fabricante, local, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(tenant_slug, source, host, http_port) DO UPDATE SET
                  site_id=excluded.site_id,
                  mac=excluded.mac,
                  modelo=excluded.modelo,
                  fabricante=excluded.fabricante,
                  local=excluded.local,
                  updated_at=datetime('now')
                """,
                (
                    tenant,
                    site_id,
                    src,
                    host,
                    http_port,
                    str(r.get("nvr_mac") or r.get("dvr_mac") or r.get("mac") or ""),
                    str(r.get("nvr_model") or r.get("dvr_model") or r.get("modelo") or ""),
                    str(r.get("fabricante") or ""),
                    str(r.get("local") or ""),
                ),
            )
            rec = c.execute(
                "SELECT id FROM recorders WHERE tenant_slug=? AND source=? AND host=? AND http_port=?",
                (tenant, src, host, http_port),
            ).fetchone()
            if not rec:
                continue
            recorder_id = int(rec["id"])
            rec_seen += 1

            channel = int(r.get("channel") or 0)
            if channel <= 0:
                continue
            c.execute(
                """
                INSERT INTO recorder_channels(
                  tenant_slug, recorder_id, channel, title, status, local, camera_ip, camera_mac, camera_model, snapshot_url, imgbb_url, raw_json, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(recorder_id, channel) DO UPDATE SET
                  tenant_slug=excluded.tenant_slug,
                  title=excluded.title,
                  status=excluded.status,
                  local=excluded.local,
                  camera_ip=excluded.camera_ip,
                  camera_mac=excluded.camera_mac,
                  camera_model=excluded.camera_model,
                  snapshot_url=excluded.snapshot_url,
                  imgbb_url=excluded.imgbb_url,
                  raw_json=excluded.raw_json,
                  updated_at=datetime('now')
                """,
                (
                    tenant,
                    recorder_id,
                    channel,
                    str(r.get("title") or ""),
                    str(r.get("status") or ""),
                    str(r.get("local") or ""),
                    str(r.get("camera_ip") or ""),
                    str(r.get("camera_mac") or r.get("mac_camera") or r.get("mac") or ""),
                    str(r.get("camera_model") or r.get("modelo") or ""),
                    str(r.get("snapshot_url") or ""),
                    str(r.get("imgbb_url") or ""),
                    json.dumps(r, ensure_ascii=False),
                ),
            )
            ch_seen += 1
    return {"ok": True, "recorders_upserted": rec_seen, "channels_upserted": ch_seen}


def clear_inventory_source(source: str) -> Dict[str, Any]:
    src = str(source or "").strip().lower()
    if src not in ("ip", "dvr", "nvr"):
        raise ValueError("source invalido (use ip|dvr|nvr)")
    init_db()
    tenant = _current_tenant_slug()
    with _conn() as c:
        if src == "ip":
            n = int(c.execute("DELETE FROM ip_cameras WHERE tenant_slug=?", (tenant,)).rowcount or 0)
            return {"ok": True, "source": src, "deleted": n}
        rec_ids = [
            int(r["id"])
            for r in c.execute("SELECT id FROM recorders WHERE tenant_slug=? AND source=?", (tenant, src)).fetchall()
        ]
        if rec_ids:
            c.execute("DELETE FROM recorder_channels WHERE recorder_id IN ({})".format(",".join(["?"] * len(rec_ids))), rec_ids)
        nrec = int(c.execute("DELETE FROM recorders WHERE tenant_slug=? AND source=?", (tenant, src)).rowcount or 0)
        return {"ok": True, "source": src, "deleted_recorders": nrec}


def replace_ip_inventory_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    clear_inventory_source("ip")
    return upsert_ip_inventory_rows(rows)


def replace_recorder_inventory_rows(source: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    clear_inventory_source(source)
    return upsert_recorder_inventory_rows(source, rows)


def legacy_rows_from_db(source: str = "ip", site: str = "") -> List[Dict[str, Any]]:
    src = str(source or "ip").strip().lower()
    if src not in ("ip", "dvr", "nvr"):
        src = "ip"
    want_site = str(site or "").strip()
    tenant = _current_tenant_slug()
    if _db_backend() == "sqlite" and not SIGHTOPS_DB_PATH.exists():
        return []
    with _conn() as c:
        if src == "ip":
            q = """
            SELECT ic.raw_json, COALESCE(s.name, '') AS site_name
            FROM ip_cameras ic
            LEFT JOIN sites s ON s.id = ic.site_id
            WHERE ic.tenant_slug = ?
              AND (? = '' OR s.name = ? OR lower(trim(ic.local)) = lower(trim(?)))
            ORDER BY ic.ip
            """
            rows = c.execute(q, (tenant, want_site, want_site, want_site)).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                raw = str(r["raw_json"] or "").strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    site_name = str(r["site_name"] or "").strip()
                    if site_name:
                        obj["site"] = site_name
                        obj["site_name"] = site_name
                    out.append(obj)
            return out

        q2 = """
        SELECT rc.raw_json, COALESCE(s.name, '') AS site_name, r.host, r.http_port, rc.channel
        FROM recorder_channels rc
        JOIN recorders r ON r.id = rc.recorder_id
        LEFT JOIN sites s ON s.id = r.site_id
        WHERE r.tenant_slug = ?
          AND r.source = ? AND (? = '' OR s.name = ? OR lower(trim(COALESCE(rc.local, r.local, ''))) = lower(trim(?)))
        ORDER BY r.host, rc.channel
        """
        rows2 = c.execute(q2, (tenant, src, want_site, want_site, want_site)).fetchall()
        out2: List[Dict[str, Any]] = []
        for r in rows2:
            raw = str(r["raw_json"] or "").strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            if isinstance(obj, dict):
                site_name = str(r["site_name"] or "").strip()
                if site_name:
                    obj["site"] = site_name
                    obj["site_name"] = site_name
                out2.append(obj)
        return out2


def decorate_legacy_rows(source: str, rows: List[Dict[str, Any]], site: str = "") -> List[Dict[str, Any]]:
    src = str(source or "ip").strip().lower()
    want_site = str(site or "").strip().lower()
    tenant = _current_tenant_slug()
    if not rows:
        return []
    if _db_backend() == "sqlite" and not SIGHTOPS_DB_PATH.exists():
        return rows if not want_site else []
    out: List[Dict[str, Any]] = []
    with _conn() as c:
        if src == "ip":
            mrows = c.execute(
                """
                SELECT ic.ip, COALESCE(s.name, '') AS site_name
                FROM ip_cameras ic
                LEFT JOIN sites s ON s.id = ic.site_id
                WHERE ic.tenant_slug = ?
                """
                ,
                (tenant,),
            ).fetchall()
            site_map = {str(r["ip"]): str(r["site_name"] or "") for r in mrows}
            for r in rows:
                if not isinstance(r, dict):
                    continue
                ip = str(r.get("ip") or r.get("host") or "").strip()
                row_site = site_map.get(ip, "")
                rr = dict(r)
                if row_site:
                    rr["site"] = row_site
                    rr["site_name"] = row_site
                if want_site and str(row_site or "").strip().lower() != want_site:
                    continue
                out.append(rr)
            return out

        mrows2 = c.execute(
            """
            SELECT r.source, r.host, r.http_port, rc.channel, COALESCE(s.name, '') AS site_name
            FROM recorders r
            LEFT JOIN recorder_channels rc ON rc.recorder_id = r.id
            LEFT JOIN sites s ON s.id = r.site_id
            WHERE r.tenant_slug = ? AND r.source = ?
            """,
            (tenant, src),
        ).fetchall()
        site_map2 = {}
        for mr in mrows2:
            key = (str(mr["host"]), int(mr["http_port"] or 80), int(mr["channel"] or 0))
            site_map2[key] = str(mr["site_name"] or "")

        for r in rows:
            if not isinstance(r, dict):
                continue
            host = str(r.get("host") or r.get("ip") or "").strip()
            port = int(r.get("http_port") or 80)
            ch = int(r.get("channel") or 0)
            row_site = site_map2.get((host, port, ch), "")
            rr = dict(r)
            if row_site:
                rr["site"] = row_site
                rr["site_name"] = row_site
            if want_site and str(row_site or "").strip().lower() != want_site:
                continue
            out.append(rr)
    return out
