from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services.access_control_store import (
    list_group_members,
    list_people,
    list_provision_status_for_person,
    save_device,
    save_door_group,
    save_group,
    save_rule,
    set_door_group_members,
)
from app.services.access_control_whatsapp_inbound import (
    approve_access_whatsapp_triage_item,
    approve_ready_access_whatsapp_triage_items,
    create_access_whatsapp_triage_item,
    ensure_access_whatsapp_inbound_token,
    extract_evolution_inbound,
    list_access_whatsapp_triage,
    process_access_whatsapp_inbound,
    process_access_whatsapp_text,
    update_access_whatsapp_triage_item,
    verify_access_whatsapp_inbound_token,
)


def test_whatsapp_registration_draft_confirm_and_cancel() -> None:
    token = set_current_tenant_slug(f"whatsapp-inbound-test-{uuid.uuid4().hex[:8]}")
    try:
        device = save_device({
            "name": "Portaria",
            "site": "RESERVA",
            "vendor": "intelbras",
            "host": "10.10.10.10",
        })
        group = save_group({"name": "GERAL", "site": "RESERVA"})
        door_group = save_door_group({"name": "Portaria", "site": "RESERVA"})
        set_door_group_members(door_group["id"], [device["id"]])
        save_rule({"people_group_id": group["id"], "door_group_id": door_group["id"]})

        first = process_access_whatsapp_text(
            "+5582999000000",
            "nome: Maria Silva matricula: 2001 site: RESERVA grupo: GERAL responsavel: Joao telefone: +5582999111111",
        )
        assert first["ok"] is True
        assert "Rascunho do cadastro" in first["reply"]
        assert first["draft"]["full_name"] == "Maria Silva"
        assert first["draft"]["controller_user_id"] == "2001"

        confirm = process_access_whatsapp_text("+5582999000000", "confirmar")
        assert confirm["ok"] is True
        person = confirm["person"]
        assert person["full_name"] == "MARIA SILVA"
        assert person["site"] == "RESERVA"
        assert person["enrollment_code"] == "2001"
        assert person["controller_user_id"] == "2001"
        assert person["guardian_phone"] == "+5582999111111"
        assert person["id"] in list_group_members(group["id"])
        provision = list_provision_status_for_person(person["id"])
        assert len(provision) == 1
        assert provision[0]["device_id"] == device["id"]
        assert provision[0]["status"] == "pending"

        cancel_start = process_access_whatsapp_text("+5582999000000", "nome: Outro Teste matricula: 2002 site: RESERVA")
        assert cancel_start["ok"] is True
        cancel = process_access_whatsapp_text("+5582999000000", "cancelar")
        assert cancel["ok"] is True
        names = {person["full_name"] for person in list_people()}
        assert "OUTRO TESTE" not in names
    finally:
        reset_current_tenant_slug(token)


def test_whatsapp_registration_blocks_missing_fields_and_group() -> None:
    token = set_current_tenant_slug(f"whatsapp-inbound-test-missing-{uuid.uuid4().hex[:8]}")
    try:
        draft = process_access_whatsapp_text("+5582999000001", "nome: Sem Matricula site: RESERVA")
        assert draft["ok"] is True
        blocked = process_access_whatsapp_text("+5582999000001", "confirmar")
        assert blocked["ok"] is False
        assert "matricula ou id" in blocked["reply"]

        with_group = process_access_whatsapp_text(
            "+5582999000002",
            "nome: Grupo Errado matricula: 2003 site: RESERVA grupo: NAO EXISTE",
        )
        assert with_group["ok"] is True
        blocked_group = process_access_whatsapp_text("+5582999000002", "confirmar")
        assert blocked_group["ok"] is False
        assert "Nao encontrei um grupo unico" in blocked_group["reply"]
    finally:
        reset_current_tenant_slug(token)


def test_evolution_payload_and_token_helpers() -> None:
    token = set_current_tenant_slug(f"whatsapp-inbound-test-token-{uuid.uuid4().hex[:8]}")
    try:
        inbound_token = ensure_access_whatsapp_inbound_token()
        assert verify_access_whatsapp_inbound_token(inbound_token) is True
        assert verify_access_whatsapp_inbound_token("wrong") is False
        payload = {
            "data": {
                "key": {"remoteJid": "5582999000000@s.whatsapp.net"},
                "message": {"conversation": "resumo"},
            }
        }
        extracted = extract_evolution_inbound(payload)
        assert extracted["from_number"] == "5582999000000"
        assert extracted["text"] == "resumo"
        assert extracted["is_group"] is False
    finally:
        reset_current_tenant_slug(token)


