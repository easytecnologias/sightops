from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.access_control_device import get_system_info, open_door, poll_events, provision_person, remove_person


def test_get_system_info_parses_response() -> None:
    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = (
        "appAutoStart=true\r\n"
        "deviceType=SS 3542 MF W\r\n"
        "hardwareVersion=1.00\r\n"
        "processor=FREYJA\r\n"
        "serialNumber=5PGM370013181\r\n"
        "updateSerial=ASI6214S-W\r\n"
    )
    fake_response.raise_for_status = MagicMock()
    with patch("app.services.access_control_device.requests.get", return_value=fake_response) as mock_get:
        info = get_system_info(device)
    assert info["deviceType"] == "SS 3542 MF W"
    assert info["updateSerial"] == "ASI6214S-W"
    called_url = mock_get.call_args.args[0]
    assert "getSystemInfo" in called_url


def test_open_door_checks_ok_response() -> None:
    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "OK"
    fake_response.raise_for_status = MagicMock()
    with patch("app.services.access_control_device.requests.get", return_value=fake_response):
        result = open_door(device, channel=1)
    assert result["ok"] is True


def test_open_door_raises_on_device_error() -> None:
    from fastapi import HTTPException

    device = {"host": "10.10.13.33", "username": "admin", "password": "wrong"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "Error: Invalid channel"
    fake_response.raise_for_status = MagicMock()
    with patch("app.services.access_control_device.requests.get", return_value=fake_response):
        try:
            open_door(device, channel=99)
            raise AssertionError("deveria ter levantado HTTPException")
        except HTTPException as exc:
            assert "Invalid channel" in str(exc.detail)


def test_get_system_info_reports_invalid_credentials() -> None:
    from fastapi import HTTPException

    device = {"host": "10.10.13.33", "username": "admin", "password": "wrong"}
    fake_response = MagicMock()
    fake_response.status_code = 403
    fake_response.text = "Authentication Failed"
    with patch("app.services.access_control_device.requests.get", return_value=fake_response):
        try:
            get_system_info(device)
            raise AssertionError("deveria informar senha invalida")
        except HTTPException as exc:
            assert "senha invalidos" in str(exc.detail)


def test_get_system_info_uses_connector_job_when_configured() -> None:
    device = {
        "host": "10.10.10.175",
        "username": "admin",
        "password": "secret",
        "connector_id": "perucaba",
    }
    job = {
        "id": "job-access",
        "connector_id": "perucaba",
        "type": "access_http_get",
        "status": "done",
        "result": {
            "access_http": "status=finished;data=deviceType=SS 3542 MF W\r\nupdateSerial=ASI6214S-W\r\n"
        },
    }
    with patch("app.services.connector_service.create_job", return_value={"ok": True, "job": {"id": "job-access"}}) as create_job:
        with patch("app.services.connector_service.list_jobs", return_value={"ok": True, "jobs": [job]}):
            info = get_system_info(device)

    assert info["deviceType"] == "SS 3542 MF W"
    payload = create_job.call_args.args[0]
    assert payload["connector_id"] == "perucaba"
    assert payload["type"] == "access_http_get"
    assert "magicBox.cgi" in payload["payload"]["url"]
    assert payload["payload"]["password"] == "secret"


def test_remove_intelbras_person_uses_connector_get_job_when_configured() -> None:
    device = {
        "host": "10.10.10.175",
        "username": "admin",
        "password": "secret",
        "connector_id": "perucaba",
    }
    job = {
        "id": "job-remove",
        "connector_id": "perucaba",
        "type": "access_http_get",
        "status": "done",
        "result": {"access_http": "status=finished;data=OK"},
    }
    with patch("app.services.connector_service.create_job", return_value={"ok": True, "job": {"id": "job-remove"}}) as create_job:
        with patch("app.services.connector_service.list_jobs", return_value={"ok": True, "jobs": [job]}):
            with patch("app.services.access_control_device.requests.post") as direct_post:
                result = remove_person(device, "1001")

    assert result["ok"] is True
    assert not direct_post.called
    payload = create_job.call_args.args[0]
    assert payload["type"] == "access_http_get"
    assert "/cgi-bin/AccessUser.cgi" in payload["payload"]["url"]
    assert "action=removeMulti" in payload["payload"]["url"]
    assert "UserIDList%5B0%5D=1001" in payload["payload"]["url"]


def test_poll_events_reads_intelbras_access_history() -> None:
    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011", "vendor": "Intelbras"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = (
        "found=3\r\n"
        "records[0].RecNo=100\r\n"
        "records[0].CreateTime=2026-05-15 10:14:27\r\n"
        "records[0].UserID=1021\r\n"
        "records[0].CardName=RAYSSA FUNCIONARIA\r\n"
        "records[0].Status=1\r\n"
        "records[0].Type=Entry\r\n"
        "records[0].Method=15\r\n"
        "records[0].Door=0\r\n"
        "records[0].ReaderID=1\r\n"
        "records[1].RecNo=101\r\n"
        "records[1].CreateTime=2026-05-15 10:15:27\r\n"
        "records[1].UserID=1022\r\n"
        "records[1].CardName=TENTATIVA NEGADA\r\n"
        "records[1].Status=0\r\n"
        "records[1].Type=Entry\r\n"
        "records[2].RecNo=102\r\n"
        "records[2].CreateTime=2026-05-15 10:16:27\r\n"
        "records[2].UserID=1023\r\n"
        "records[2].CardName=LUCIANA SAIDA\r\n"
        "records[2].Status=1\r\n"
        "records[2].Type=Exit\r\n"
    )
    with patch("app.services.access_control_device.requests.get", return_value=fake_response) as mock_get:
        events = poll_events(device, since_id="100")
    assert len(events) == 1
    assert events[0]["raw_id"] == "102"
    assert events[0]["occurred_at"] == "2026-05-15 10:16:27"
    assert events[0]["person_name_raw"] == "LUCIANA SAIDA"
    assert events[0]["user_id"] == "1023"
    assert events[0]["event_type"] == "saida"
    called_url = mock_get.call_args.args[0]
    assert "recordFinder.cgi" in called_url
    assert "AccessControlCardRec" in called_url
    assert "StartTime" in called_url


