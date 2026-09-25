"""Testa o log de acoes de ONU: grava e le, isolado por tenant e por OLT,
mais recente primeiro.

Roda direto:  python scripts/sightops_onu_action_log_test.py
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
    tmp = Path(tempfile.mkdtemp(prefix="onu-action-log-test-"))
    os.environ["DATA_DIR"] = str(tmp / "data")
    os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
    os.environ["DATABASE_BACKEND"] = "sqlite"
    os.environ["SIGHTOPS_SECRET_KEY"] = "chave-de-teste"
    os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
    os.environ.pop("DATABASE_URL", None)

    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    from app.services import db_store, onu_action_log

    db_store.init_db()

    tok = set_current_tenant_slug("cliente-a")
    try:
        onu_action_log.log_onu_action(
            "add_onu", olt_id=2, olt_ip="10.80.80.2", olt_name="JARDINS I", site="JARDINS I",
            pon=7, onu=2, serial="ITBS2C96E6A7", vlan="3000", ok=True, detail="ITBS 110Gb",
        )
        onu_action_log.log_onu_action(
            "onu_signal", olt_id=2, olt_ip="10.80.80.2", site="JARDINS I",
            pon=7, onu=2, serial="ITBS2C96E6A7", vlan="3000", ok=True,
        )
        onu_action_log.log_onu_action(
            "delete_onu", olt_id=2, olt_ip="10.80.80.2", site="JARDINS I",
            pon=7, onu=2, serial="ITBS2C96E6A7", ok=True,
        )
        # De outra OLT, nao deve aparecer quando filtramos por 10.80.80.2.
        onu_action_log.log_onu_action(
            "add_onu", olt_id=3, olt_ip="10.80.80.5", site="PERUCABA",
            pon=1, onu=1, serial="ITBSAAAAAAAA", ok=False, detail="falhou",
        )

        acoes = onu_action_log.list_onu_actions(olt_ip="10.80.80.2")
        check(len(acoes) == 3, f"esperava 3 acoes da OLT 10.80.80.2, veio {len(acoes)}")
        check(acoes[0]["action"] == "delete_onu", f"mais recente devia ser delete_onu: {acoes[0]}")
        check(acoes[1]["action"] == "onu_signal", f"segunda devia ser onu_signal: {acoes[1]}")
        check(acoes[2]["action"] == "add_onu", f"terceira devia ser add_onu: {acoes[2]}")
        check(acoes[0]["ok"] == 1, f"delete_onu devia estar ok=1: {acoes[0]}")
        check(acoes[2]["vlan"] == "3000", f"add_onu devia ter gravado vlan=3000: {acoes[2]}")
        check(acoes[0]["vlan"] == "", f"delete_onu sem vlan informada devia gravar vazio: {acoes[0]}")

        todas = onu_action_log.list_onu_actions()
        check(len(todas) == 4, f"sem filtro de olt_ip esperava 4 acoes, veio {len(todas)}")

        falha = next((a for a in todas if a["action"] == "add_onu" and a["olt_ip"] == "10.80.80.5"), None)
        check(falha is not None and falha["ok"] == 0, f"acao com falha nao registrou ok=0: {falha}")
        check(falha is not None and falha["detail"] == "falhou", f"detail da falha nao gravou: {falha}")
    finally:
        reset_current_tenant_slug(tok)

    # --- isolamento por tenant ---
    tok_b = set_current_tenant_slug("cliente-b")
    try:
        acoes_b = onu_action_log.list_onu_actions(olt_ip="10.80.80.2")
        check(len(acoes_b) == 0, f"tenant B nao devia ver acoes do tenant A, veio {len(acoes_b)}")
    finally:
        reset_current_tenant_slug(tok_b)

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print(" -", f)
        raise SystemExit(1)
    print("OK: sightops_onu_action_log_test")


if __name__ == "__main__":
    main()
