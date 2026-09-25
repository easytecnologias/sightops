import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.cli.tools.ruijie_reyee import (
    FIRMWARE_KEY,
    _evp_bytes_to_key,
    encrypt_password,
    parse_user_list,
)


def _openssl_decrypt(ciphertext_b64: str, passphrase: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    assert raw[:8] == b"Salted__"
    salt = raw[8:16]
    body = raw[16:]
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(body) + decryptor.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len].decode("utf-8")


def test_encrypt_password_round_trips_with_openssl_kdf():
    for plaintext in ["xzydsP2@11", "senha simples", "áéíóú çãõ"]:
        ciphertext = encrypt_password(plaintext)
        assert _openssl_decrypt(ciphertext, FIRMWARE_KEY) == plaintext


def test_encrypt_password_uses_openssl_salted_format():
    ciphertext = encrypt_password("qualquer coisa")
    assert base64.b64decode(ciphertext)[:8] == b"Salted__"


def test_parse_user_list_extracts_wired_and_wireless_devices():
    raw = {
        "code": 0,
        "data": [
            {
                "dev_sn": "H1SU101001825",
                "code": "0",
                "list": [
                    {
                        "mac": "F2:C5:6A:73:78:82", "userIp": "172.16.180.100",
                        "hostName": "Galaxy-A07", "connectType": "wireless",
                        "ssid": "COLABORADORES", "band": "5G", "access_vlan": "0",
                        "up": "123", "down": "456",
                    },
                    {
                        "mac": "08:CC:81:12:52:4D", "userIp": "172.16.80.200",
                        "hostName": "DS-7632NXI-K21620250611CCRRGB42", "connectType": "wire",
                        "port": "LAN3/WAN1", "flowUp": "789", "flowDown": "1011",
                    },
                ],
            },
            {"dev_sn": "H1SU101001825", "code": "0", "list": []},
        ],
        "error": None,
    }
    rows = parse_user_list(raw)
    assert len(rows) == 2
    assert rows[0]["mac"] == "f2:c5:6a:73:78:82"
    assert rows[0]["hostname"] == "Galaxy-A07"
    assert rows[0]["connect_type"] == "wireless"
    assert rows[1]["ip"] == "172.16.80.200"
    assert rows[1]["port"] == "LAN3/WAN1"
    assert rows[1]["up_bytes"] == "789"


def test_parse_user_list_handles_missing_or_malformed_data():
    assert parse_user_list({}) == []
    assert parse_user_list({"data": None}) == []
    assert parse_user_list({"data": [{"list": None}]}) == []


def main() -> None:
    test_encrypt_password_round_trips_with_openssl_kdf()
    test_encrypt_password_uses_openssl_salted_format()
    test_parse_user_list_extracts_wired_and_wireless_devices()
    test_parse_user_list_handles_missing_or_malformed_data()
    print("OK: sightops_ruijie_reyee_test")


if __name__ == "__main__":
    main()
