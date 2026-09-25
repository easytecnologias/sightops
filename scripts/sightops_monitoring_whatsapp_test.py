from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import MagicMock, patch


def _shim_broken_olt_service() -> None:
    """app/cli/tools/olt_4840e_collect_macs.py esta com um refactor incompleto
    (varios nomes que app/services/olt_service.py e app/cli/tools/olt_vsol_epon.py
    esperam importar nao existem mais no arquivo) -- isso e trabalho de terceiros
    em andamento, sem relacao com Controle de Acesso/WhatsApp, e nao deve ser
    tocado aqui. refresh_from_inventory() importa app.services.olt_service so
    para o bloco de OLT/ONU (fora do escopo deste teste), entao "pre-populamos"
    esse modulo no sys.modules com um shim minimo antes de importar qualquer
    coisa -- isso evita que o Python execute a cadeia de import quebrada, sem
    tocar em nenhum arquivo real. Se este shim comecar a falhar porque
    refresh_from_inventory() passou a depender de mais funcoes de list_macs,
    isso e sinal de que o bloco de OLT mudou -- nao que este teste esta errado.
    """
    if "app.services.olt_service" in sys.modules:
        return
    fake = types.ModuleType("app.services.olt_service")
    fake.list_macs = lambda *a, **k: {"rows": []}
    sys.modules["app.services.olt_service"] = fake


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _shim_broken_olt_service()

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-monitoring-whatsapp.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-monitoring-whatsapp-test-key"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.db_store import save_app_settings
        from app.services.access_control_notifications import list_access_whatsapp_channels

        token = set_current_tenant_slug("escola-whatsapp-test")
        try:
            save_app_settings({
                # Canal "Padrao do cliente": credencial propria, sem site
                # associado -- exercita o caminho site="" de
                # list_access_whatsapp_channels() e o entity_key sentinela
                # "whatsapp:__default__" (a colisao que motivou o fix aqui:
                # antes o fallback era a string literal "default", que colide
                # com um site real chamado "default").
                "access_control_whatsapp_notifications": {
                    "phone_number_id": "333333",
                    "access_token": "token-padrao-cliente",
                    "template_name": "aviso_acesso_aluno",
                },
                "access_control_whatsapp_notifications_by_site": {
                    "ESCOLA A": {
                        "phone_number_id": "111111",
                        "access_token": "token-escola-a",
                        "template_name": "aviso_acesso_aluno",
                    },
                    "ESCOLA B": {
                        "phone_number_id": "222222",
                        "access_token": "token-escola-b",
                        "template_name": "aviso_acesso_aluno",
                    },
                },
            })

            fake_ok = MagicMock(status_code=200)
            fake_ok.json.return_value = {"display_phone_number": "+55 82 90000-0000", "quality_rating": "GREEN"}
            fake_fail = MagicMock(status_code=401)
            fake_fail.json.return_value = {"error": {"message": "token invalido"}}

            def fake_get(url: str, **kwargs):
                # ESCOLA B tem token invalido -- simula token expirado/errado
                return fake_fail if "222222" in url else fake_ok

            with patch("app.services.access_control_notifications.requests.get", side_effect=fake_get):
                channels = list_access_whatsapp_channels()

            by_site = {c["site"]: c for c in channels}
            assert len(channels) == 3, f"esperado 3 canais configurados, veio {len(channels)}"
            assert by_site["ESCOLA A"]["connected"] is True, by_site["ESCOLA A"]
            assert by_site["ESCOLA B"]["connected"] is False, by_site["ESCOLA B"]
            assert by_site["ESCOLA B"]["configured"] is True, by_site["ESCOLA B"]
            assert "" in by_site, "esperado canal 'Padrao do cliente' com site==''"
            assert by_site[""]["configured"] is True, by_site[""]
            assert by_site[""]["connected"] is True, by_site[""]
            # o rotulo do canal padrao inclui o slug do tenant para nao colidir
            # no nome visivel do Zabbix entre clientes diferentes (ver
            # list_access_whatsapp_channels() em access_control_notifications.py)
            assert by_site[""]["label"] == "Padrao do cliente (escola-whatsapp-test)", by_site[""]
            print("OK: list_access_whatsapp_channels devolve um canal por site configurado")

            from app.services.monitoring_service import refresh_from_inventory
            from app.services.monitoring_service import list_entities as list_monitoring_entities

            with patch("app.services.access_control_notifications.requests.get", side_effect=fake_get):
                refresh_from_inventory()

            rows = list_monitoring_entities(entity_type="whatsapp")
            by_site2 = {r["site"]: r["status"] for r in rows}
            by_key2 = {r["entity_key"]: r for r in rows}
            assert by_site2.get("ESCOLA A") == "up", by_site2
            assert by_site2.get("ESCOLA B") == "down", by_site2
            assert by_site2.get("") == "up", by_site2
            # entity_key tem que usar o sentinel "__default__", nunca a string
            # literal "default" -- essa era a colisao: um site real chamado
            # "default" geraria o mesmo entity_key do canal global e um dos
            # dois sumiria da lista (upsert por tenant_slug+entity_key).
            assert "whatsapp:__default__" in by_key2, by_key2.keys()
            assert by_key2["whatsapp:__default__"]["site"] == "", by_key2["whatsapp:__default__"]
            assert len(rows) == 3, f"esperado 3 canais monitorados, veio {len(rows)}"
            print("OK: canais WhatsApp aparecem em monitoring_entities com status certo")
        finally:
            reset_current_tenant_slug(token)


if __name__ == "__main__":
    main()
