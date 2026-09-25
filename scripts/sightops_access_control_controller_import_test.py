import base64

from app.services.access_control_device import (
    _parse_record_table,
    _photo_data_from_access_face_text,
    get_controller_person_photo,
    list_controller_people,
)


class FakeResponse:
    status_code = 200
    text = ""


def test_record_table_parser() -> None:
    text = "\n".join(
        [
            "found=2",
            "records[1].CardName=Maria Silva",
            "records[1].UserID=1002",
            "records[0].CardName=Joao Souza",
            "records[0].UserID=1001",
            "records[0].CitizenIDNo=123",
        ]
    )
    rows = _parse_record_table(text)
    assert rows[0]["CardName"] == "Joao Souza"
    assert rows[0]["UserID"] == "1001"
    assert rows[1]["CardName"] == "Maria Silva"


def test_controller_people_normalization(monkeypatch) -> None:
    def fake_get(device, path, params):
        response = FakeResponse()
        response.text = "\n".join(
            [
                "found=1",
                "records[0].CardName=Joao Souza",
                "records[0].UserID=1001",
                "records[0].CitizenIDNo=123",
            ]
        )
        return response

    monkeypatch.setattr("app.services.access_control_device._get", fake_get)
    rows = list_controller_people({"vendor": "intelbras", "host": "10.0.0.1"})
    assert rows == [
        {
            "controller_user_id": "1001",
            "full_name": "Joao Souza",
            "document_id": "123",
            "card_no": "",
            "rec_no": "",
            "valid_from": "",
            "valid_to": "",
            "raw_active": "",
        }
    ]


def test_access_face_photo_parser_decodes_photo_data() -> None:
    jpg = b"\xff\xd8fake-jpeg\xff\xd9"
    text = "\n".join(
        [
            "FaceDataList[0].FaceData[0]=not-a-photo",
            f"FaceDataList[0].PhotoData[0]={base64.b64encode(jpg).decode('ascii')}",
            "FaceDataList[0].UserID=1001",
        ]
    )
    assert _photo_data_from_access_face_text(text) == jpg


def test_get_controller_person_photo_uses_user_id_list(monkeypatch) -> None:
    calls = []
    jpg = b"\xff\xd8face\xff\xd9"

    def fake_get(device, path, params):
        calls.append((path, params))
        response = FakeResponse()
        response.text = f"FaceDataList[0].PhotoData[0]={base64.b64encode(jpg).decode('ascii')}"
        return response

    monkeypatch.setattr("app.services.access_control_device._get", fake_get)
    assert get_controller_person_photo({"vendor": "intelbras", "host": "10.0.0.1"}, "ID 1001") == jpg
    assert calls == [("/cgi-bin/AccessFace.cgi", {"action": "list", "UserIDList[0]": "1001"})]
