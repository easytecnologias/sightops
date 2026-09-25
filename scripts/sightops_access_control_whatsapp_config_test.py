"""Configuracao do WhatsApp do Controle de Acesso (Cloud API oficial).

Substitui a versao anterior, que exercitava QR Code, instancia e desconexao --
conceitos da Evolution API, removida do sistema. No canal oficial nao ha sessao
para parear nem para cair: a autenticacao e um token permanente, e o que precisa
ser verificado e outro.

Cobre:
  - salvar e reler a configuracao, global e por site;
  - o token nunca voltar para a tela;
  - site sem configuracao propria nao herdar a de outro site;
  - o estado do canal refletir credencial ausente e credencial presente;
  - o resumo (usado pelo indicador do topo) achar uma escola configurada,
    enquanto o painel respeita o site escolhido.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-access-control-whatsapp-config.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-whatsapp-config-test-key"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services.access_control_notifications import (
            get_access_whatsapp_config,
            get_access_whatsapp_connection,
            save_access_whatsapp_config,
        )

        chamadas: list[str] = []

        class RespostaMeta:
            ok = True
            status_code = 200
            text = ""

            def __init__(self, dados: dict[str, Any]) -> None:
                self._dados = dados
                self.content = b"{}"

            def json(self) -> dict[str, Any]:
                return self._dados

        def fake_get(url: str, **kwargs: Any) -> RespostaMeta:
            chamadas.append(url)
            if "/message_templates" in url:
                return RespostaMeta({"data": [{"name": "aviso_acesso_aluno", "status": "APPROVED"}]})
            return RespostaMeta({
                "display_phone_number": "+55 82 9369-0487",
                "verified_name": "Escola Segura",
                "quality_rating": "GREEN",
            })

        import requests

        get_original = requests.get
        requests.get = fake_get
        token = set_current_tenant_slug("escola-oficial")
        try:
            # --- sem credencial, o canal nao se diz pronto
            vazio = get_access_whatsapp_connection()
            assert vazio["configured"] is False, vazio
            assert vazio["state"] == "not_configured", vazio

            # --- configuracao global
            salvo = save_access_whatsapp_config({
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "1299130376610413",
                "waba_id": "1728641351582658",
                "access_token": "token-secreto",
                "template_name": "aviso_acesso_aluno",
                "template_language": "pt_BR",
            })
            assert salvo["configured"] is True, salvo
            assert salvo["provider"] == "cloud_api", salvo
            assert salvo["phone_number_id"] == "1299130376610413", salvo
            # o token e gravado mas nunca devolvido
            assert "access_token" not in salvo, salvo
            assert salvo["token_saved"] is True, salvo

            relido = get_access_whatsapp_config()
            assert relido["template_name"] == "aviso_acesso_aluno", relido
            assert "access_token" not in relido, relido

            # --- salvar sem repetir o token mantem o que ja estava
            resalvo = save_access_whatsapp_config({
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "1299130376610413",
                "template_name": "aviso_acesso_aluno",
            })
            assert resalvo["token_saved"] is True, resalvo

            # --- configuracao por site
            save_access_whatsapp_config({
                "site": "ESCOLA A",
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "111111111111111",
                "waba_id": "1728641351582658",
                "access_token": "token-a",
                "template_name": "aviso_acesso_aluno",
            })
            site_a = get_access_whatsapp_config("ESCOLA A")
            assert site_a["phone_number_id"] == "111111111111111", site_a
            assert site_a["site_configured"] is True, site_a

            # Atencao: campo em branco na configuracao do site sobrescreve o
            # global. Salvar um site sem waba_id apaga o herdado, e o estado do
            # template deixa de ser consultavel para aquele site.

            # site sem configuracao propria cai no global, sem herdar da ESCOLA A
            site_b = get_access_whatsapp_config("ESCOLA B")
            assert site_b["site_configured"] is False, site_b
            assert site_b["phone_number_id"] == "1299130376610413", site_b

            # --- estado do canal: dados vindos da Meta
            conexao = get_access_whatsapp_connection(site="ESCOLA A")
            assert conexao["configured"] is True, conexao
            assert conexao["display_phone_number"] == "+55 82 9369-0487", conexao
            assert conexao["verified_name"] == "Escola Segura", conexao
            assert conexao["quality_rating"] == "GREEN", conexao
            assert conexao["template_status"] == "APPROVED", conexao
            assert conexao["qrcode"] == "", conexao   # nao existe QR no canal oficial

            # --- resumo x painel: o indicador do topo procura uma escola
            # configurada; o painel mostra so o site escolhido
            resumo = get_access_whatsapp_connection(resumo=True)
            assert resumo["configured"] is True, resumo
            assert "ESCOLA A" in (resumo.get("configured_sites") or []), resumo
        finally:
            requests.get = get_original
            reset_current_tenant_slug(token)

    print("access-control whatsapp config (cloud api) ok")


if __name__ == "__main__":
    main()
