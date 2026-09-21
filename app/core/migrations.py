"""Runner de migrations versionadas.

Existe para garantir uma propriedade so: **banco novo e banco existente passam
pela mesma sequencia de migrations e terminam com o schema identico**.

O modelo anterior (CREATE TABLE IF NOT EXISTS + funcoes _ensure_*_schema) nao
garantia isso: num banco vazio o CREATE definia o schema final, num banco ja
populado ele virava no-op e o schema real passava a depender das funcoes de
remendo. Os dois caminhos divergiram em producao -- e nada detectava.

Regras:
  - migrations sao arquivos .sql numerados, por componente e por backend:
        migrations/<componente>/<backend>/<versao>_<nome>.sql
  - toda migration aplicada fica registrada em `schema_migrations` com checksum;
    editar uma migration ja aplicada e erro, nao "atualizacao".
  - cada migration roda dentro de uma transacao. Falhou, nada daquela versao fica.
  - banco pre-existente sem `schema_migrations` e "adotado": a versao baseline e
    carimbada como aplicada sem rodar, e a execucao segue da proxima. E o que
    permite migrar producao sem recriar o banco.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Sequence

logger = logging.getLogger("app.migrations")

MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"

_FILENAME_RE = re.compile(r"^(\d{3,})_([a-z0-9_]+)\.sql$")

# Chave do advisory lock do Postgres. Constante arbitraria, so precisa ser
# estavel entre processos.
_PG_LOCK_KEY = 8110723

# `component` faz parte da chave, nao so `version`.
#
# Sem isso, `main` e `auth` compartilhando o mesmo banco colidem: a 001 do main
# e a 001 do auth disputam a mesma linha, e a segunda a rodar falha com "ja
# aplicada com outro conteudo". E o caso da producao -- AUTH_DATABASE_URL nao e
# definida, entao o auth cai no mesmo banco do main. O modelo antigo (version
# como chave) so funcionava com bancos separados, que era uma suposicao nao
# declarada em lugar nenhum.
#
# UNIQUE INDEX em vez de PRIMARY KEY composta pra manter o DDL identico nos dois
# backends -- e porque indice nomeado e o que a licao da migration 001 mandou.
_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    component TEXT NOT NULL DEFAULT 'main',
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    adopted INTEGER NOT NULL DEFAULT 0
)
"""

_SCHEMA_MIGRATIONS_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS schema_migrations_component_version_uq
    ON schema_migrations(component, version)
