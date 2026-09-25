"""Confere o ciclo completo do provider Evolution na camada de servico:
envio de notificacao, checagem de conexao (com a interpretacao estrita que
corrige o bug provado ao vivo -- so "open" conta como conectado) e
desconexao. Usa um FakeResponse para simular o Evolution API sem rede.

Roda direto: python scripts/sightops_whatsapp_evolution_service_test.py
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
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-whatsapp-evolution-service.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-whatsapp-evolution-service-test-key"
        os.environ["SIGHTOPS_EVOLUTION_URL"] = "http://evolution.teste:8090"
        os.environ["SIGHTOPS_EVOLUTION_API_KEY"] = "chave-teste"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services import db_store
        from app.services.access_control_notifications import (
            get_access_whatsapp_config,
            get_access_whatsapp_connection,
            disconnect_access_whatsapp,
            notify_access_event,
            save_access_whatsapp_config,
            send_access_whatsapp_text,
            test_access_whatsapp,
        )

        chamadas: list[dict[str, Any]] = []

        class FakeResponse:
            def __init__(self, status_code: int, body: dict[str, Any]):
                self.status_code = status_code
                self._body = body
                self.content = b"1" if body else b""
                self.text = str(body)

            def json(self) -> dict[str, Any]:
                return self._body

        respostas_get: list[FakeResponse] = []
        respostas_delete: list[FakeResponse] = []

        def fake_get(url: str, **kwargs: Any) -> FakeResponse:
            chamadas.append({"metodo": "GET", "url": url, **kwargs})
            return respostas_get.pop(0)

        def fake_post(url: str, **kwargs: Any) -> FakeResponse:
            chamadas.append({"metodo": "POST", "url": url, **kwargs})
            return FakeResponse(201, {"key": {"id": "3EB0"}})

        def fake_delete(url: str, **kwargs: Any) -> FakeResponse:
            chamadas.append({"metodo": "DELETE", "url": url, **kwargs})
            return respostas_delete.pop(0)

        import requests

        original_get, original_post, original_delete = requests.get, requests.post, requests.delete
        requests.get = fake_get
        requests.post = fake_post
        requests.delete = fake_delete
        token = set_current_tenant_slug("escola-evolution")
        try:
            db_store.ensure_schema() if hasattr(db_store, "ensure_schema") else None
            save_access_whatsapp_config({
                "site": "Unidade Centro",
                "enabled": True,
                "provider": "evolution",
            })

            config = get_access_whatsapp_config("Unidade Centro")
            assert config["provider"] == "evolution", config
            assert config["configured"] is True, config
            assert config["instance"] == "escola-evolution-unidade-centro", config
            # o endereco interno do container Evolution nao volta mais para a
            # tela: e infraestrutura da plataforma, e ninguem exibe esse campo
            assert "base_url" not in config, config

            # --- envio de evento passa a usar o Evolution, nao a Meta ---
            chamadas.clear()
            status = notify_access_event({
                "site": "Unidade Centro",
                "device_id": "",
                "person_id": "",
                "person_name_raw": "Aluno Evolution",
                "guardian_phone": "(82) 98888-1111",
                "event_type": "entrada",
                "occurred_at": "2026-08-27 08:00:00",
            })
            envio = next(c for c in chamadas if c["metodo"] == "POST" and "sendText" in c["url"])
            assert envio["url"].endswith("/message/sendText/escola-evolution-unidade-centro"), envio
            assert envio["headers"]["apikey"] == "chave-teste", envio
            assert envio["json"]["number"] == "5582988881111", envio
            assert "whatsapp_sent" in status["statuses"], status
            # o texto tem que ser igual ao template aprovado na Meta
            # (aviso_acesso_aluno), pra ficar com a mesma cara pro responsavel
            # em qualquer um dos dois provedores
            texto = envio["json"]["text"]
            assert texto.startswith("Aviso do controle de acesso.\n\n"), texto
            assert "Evento: ENTRADA\n" in texto, texto
            assert "Escola: Unidade Centro\n" in texto, texto
            assert "Aluno: Aluno Evolution\n" in texto, texto
            assert "Horário: 2026-08-27 08:00:00" in texto, texto
            assert texto.endswith("Não precisa responder"), texto

            # --- resposta direta (send_access_whatsapp_text) tambem usa Evolution ---
            chamadas.clear()
            resposta = send_access_whatsapp_text("5582988881111", "ola", site="Unidade Centro")
            assert resposta["ok"] is True, resposta
            assert any("sendText" in c["url"] for c in chamadas), chamadas

            # --- checagem de conexao: sessao presa em "connecting" NAO pode contar como conectada ---
            respostas_get.clear()
            respostas_get.append(FakeResponse(200, {"instance": {"state": "connecting"}}))
            respostas_get.append(FakeResponse(200, {"base64": "data-fake-qr"}))
            estado = get_access_whatsapp_connection(site="Unidade Centro")
            assert estado["configured"] is True, estado
            assert estado["connected"] is False, estado
            assert estado["state"] == "waiting_qr", estado
            assert estado["qrcode"] == "data-fake-qr", estado

            # --- sessao realmente aberta conta como conectada ---
            respostas_get.clear()
            respostas_get.append(FakeResponse(200, {"instance": {"state": "open"}}))
            estado = get_access_whatsapp_connection(site="Unidade Centro")
            assert estado["connected"] is True, estado
            assert estado["state"] == "connected", estado

            # --- desconectar ---
            respostas_delete.clear()
            respostas_delete.append(FakeResponse(200, {}))
            resultado = disconnect_access_whatsapp("Unidade Centro")
            assert resultado["ok"] is True, resultado
            assert resultado["state"] == "disconnected", resultado

            # --- site sem configuracao de provider continua em cloud_api, sem regressao ---
            padrao = get_access_whatsapp_config("Outro Site")
            assert padrao["provider"] == "cloud_api", padrao

            # --- config legada com instance="sightops" nao pode sobreviver a
            # troca de provider. Todo WhatsApp salvo antes desta feature tem
            # esse valor gravado (era o default do modelo antigo, ate em
            # configuracao puramente cloud_api). Como "sightops" e truthy, um
            # fallback `salvo or default` nunca chegava no nome seguro: os dois
            # primeiros clientes a migrar para Evolution cairiam na MESMA
            # instancia do container compartilhado e se derrubariam.
            settings = db_store.load_app_settings()
            settings["access_control_whatsapp_notifications_by_site"] = {
                **(settings.get("access_control_whatsapp_notifications_by_site") or {}),
                "Unidade Legada": {
                    "enabled": True,
                    "provider": "cloud_api",
                    "instance": "sightops",
                    "phone_number_id": "999",
                    "access_token": "token-legado",
                },
            }
            db_store.save_app_settings(settings)

            legado = save_access_whatsapp_config({
                "site": "Unidade Legada",
                "enabled": True,
                "provider": "evolution",
            })
            assert legado["provider"] == "evolution", legado
            assert legado["instance"] == "escola-evolution-unidade-legada", legado
            assert legado["instance"] != "sightops", legado
            gravado = db_store.load_app_settings()["access_control_whatsapp_notifications_by_site"]["Unidade Legada"]
            assert gravado["instance"] == "escola-evolution-unidade-legada", gravado

            # e o envio real tem que usar o nome derivado, nao o legado
            chamadas.clear()
            send_access_whatsapp_text("5582988881111", "ola", site="Unidade Legada")
            envio = next(c for c in chamadas if "sendText" in c["url"])
            assert envio["url"].endswith("/message/sendText/escola-evolution-unidade-legada"), envio
            assert "/sightops" not in envio["url"], envio

            # --- instance vindo do corpo da requisicao e ignorado ---
            # O container Evolution e a chave de admin sao compartilhados entre
            # todos os clientes: aceitar um nome escolhido pelo cliente deixaria
            # qualquer usuario autenticado operar a instancia de outro tenant
            # (o nome e deduzivel) -- mandar mensagem pela sessao alheia, pegar
            # o QR de pareamento dela ou desconecta-la.
            invasor = "outro-cliente-matriz"
            hijack = save_access_whatsapp_config({
                "site": "Unidade Centro",
                "enabled": True,
                "provider": "evolution",
                "instance": invasor,
                "instance_name": invasor,
            })
            assert hijack["instance"] == "escola-evolution-unidade-centro", hijack
            gravado = db_store.load_app_settings()["access_control_whatsapp_notifications_by_site"]["Unidade Centro"]
            assert gravado["instance"] == "escola-evolution-unidade-centro", gravado

            chamadas.clear()
            respostas_get.clear()
            respostas_get.append(FakeResponse(200, {"instance": {"state": "open"}}))
            send_access_whatsapp_text("5582988881111", "ola", site="Unidade Centro")
            get_access_whatsapp_connection(site="Unidade Centro")
            respostas_delete.clear()
            respostas_delete.append(FakeResponse(200, {}))
            disconnect_access_whatsapp("Unidade Centro")
            assert chamadas, "nenhuma chamada registrada"
            for chamada in chamadas:
                assert invasor not in chamada["url"], f"instance do payload chegou na URL: {chamada}"
                assert "escola-evolution-unidade-centro" in chamada["url"], chamada

            # --- por o canal padrao do cliente em Evolution nao arrasta site
            # que tem credencial Meta propria e nunca escolheu provedor ---
            settings = db_store.load_app_settings()
            settings["access_control_whatsapp_notifications"] = {
                "enabled": True, "provider": "evolution", "instance": "escola-evolution-padrao",
            }
            settings["access_control_whatsapp_notifications_by_site"]["Unidade Meta"] = {
                "enabled": True, "phone_number_id": "555", "access_token": "token-meta",
            }
            db_store.save_app_settings(settings)
            assert get_access_whatsapp_config("")["provider"] == "evolution", "padrao do cliente deveria ser evolution"
            meta = get_access_whatsapp_config("Unidade Meta")
            assert meta["provider"] == "cloud_api", f"site com credencial Meta nao pode herdar evolution do padrao: {meta}"
            assert meta["configured"] is True, meta
            assert meta["phone_number_id"] == "555", meta
            assert meta["instance"] == "", meta

            # --- botao "Testar envio" tem que falar com a instancia do site
            # testado, nao com a instancia padrao do cliente. Achado ao vivo em
            # producao: test_access_whatsapp() montava o contexto sem a chave
            # "site", entao _send_whatsapp->_send_whatsapp_evolution recebia
            # site_key="" e _evolution_instance_cfg (que so deriva do site,
            # nunca do que esta salvo em cfg) calculava o nome da instancia
            # PADRAO do cliente em vez da instancia do site que estava sendo
            # testado -- uma escola conectada via QR via pro teste falhar (ou
            # falar com a instancia errada) porque o teste mirava outra sessao.
            chamadas.clear()
            resultado_teste = test_access_whatsapp({"number": "5582988881111", "site": "Unidade Centro"})
            assert resultado_teste["ok"] is True, resultado_teste
            envio = next(c for c in chamadas if "sendText" in c["url"])
            assert envio["url"].endswith("/message/sendText/escola-evolution-unidade-centro"), envio
            assert "-padrao" not in envio["url"], envio

            # --- trocar de Meta para Evolution e depois voltar nao pode apagar
            # Phone Number ID/WABA ID/template/token. Achado ao vivo em
            # producao: uma escola configurada na Meta perdeu esses campos de
            # verdade (nao so escondidos na tela) ao salvar com Evolution
            # selecionado, porque save_access_whatsapp_config so gravava os
            # campos da API oficial dentro do "if provider == cloud_api".
            site_meta = "Escola com Meta"
            salvo_meta = save_access_whatsapp_config({
                "site": site_meta,
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "111222333",
                "waba_id": "444555666",
                "access_token": "token-secreto-meta",
                "template_name": "aviso_padrao",
                "template_language": "pt_BR",
            })
            assert salvo_meta["phone_number_id"] == "111222333", salvo_meta
            assert salvo_meta["token_saved"] is True, salvo_meta

            trocado = save_access_whatsapp_config({"site": site_meta, "enabled": True, "provider": "evolution"})
            assert trocado["provider"] == "evolution", trocado
            # os campos da Meta continuam voltando na leitura mesmo com
            # Evolution ativo -- e o que faz o front pre-preencher o formulario
            # se o usuario voltar pro provider oficial sem redigitar nada
            assert trocado["phone_number_id"] == "111222333", trocado
            assert trocado["waba_id"] == "444555666", trocado
            assert trocado["token_saved"] is True, trocado

            gravado_evolution = db_store.load_app_settings()["access_control_whatsapp_notifications_by_site"][site_meta]
            assert gravado_evolution["phone_number_id"] == "111222333", gravado_evolution
            assert gravado_evolution.get("access_token"), gravado_evolution

            # voltar pra Meta sem mandar phone_number_id/token de novo (o
            # front so envia esses campos quando o provider ativo e cloud_api)
            # tem que continuar usando os valores preservados
            de_volta = save_access_whatsapp_config({"site": site_meta, "enabled": True, "provider": "cloud_api"})
            assert de_volta["provider"] == "cloud_api", de_volta
            assert de_volta["phone_number_id"] == "111222333", de_volta
            assert de_volta["token_saved"] is True, de_volta
        finally:
            requests.get, requests.post, requests.delete = original_get, original_post, original_delete
            reset_current_tenant_slug(token)

    print("whatsapp evolution service regression ok")


if __name__ == "__main__":
    main()
