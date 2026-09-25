"""Seguranca do webhook do WhatsApp e do token em repouso.

Duas falhas encontradas na revisao de 27/08, ambas introduzidas na migracao
para a Cloud API:

1. O POST do webhook e publico (a Meta chama de fora) e nao conferia a
   assinatura. Qualquer um com a URL forjava mensagem recebida -- injetava item
   de triagem no cliente e fazia o sistema responder para um numero escolhido
   por ele, gastando o saldo e queimando a reputacao do numero da escola.

2. O token permanente da Meta ficava em texto puro nas configuracoes, enquanto
   senha de OLT/camera/switch ja era cifrada. Esse token nao expira e envia
   mensagem em nome da escola.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_BACKEND"] = "sqlite"
        os.environ["SIGHTOPS_DB_PATH"] = os.path.join(tmp, "sightops-webhook-seg.db")
        os.environ["SIGHTOPS_SECRET_KEY"] = "sightops-webhook-seguranca-test-key"

        from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
        from app.services import db_store
        from app.services.access_control_notifications import (
            _cloud_cfg,
            assinatura_webhook_valida,
            save_access_whatsapp_config,
        )

        token = set_current_tenant_slug("escola-webhook-seg")
        try:
            SEGREDO = "segredo-do-app-meta"
            TOKEN = "EAAmuitolongo-token-permanente-da-meta"

            save_access_whatsapp_config({
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "1299130376610413",
                "access_token": TOKEN,
                "app_secret": SEGREDO,
            })

            # --- o token nao pode estar legivel no que foi gravado
            bruto = db_store.load_app_settings().get("access_control_whatsapp_notifications") or {}
            assert TOKEN not in str(bruto), "token gravado em texto puro"
            assert SEGREDO not in str(bruto), "app secret gravado em texto puro"

            # --- mas quem usa continua recebendo o valor certo
            assert _cloud_cfg(bruto)["access_token"] == TOKEN, _cloud_cfg(bruto)

            # --- assinatura correta passa
            corpo = b'{"entry":[{"changes":[{"value":{"messages":[]}}]}]}'
            certa = hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()
            assert assinatura_webhook_valida(corpo, f"sha256={certa}")
            assert assinatura_webhook_valida(corpo, certa)          # sem o prefixo tambem

            # --- payload forjado e recusado
            assert not assinatura_webhook_valida(corpo, "sha256=" + "0" * 64)
            assert not assinatura_webhook_valida(corpo, "")

            # --- corpo alterado com assinatura do original e recusado
            adulterado = corpo.replace(b'"messages":[]', b'"messages":[{"from":"5511999999999"}]')
            assert not assinatura_webhook_valida(adulterado, f"sha256={certa}")

            # --- campo vazio PRESERVA o segredo atual: editar outro campo do
            #     formulario nao pode apagar credencial
            save_access_whatsapp_config({
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "1299130376610413",
                "app_secret": "",
            })
            assert not assinatura_webhook_valida(corpo, "sha256=" + "0" * 64),                 "campo vazio nao pode apagar o app secret"
        finally:
            reset_current_tenant_slug(token)

        # --- cliente que nunca configurou o App Secret: a checagem nao roda e o
        #     webhook segue aberto, de proposito -- bloquear pararia o que ja
        #     esta no ar. O codigo registra WARNING nomeando o que fazer.
        token = set_current_tenant_slug("escola-sem-segredo")
        try:
            save_access_whatsapp_config({
                "enabled": True,
                "provider": "cloud_api",
                "phone_number_id": "999",
            })
            assert assinatura_webhook_valida(corpo, "qualquer-coisa")
        finally:
            reset_current_tenant_slug(token)

    print("whatsapp webhook: assinatura conferida e token cifrado ok")


if __name__ == "__main__":
    main()