def test_poll_events_uses_recent_window_after_cursor() -> None:
    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011", "vendor": "Intelbras"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = (
        "found=2\r\n"
        "records[0].RecNo=1656\r\n"
        "records[0].CreateTime=1787231797\r\n"
        "records[0].UserID=1021\r\n"
        "records[0].CardName=RAYSSA FUNCIONARIA\r\n"
        "records[0].Status=1\r\n"
        "records[0].Type=Entry\r\n"
        "records[1].RecNo=1657\r\n"
        "records[1].CreateTime=1787255104\r\n"
        "records[1].UserID=1001\r\n"
        "records[1].CardName=ELISHAFAN DE OLIVEIRA MACHADO\r\n"
        "records[1].Status=1\r\n"
        "records[1].Type=Entry\r\n"
    )
    with patch("app.services.access_control_device.requests.get", return_value=fake_response) as mock_get:
        events = poll_events(device, since_id="1656")
    assert len(events) == 1
    assert events[0]["raw_id"] == "1657"
    assert events[0]["user_id"] == "1001"
    assert events[0]["person_name_raw"] == "ELISHAFAN DE OLIVEIRA MACHADO"
    assert events[0]["occurred_at"] == "2026-08-20 16:45:04"
    called_url = mock_get.call_args.args[0]
    assert "StartTime" in called_url
    assert "count=1024" in called_url


def test_poll_events_raises_on_unexpected_error_body() -> None:
    """Review finding: so "Error: No Events" (confirmado ao vivo) pode virar
    lista vazia. Qualquer OUTRO corpo iniciado por "Error" (ex.: falha de
    autenticacao, mau funcionamento) tem que levantar HTTPException com o
    texto real do dispositivo -- nao pode virar lista vazia silenciosa,
    senao quem faz polling em loop nao consegue distinguir "sem novidade"
    de "dispositivo com problema".
    """
    from fastapi import HTTPException

    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011", "vendor": "Intelbras"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "Error: Authentication Failed"
    with patch("app.services.access_control_device.requests.get", return_value=fake_response):
        try:
            poll_events(device)
            raise AssertionError("deveria ter levantado HTTPException")
        except HTTPException as exc:
            assert "senha invalidos" in str(exc.detail)


def test_provision_person_sends_valid_json_not_python_repr() -> None:
    """Review finding: o multipart 'json' era montado com str(dict) (repr do
    Python -- aspas simples, True/False/None capitalizados), nao JSON de
    verdade. Trocado para json.dumps(). Este teste falha se alguem reverter
    pra str() -- json.loads() rejeitaria o repr do Python.
    """
    device = {"host": "10.10.13.33", "username": "admin", "password": "SenhaTeste2011"}
    person = {"id": "p1", "full_name": "Fulano de Tal"}
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "OK"
    with patch("app.services.access_control_device.requests.post", return_value=fake_response) as mock_post:
        result = provision_person(device, person)
    assert result["ok"] is True
    sent_files = mock_post.call_args.kwargs["files"]
    sent_json_text = sent_files["json"][1]
    payload = json.loads(sent_json_text)  # levanta ValueError se nao for JSON valido
    assert payload["action"] == "insertMulti"
    assert payload["Info"][0]["UserID"] == "p1"
    assert payload["Info"][0]["UserName"] == "Fulano de Tal"


