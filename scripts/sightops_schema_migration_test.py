"""Prova que banco novo e banco antigo migrado terminam com o schema identico.

Este e o teste que faltava. O bug que motivou o runner de migrations (UNIQUE(ip)
legado sobrevivendo em producao enquanto uma instalacao nova nascia sem ele)
existia porque nada comparava os dois caminhos. Aqui a comparacao e o teste.

Roda direto:  python scripts/sightops_schema_migration_test.py
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Schema anterior ao trabalho multi-tenant: sem tenant_slug, com as UNIQUE
# globais. E o que a producao tinha antes do remendo.
_LEGACY_SCHEMA = """
CREATE TABLE sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE settings_kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE json_state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE ip_cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    ip TEXT NOT NULL,
    host TEXT DEFAULT '',
    http_port INTEGER DEFAULT 80,
    title TEXT DEFAULT '',
    local TEXT DEFAULT '',
    status TEXT DEFAULT '',
    mac TEXT DEFAULT '',
    fabricante TEXT DEFAULT '',
    modelo TEXT DEFAULT '',
    snapshot_url TEXT DEFAULT '',
    imgbb_url TEXT DEFAULT '',
    raw_json TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ip)
);
CREATE TABLE recorders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    host TEXT NOT NULL,
    http_port INTEGER NOT NULL DEFAULT 80,
    mac TEXT DEFAULT '',
    modelo TEXT DEFAULT '',
    fabricante TEXT DEFAULT '',
    local TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, host, http_port)
);
CREATE TABLE recorder_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorder_id INTEGER NOT NULL REFERENCES recorders(id) ON DELETE CASCADE,
    channel INTEGER NOT NULL,
    title TEXT DEFAULT '',
    status TEXT DEFAULT '',
    local TEXT DEFAULT '',
    camera_ip TEXT DEFAULT '',
    camera_mac TEXT DEFAULT '',
    camera_model TEXT DEFAULT '',
    snapshot_url TEXT DEFAULT '',
    imgbb_url TEXT DEFAULT '',
    raw_json TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(recorder_id, channel)
);
"""

_FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        _FAILURES.append(message)


def _connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON;")
    return c


def _schema_snapshot(conn: sqlite3.Connection) -> dict[str, str]:
    """Schema normalizado, comparavel entre dois bancos."""
    out: dict[str, str] = {}
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "AND name <> 'schema_migrations'"
    ).fetchall()
    for row in rows:
        sql = re.sub(r"\s+", " ", str(row["sql"] or "")).strip()
        # nome do indice implicito de UNIQUE nao importa; a definicao importa
        out[f"{row['type']}:{row['name']}"] = sql
    return out


def _seed_legacy(conn: sqlite3.Connection) -> None:
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute("INSERT INTO sites(id, name) VALUES(1, 'Jardins')")
    conn.execute("INSERT INTO sites(id, name) VALUES(2, 'Centro')")
    for i in range(1, 6):
        conn.execute(
            "INSERT INTO ip_cameras(id, site_id, ip, title) VALUES(?, 1, ?, ?)",
            (i, f"10.10.8.{i}", f"CAM {i:02d}"),
        )
    conn.execute("INSERT INTO recorders(id, site_id, source, host, http_port) VALUES(1, 1, 'nvr', '10.10.9.1', 80)")
    conn.execute("INSERT INTO recorder_channels(id, recorder_id, channel, title) VALUES(1, 1, 1, 'Canal 01')")
    conn.commit()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sightops-schema-test-"))
    try:
        _run(tmp)
    except Exception as exc:
        # Schema divergente costuma estourar antes do fim (coluna que nao existe
        # no caminho quebrado). Isso e falha de teste, nao crash do teste.
        _FAILURES.append(f"excecao durante o teste: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if _FAILURES:
        print(f"FALHOU ({len(_FAILURES)}):")
        for item in _FAILURES:
            print(f"  - {item}")
        return 1
    print("OK schema migrations: banco novo e banco legado migrado tem schema identico")
    return 0


def _run(tmp: Path) -> None:
    fresh = legacy = None
    try:
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["DATA_DIR"] = str(tmp)
        from app.core.migrations import apply_migrations, load_migrations
        from app.services.db_store import _tenant_scoped_keys_satisfied

        kwargs = dict(
            backend="sqlite",
            component="main",
            adopt_probe_tables=("sites", "ip_cameras", "recorders"),
            postconditions={2: _tenant_scoped_keys_satisfied},
        )

        # --- caminho A: banco novo, do zero ---
        fresh = _connect(tmp / "fresh.db")
        status_fresh = apply_migrations(fresh, **kwargs)
        check(status_fresh["adopted"] == [], f"banco novo nao deveria adotar nada: {status_fresh}")
        # Sem numero fixo: o banco novo tem que rodar TODAS as migrations, quantas
        # existirem. Fixar [1, 2] fazia este teste quebrar a cada migration nova,
        # sem que nada estivesse errado -- e teste que grita por engano acaba
        # ignorado, que e o oposto do que ele serve.
        todas = [m.version for m in load_migrations("main", "sqlite")]
        check(status_fresh["applied_now"] == todas, f"banco novo deveria rodar todas as migrations {todas}: {status_fresh}")

        # --- caminho B: banco legado, adotado e migrado ---
        legacy = _connect(tmp / "legacy.db")
        _seed_legacy(legacy)
        status_legacy = apply_migrations(legacy, **kwargs)
        check(status_legacy["adopted"] == [1], f"banco legado deveria adotar so a baseline: {status_legacy}")
        # O legado adota a baseline e roda o resto: tudo menos a 001.
        resto = [v for v in todas if v != 1]
        check(status_legacy["applied_now"] == resto, f"banco legado deveria rodar {resto}: {status_legacy}")

        # --- a asercao que importa ---
        schema_fresh = _schema_snapshot(fresh)
        schema_legacy = _schema_snapshot(legacy)
        for key in sorted(set(schema_fresh) | set(schema_legacy)):
            a = schema_fresh.get(key)
            b = schema_legacy.get(key)
            check(a == b, f"schema divergente em {key}:\n  novo    = {a}\n  migrado = {b}")

        # --- dado sobreviveu a migracao ---
        cams = legacy.execute("SELECT COUNT(1) AS n FROM ip_cameras").fetchone()["n"]
        sites = legacy.execute("SELECT COUNT(1) AS n FROM sites").fetchone()["n"]
        chans = legacy.execute("SELECT COUNT(1) AS n FROM recorder_channels").fetchone()["n"]
        check(cams == 5, f"esperado 5 cameras apos migracao, veio {cams}")
        check(sites == 2, f"esperado 2 sites apos migracao, veio {sites}")
        check(chans == 1, f"esperado 1 canal apos migracao, veio {chans}")
        slugs = {r["tenant_slug"] for r in legacy.execute("SELECT DISTINCT tenant_slug FROM ip_cameras").fetchall()}
        check(slugs == {"default"}, f"tenant_slug apos migracao deveria ser default, veio {slugs}")

        # --- a UNIQUE legada tem que ter sumido nos dois ---
        for label, conn in (("novo", fresh), ("migrado", legacy)):
            ddl = " ".join(
                str(r["sql"] or "")
                for r in conn.execute(
                    "SELECT sql FROM sqlite_master WHERE name IN ('sites','ip_cameras','recorders')"
                ).fetchall()
            )
            for chunk in re.findall(r"UNIQUE\s*\(([^)]*)\)", ddl, flags=re.IGNORECASE):
                check(
                    "tenant_slug" in chunk.lower(),
                    f"banco {label} ainda tem UNIQUE sem tenant_slug: UNIQUE({chunk.strip()})",
                )

        # --- dois tenants com o mesmo IP: o objetivo de tudo isso ---
        legacy.execute(
            "INSERT INTO ip_cameras(tenant_slug, ip, title) VALUES('cliente-b', '10.10.8.1', 'CAM do outro cliente')"
        )
        legacy.commit()
        n = legacy.execute("SELECT COUNT(1) AS n FROM ip_cameras WHERE ip='10.10.8.1'").fetchone()["n"]
        check(n == 2, f"mesmo IP em dois tenants deveria coexistir, veio {n} linha(s)")

        # --- rodar de novo nao faz nada (idempotencia) ---
        again = apply_migrations(legacy, **kwargs)
        check(again["applied_now"] == [], f"segunda execucao deveria ser no-op: {again}")

        # --- main e auth no MESMO banco ---
        #
        # E a configuracao da producao: AUTH_DATABASE_URL nao e definida, entao o
        # auth cai no banco do main e os dois dividem a tabela schema_migrations.
        #
        # Nenhum teste cobria isso, e o runner usava `version` como chave -- a 001
        # do auth batia na 001 do main e a API nao subia. So apareceu rodando a
        # imagem contra um Postgres de verdade, ja com tudo publicado.
        compartilhado = _connect(tmp / "compartilhado.db")
        try:
            st_main = apply_migrations(compartilhado, **kwargs)
            st_auth = apply_migrations(
                compartilhado, backend="sqlite", component="auth",
                adopt_probe_tables=("tenants", "users"),
            )
            check(bool(st_main["applied_now"]), f"main deveria ter rodado: {st_main}")
            check(bool(st_auth["applied_now"]), f"auth deveria ter rodado no mesmo banco: {st_auth}")

            linhas = compartilhado.execute(
                "SELECT component, version FROM schema_migrations ORDER BY component, version"
            ).fetchall()
            componentes = {str(dict(r)["component"]) for r in linhas}
            check(componentes == {"main", "auth"},
                  f"schema_migrations deveria ter os dois componentes: {componentes}")

            # a colisao original: versao 1 existe duas vezes, uma por componente
            v1 = [dict(r) for r in linhas if int(dict(r)["version"]) == 1]
            check(len(v1) == 2, f"versao 1 deveria existir para main e auth: {v1}")

            # e as tabelas dos dois componentes convivem
            for tabela in ("sites", "ip_cameras", "olts", "tenants", "users"):
                existe = compartilhado.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)
                ).fetchone()
                check(existe is not None, f"tabela {tabela} faltando no banco compartilhado")
        finally:
            try:
                compartilhado.close()
            except Exception:
                pass
    finally:
        for conn in (fresh, legacy):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
