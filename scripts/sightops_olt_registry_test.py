"""Testa o cadastro de OLT: isolamento entre tenants e sigilo da senha.

As duas propriedades que este cadastro precisa ter pra poder existir:
  - a senha da OLT nunca sai do servidor pelas funcoes de leitura;
  - um tenant nao le, nao edita, nao apaga e nao usa a OLT de outro.

Roda direto:  python scripts/sightops_olt_registry_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="olt-registry-test-"))
    os.environ["DATA_DIR"] = str(tmp / "data")
    os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
    os.environ["DATABASE_BACKEND"] = "sqlite"
    os.environ["SIGHTOPS_SECRET_KEY"] = "chave-de-teste"
    os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
    os.environ.pop("DATABASE_URL", None)

    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services import db_store, olt_registry

    db_store.init_db()

    SENHA = "senha-secreta-da-olt"

    # --- tenant A cadastra uma OLT ---
    tok = set_current_tenant_slug("cliente-a")
    try:
        salvo = olt_registry.save_olt({
            "name": "OLT Centro", "host": "10.0.0.10",
            "vendor": "Fiberhome", "model": "8820i",
            "username": "admin", "password": SENHA,
        })
        olt_id = salvo["id"]
        check("password" not in salvo, f"save_olt vazou a senha: {salvo}")
        check("password_enc" not in salvo, f"save_olt vazou o texto cifrado: {salvo}")
        check(salvo.get("has_password") is True, "has_password deveria ser True")
        check(salvo.get("vendor") == "Fiberhome", "fabricante nao foi gravado")

        lista = olt_registry.list_olts()
        check(len(lista) == 1, f"tenant A deveria ver 1 OLT: {lista}")
        check(all("password" not in o and "password_enc" not in o for o in lista),
              "list_olts vazou senha")

        # a senha esta mesmo cifrada no banco?
        with db_store._conn() as c:
            crua = dict(c.execute("SELECT password_enc FROM olts WHERE id=?", (olt_id,)).fetchone())
        check(SENHA not in str(crua.get("password_enc")), "senha gravada em texto puro no banco!")
        check(str(crua.get("password_enc")).startswith("enc:"), "senha nao foi cifrada")

        # so resolve_credentials abre
        cred = olt_registry.resolve_credentials(olt_id)
        check(cred["password"] == SENHA, "resolve_credentials nao devolveu a senha certa")

        # editar sem mandar senha mantem a que estava
        olt_registry.save_olt({"id": olt_id, "name": "OLT Centro II", "host": "10.0.0.10"})
        check(olt_registry.resolve_credentials(olt_id)["password"] == SENHA,
              "editar sem senha apagou a senha existente")
    finally:
        reset_current_tenant_slug(tok)

    # --- tenant B nao pode alcancar a OLT do A ---
    tok = set_current_tenant_slug("cliente-b")
    try:
        check(olt_registry.list_olts() == [], "tenant B enxergou OLT do tenant A")
        check(olt_registry.get_olt(olt_id) is None, "tenant B leu a OLT do tenant A por id")
        check(olt_registry.delete_olt(olt_id) is False, "tenant B conseguiu apagar OLT do tenant A")
        try:
            olt_registry.resolve_credentials(olt_id)
            FALHAS.append("tenant B conseguiu decifrar a senha da OLT do tenant A")
        except olt_registry.OltNotFound:
            pass

        # e o mesmo IP pode existir em dois clientes
        b = olt_registry.save_olt({"name": "OLT do B", "host": "10.0.0.10", "password": "outra"})
        check(b["id"] != olt_id, "mesmo IP em tenants diferentes colidiu")
    finally:
        reset_current_tenant_slug(tok)

    # --- a OLT do A continua intacta ---
    tok = set_current_tenant_slug("cliente-a")
    try:
        check(olt_registry.resolve_credentials(olt_id)["password"] == SENHA,
              "OLT do tenant A foi afetada pelo tenant B")
    finally:
        reset_current_tenant_slug(tok)

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print("  -", f)
        raise SystemExit(1)
    print("OK cadastro de OLT: senha cifrada e invisivel, tenants isolados")


if __name__ == "__main__":
    main()