"""


class MigrationError(RuntimeError):
    pass


def _q(backend: str, sql: str) -> str:
    """Traduz as queries internas do runner para o dialeto do backend.

    O runner recebe conexoes de origens diferentes (wrapper do db_store, psycopg
    cru do auth_store), entao nao pode contar com o chamador pra traduzir.
    Aplicar duas vezes e inofensivo: depois da primeira nao sobra '?'.
    """
    if str(backend or "sqlite").strip().lower() != "postgres":
        return sql
    return sql.replace("?", "%s").replace("datetime('now')", "CURRENT_TIMESTAMP")


class Migration(NamedTuple):
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def split_sql_statements(sql: str) -> List[str]:
    """Quebra um script SQL em statements.

    Precisa existir porque split(';') ingenuo corta no meio de bloco
    dollar-quoted ($$ ... $$), que e exatamente o que uma migration de DDL
    condicional no Postgres usa.
    """
    statements: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(sql or "")

    while i < n:
        ch = sql[i]

        # comentario de linha
        if ch == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            i = n if end < 0 else end
            continue

        # comentario de bloco
        if ch == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue

        # string literal / identificador entre aspas
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql[i] == quote:
                    # aspas duplicadas dentro da string ('' ou "") sao escape
                    if i + 1 < n and sql[i + 1] == quote:
                        buf.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        # bloco dollar-quoted: $$ ... $$ ou $tag$ ... $tag$
        if ch == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if match:
                tag = match.group(0)
                end = sql.find(tag, i + len(tag))
                if end < 0:
                    raise MigrationError(f"bloco dollar-quoted {tag} sem fechamento")
                buf.append(sql[i : end + len(tag)])
                i = end + len(tag)
                continue

        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _checksum(sql: str) -> str:
    normalized = "\n".join(line.rstrip() for line in str(sql or "").replace("\r\n", "\n").split("\n")).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def load_migrations(component: str, backend: str, root: Path | None = None) -> List[Migration]:
    base = (root or MIGRATIONS_ROOT) / str(component).strip() / str(backend).strip().lower()
    if not base.is_dir():
        raise MigrationError(f"diretorio de migrations nao encontrado: {base}")

    out: List[Migration] = []
    seen: Dict[int, Path] = {}
    for path in sorted(base.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"nome de migration invalido: {path.name} (use 001_nome_em_snake_case.sql)")
        version = int(match.group(1))
        if version in seen:
            raise MigrationError(f"versao {version} duplicada: {seen[version].name} e {path.name}")
        seen[version] = path
        sql = path.read_text(encoding="utf-8")
        out.append(Migration(version=version, name=match.group(2), path=path, sql=sql, checksum=_checksum(sql)))

    out.sort(key=lambda m: m.version)
    if not out:
        raise MigrationError(f"nenhuma migration em {base}")
    return out


def _table_exists(conn: Any, backend: str, table: str) -> bool:
    try:
        if str(backend).strip().lower() == "postgres":
            row = conn.execute(
                _q(backend, "SELECT 1 AS ok FROM information_schema.tables "
                            "WHERE table_name = ? AND table_schema NOT IN ('pg_catalog', 'information_schema')"),
                (table,),
            ).fetchone()
        else:
            row = conn.execute(
                _q(backend, "SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = ?"),
                (table,),
            ).fetchone()
        return row is not None
    except Exception:
        return False


def _applied(conn: Any, backend: str, component: str) -> Dict[int, str]:
    rows = conn.execute(
        _q(backend, "SELECT version, checksum FROM schema_migrations WHERE component = ?"),
        (component,),
    ).fetchall()
    out: Dict[int, str] = {}
    for row in rows or []:
        item = dict(row)
        out[int(item["version"])] = str(item.get("checksum") or "")
    return out


def _record(conn: Any, backend: str, component: str, migration: Migration, adopted: bool) -> None:
    conn.execute(
        _q(backend, "INSERT INTO schema_migrations(component, version, name, checksum, adopted) VALUES(?, ?, ?, ?, ?)"),
        (component, migration.version, migration.name, migration.checksum, 1 if adopted else 0),
    )


def _column_exists(conn: Any, backend: str, table: str, column: str) -> bool:
    try:
        if str(backend).strip().lower() == "postgres":
            row = conn.execute(
                _q(backend, "SELECT 1 AS ok FROM information_schema.columns "
                            "WHERE table_name = ? AND column_name = ?"),
                (table, column),
            ).fetchone()
            return row is not None
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(dict(r).get("name")) == column for r in rows or [])
    except Exception:
        return False


def _drop_legacy_registry(conn: Any, backend: str) -> bool:
    """Remove uma `schema_migrations` no formato antigo (sem `component`).

    O formato antigo usava `version` como chave, o que impede main e auth de
    conviverem no mesmo banco. Recriar a tabela e seguro porque a adocao a
    reconstroi: as tabelas de dados ja existem, entao a baseline e carimbada sem
    rodar, e as migrations posteriores sao idempotentes (CREATE TABLE IF NOT
    EXISTS / ADD COLUMN IF NOT EXISTS). Nenhum dado de negocio e tocado.
    """
    if not _table_exists(conn, backend, "schema_migrations"):
        return False
    if _column_exists(conn, backend, "schema_migrations", "component"):
        return False
    logger.warning(
        "schema_migrations em formato antigo (sem coluna component): recriando. "
        "As versoes serao readotadas a partir do estado real do banco."
    )
    conn.execute("DROP TABLE schema_migrations")
    _commit(conn)
    return True


def _commit(conn: Any) -> None:
    try:
        conn.commit()
    except Exception:
        pass


def _rollback(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def apply_migrations(
    conn: Any,
    backend: str,
    component: str,
    adopt_probe_tables: Sequence[str] = (),
    postconditions: Dict[int, Any] | None = None,
    root: Path | None = None,
) -> Dict[str, Any]:
    """Aplica as migrations pendentes de `component` na conexao dada.

    `adopt_probe_tables`: se `schema_migrations` nao existir mas alguma dessas
    tabelas existir, o banco e pre-existente -- a baseline e carimbada em vez de
    executada. Lista vazia = banco novo sempre.

    `postconditions`: {versao: fn(conn, backend) -> bool}. Num banco adotado, a
    versao tambem e carimbada se a pos-condicao dela ja estiver satisfeita.
    Serve pra banco que ja recebeu a mudanca por outro caminho (remendo antigo)
    e nao deve reexecutar. Se a pos-condicao for falsa, a migration roda normal.
    """
    backend_norm = str(backend or "sqlite").strip().lower()
    migrations = load_migrations(component, backend_norm, root=root)
    baseline = migrations[0]
    checks = dict(postconditions or {})

    locked = False
    if backend_norm == "postgres":
        conn.execute(_q(backend_norm, "SELECT pg_advisory_lock(?)"), (_PG_LOCK_KEY,))
        locked = True

    try:
        _drop_legacy_registry(conn, backend_norm)
        had_registry = _table_exists(conn, backend_norm, "schema_migrations")
        conn.execute(_q(backend_norm, _SCHEMA_MIGRATIONS_DDL))
        conn.execute(_q(backend_norm, _SCHEMA_MIGRATIONS_INDEX_DDL))
        _commit(conn)

        # "Registro novo" e por componente, nao pela tabela: com main e auth no
        # mesmo banco, a tabela ja existe quando o segundo componente roda, mas
        # ele ainda precisa passar pela adocao.
        ja_registrado = bool(had_registry and _applied(conn, backend_norm, component))

        adopted: List[int] = []
        if not ja_registrado and any(_table_exists(conn, backend_norm, t) for t in adopt_probe_tables):
            # Banco pre-existente: a baseline descreve o que ele ja e.
            _record(conn, backend_norm, component, baseline, adopted=True)
            adopted.append(baseline.version)

            # Migrations posteriores que este banco ja satisfaz (porque a mudanca
            # chegou por um remendo anterior) tambem sao carimbadas. As que nao
            # satisfazem ficam pendentes e rodam normalmente logo abaixo.
            for migration in migrations[1:]:
                probe = checks.get(migration.version)
                if probe is None:
                    break
                try:
                    satisfied = bool(probe(conn, backend_norm))
                except Exception:
                    satisfied = False
                if not satisfied:
                    break
                _record(conn, backend_norm, component, migration, adopted=True)
                adopted.append(migration.version)

            _commit(conn)
            logger.info(
                "migrations[%s/%s]: banco pre-existente adotado nas versoes %s",
                component,
                backend_norm,
                adopted,
            )

        applied = _applied(conn, backend_norm, component)
        applied_now: List[int] = []

        for migration in migrations:
            known = applied.get(migration.version)
            if known is not None:
                if known != migration.checksum:
                    raise MigrationError(
                        f"migration {migration.version:03d}_{migration.name} ja aplicada com outro conteudo "
                        f"(esperado {known}, arquivo {migration.checksum}). "
                        "Migration aplicada nao se edita: crie uma nova versao."
                    )
                continue

            statements = split_sql_statements(migration.sql)
            # SQLite: DDL do modulo sqlite3 roda em autocommit se nenhuma
            # transacao estiver aberta, entao a migration nao seria atomica sem
            # o BEGIN explicito. E foreign_keys precisa cair FORA da transacao
            # (dentro dela o PRAGMA e ignorado), que e o procedimento oficial de
            # rebuild de tabela do SQLite.
            if backend_norm != "postgres":
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.execute("BEGIN")
            try:
                for stmt in statements:
                    conn.execute(stmt)
                _record(conn, backend_norm, component, migration, adopted=False)
                _commit(conn)
            except Exception as exc:
                _rollback(conn)
                raise MigrationError(
                    f"falha na migration {migration.version:03d}_{migration.name}: {exc}"
                ) from exc
            finally:
                if backend_norm != "postgres":
                    conn.execute("PRAGMA foreign_keys=ON")

            if backend_norm != "postgres":
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise MigrationError(
                        f"migration {migration.version:03d}_{migration.name} deixou "
                        f"{len(broken)} violacao(oes) de foreign key"
                    )

            applied[migration.version] = migration.checksum
            applied_now.append(migration.version)
            logger.info("migrations[%s/%s]: aplicada %03d_%s", component, backend_norm, migration.version, migration.name)

        return {
            "component": component,
            "backend": backend_norm,
            "current_version": max(applied) if applied else 0,
            "applied_now": applied_now,
            "adopted": adopted,
        }
    finally:
        if locked:
            try:
                conn.execute(_q(backend_norm, "SELECT pg_advisory_unlock(?)"), (_PG_LOCK_KEY,))
                _commit(conn)
            except Exception:
                pass