def test_provision_intelbras_uses_legacy_card_and_face_endpoints() -> None:
    device = {"host": "10.10.10.175", "username": "admin", "password": "secret", "vendor": "intelbras"}
    person = {"id": "internal-id", "controller_user_id": "1001", "full_name": "Elishafan Teste"}
    fake_user = MagicMock()
    fake_user.status_code = 200
    fake_user.text = "OK"
    fake_face = MagicMock()
    fake_face.status_code = 200
    fake_face.text = "OK"

    with patch("app.services.access_control_device.requests.post", side_effect=[fake_user, fake_face]) as mock_post:
        result = provision_person(device, person, photo_bytes=b"jpeg-bytes")

    assert result["ok"] is True
    user_url = mock_post.call_args_list[0].args[0]
    assert user_url.endswith("/cgi-bin/AccessUser.cgi?action=insertMulti")
    sent_user_payload = mock_post.call_args_list[0].kwargs["json"]
    assert sent_user_payload["UserList"][0]["UserID"] == "1001"
    assert sent_user_payload["UserList"][0]["UserName"] == "Elishafan Teste"
    assert sent_user_payload["UserList"][0]["Password"] == "123456"
    assert sent_user_payload["UserList"][0]["Doors"] == [0]

    face_url = mock_post.call_args_list[1].args[0]
    assert face_url.endswith("/cgi-bin/AccessFace.cgi?action=insertMulti")
    sent_payload = mock_post.call_args_list[1].kwargs["json"]
    assert sent_payload["FaceList"][0]["UserID"] == "1001"
    assert sent_payload["FaceList"][0]["PhotoData"][0]


def test_provision_intelbras_requires_controller_user_id() -> None:
    from fastapi import HTTPException

    device = {"host": "10.10.10.175", "username": "admin", "password": "secret", "vendor": "intelbras"}
    person = {"id": "internal-id", "full_name": "Sem Id"}
    try:
        provision_person(device, person, photo_bytes=b"jpeg-bytes")
        raise AssertionError("deveria exigir controller_user_id para Intelbras")
    except HTTPException as exc:
        assert "ID na controladora" in str(exc.detail)


def test_provision_intelbras_updates_face_when_insert_reports_batch_error() -> None:
    device = {"host": "10.10.10.175", "username": "admin", "password": "secret", "vendor": "intelbras"}
    person = {"id": "internal-id", "controller_user_id": "1001", "full_name": "Elishafan Teste"}
    fake_user = MagicMock()
    fake_user.status_code = 200
    fake_user.text = "OK"
    fake_face_insert = MagicMock()
    fake_face_insert.status_code = 400
    fake_face_insert.text = "Batch Process Error"
    fake_face_update = MagicMock()
    fake_face_update.status_code = 200
    fake_face_update.text = "OK"

    with patch(
        "app.services.access_control_device.requests.post",
        side_effect=[fake_user, fake_face_insert, fake_face_update],
    ) as mock_post:
        result = provision_person(device, person, photo_bytes=b"jpeg-bytes")

    assert result["ok"] is True
    assert mock_post.call_args_list[1].args[0].endswith("/cgi-bin/AccessFace.cgi?action=insertMulti")
    assert mock_post.call_args_list[2].args[0].endswith("/cgi-bin/AccessFace.cgi?action=updateMulti")


def main() -> None:
    test_get_system_info_parses_response()
    test_open_door_checks_ok_response()
    test_open_door_raises_on_device_error()
    test_get_system_info_reports_invalid_credentials()
    test_get_system_info_uses_connector_job_when_configured()
    test_poll_events_reads_intelbras_access_history()
    test_poll_events_uses_recent_window_after_cursor()
    test_poll_events_raises_on_unexpected_error_body()
    test_provision_person_sends_valid_json_not_python_repr()
    test_provision_intelbras_uses_legacy_card_and_face_endpoints()
    test_provision_intelbras_requires_controller_user_id()
    test_provision_intelbras_updates_face_when_insert_reports_batch_error()
    print("OK access control device client: getSystemInfo, openDoor, poll_events, provision_person")


if __name__ == "__main__":
    main()