def test_whatsapp_triage_review_and_approve_ready() -> None:
    token = set_current_tenant_slug(f"whatsapp-triage-test-{uuid.uuid4().hex[:8]}")
    try:
        device = save_device({
            "name": "Portaria",
            "site": "RESERVA",
            "vendor": "intelbras",
            "host": "10.10.10.11",
        })
        group = save_group({"name": "GERAL", "site": "RESERVA"})
        door_group = save_door_group({"name": "Portaria", "site": "RESERVA"})
        set_door_group_members(door_group["id"], [device["id"]])
        save_rule({"people_group_id": group["id"], "door_group_id": door_group["id"]})

        item = create_access_whatsapp_triage_item({
            "source_group": "Reconhecimento facial portaria - Jardins 2",
            "site": "RESERVA",
            "text": "Natalia Borges\nQuadra G-37",
        })
        assert item["status"] == "review"
        assert item["suggested"]["full_name"] == "Natalia Borges"
        assert "Quadra G-37" in item["suggested"]["unit_label"]

        reviewed = update_access_whatsapp_triage_item(item["id"], {
            "suggested": {
                "full_name": "Natalia Borges",
                "site": "RESERVA",
                "group_name": "GERAL",
                "controller_user_id": "3001",
                "enrollment_code": "3001",
            },
            "photo_url": "https://example.invalid/foto.jpg",
        })
        assert reviewed["status"] == "ready"

        approved = approve_access_whatsapp_triage_item(item["id"])
        assert approved["person"]["full_name"] == "NATALIA BORGES"
        assert approved["queued"] == 1
        assert approved["person"]["id"] in list_group_members(group["id"])
        assert list_provision_status_for_person(approved["person"]["id"])[0]["status"] == "pending"

        second = create_access_whatsapp_triage_item({
            "source_group": "Reconhecimento facial portaria - Jardins 2",
            "site": "RESERVA",
            "text": "Paulo Jose Barbosa Brito\nQUADRA/LOTE F31",
            "photo_url": "https://example.invalid/paulo.jpg",
            "suggested": {
                "full_name": "Paulo Jose Barbosa Brito",
                "site": "RESERVA",
                "group_name": "GERAL",
                "controller_user_id": "3002",
                "enrollment_code": "3002",
                "unit_label": "QUADRA/LOTE F31",
            },
        })
        assert second["status"] == "ready"
        batch = approve_ready_access_whatsapp_triage_items()
        assert len(batch["approved"]) == 1
        assert "TODOS OK" in batch["group_message"]
        assert "PAULO JOSE BARBOSA BRITO" in batch["group_message"]
        summary = list_access_whatsapp_triage()["summary"]
        assert summary["approved"] == 2

        from app.services import db_store
        settings = db_store.load_app_settings()
        settings["access_control_whatsapp_triage_groups"] = [{
            "jid": "120363384783767041@g.us",
            "name": "CADASTRO BRINQUEDOTECA",
            "site": "RESERVA",
            "enabled": True,
        }]
        db_store.save_app_settings(settings)

        ignored = process_access_whatsapp_inbound({
            "data": {
                "key": {"remoteJid": "120363000000000000@g.us"},
                "message": {"conversation": "Grupo errado"},
            }
        })
        assert ignored["ignored"] is True

        allowed = process_access_whatsapp_inbound({
            "data": {
                "key": {"remoteJid": "120363384783767041@g.us"},
                "pushName": "Atendimento",
                "message": {"conversation": "Maria Brinquedoteca\nQuadra B-10"},
            }
        })
        assert allowed["triage"] is True
        assert allowed["item"]["source_group"] == "CADASTRO BRINQUEDOTECA"
        assert allowed["item"]["suggested"]["site"] == "RESERVA"

        image_first = process_access_whatsapp_inbound({
            "key": {
                "remoteJid": "120363384783767041@g.us",
                "participant": "5582999000003@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "jardinsperucaba",
            "message": {"imageMessage": {"jpegThumbnail": "Zm90bw=="}},
            "messageType": "imageMessage",
        })
        assert image_first["triage"] is True
        assert image_first["item"]["source_group"] == "CADASTRO BRINQUEDOTECA"
        assert image_first["item"]["status"] == "review"
        assert "nome nao identificado" in image_first["item"]["reasons"]

        text_second = process_access_whatsapp_inbound({
            "key": {
                "remoteJid": "120363384783767041@g.us",
                "participant": "5582999000003@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "jardinsperucaba",
            "message": {"conversation": "F-10\nLARYSSA DSO SANTOS\nMILYON MEDEIROS"},
            "messageType": "conversation",
        })
        assert text_second["triage"] is True
        assert text_second["item"]["id"] == image_first["item"]["id"]
        assert text_second["item"]["suggested"]["full_name"] == "LARYSSA DSO SANTOS"
        assert text_second["item"]["suggested"]["unit_label"] == "F-10"
        assert text_second["item"]["suggested"]["enrollment_code"] == "F-10"
        assert text_second["item"]["photo_base64"] == "Zm90bw=="

        repeated_image = process_access_whatsapp_inbound({
            "key": {
                "remoteJid": "120363384783767041@g.us",
                "participant": "5582999000003@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "jardinsperucaba",
            "message": {"imageMessage": {"jpegThumbnail": "b3V0cmFGb3Rv"}},
            "messageType": "imageMessage",
        })
        assert repeated_image["item"]["id"] == image_first["item"]["id"]
        assert list_access_whatsapp_triage()["summary"]["ready"] == 1

        repeated_text = process_access_whatsapp_inbound({
            "key": {
                "remoteJid": "120363384783767041@g.us",
                "participant": "5582999000003@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "jardinsperucaba",
            "message": {"conversation": "F-10\nLARYSSA DSO SANTOS\nMILYON MEDEIROS"},
            "messageType": "conversation",
        })
        assert repeated_text["item"]["id"] == image_first["item"]["id"]
        assert list_access_whatsapp_triage()["summary"]["ready"] == 1
    finally:
        reset_current_tenant_slug(token)


if __name__ == "__main__":
    test_whatsapp_registration_draft_confirm_and_cancel()
    test_whatsapp_registration_blocks_missing_fields_and_group()
    test_evolution_payload_and_token_helpers()
    test_whatsapp_triage_review_and_approve_ready()
    print("ok")
