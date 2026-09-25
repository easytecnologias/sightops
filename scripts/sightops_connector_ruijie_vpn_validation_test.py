import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.connector_service import _looks_like_valid_ovpn_config

REAL_OVPN = """dev tun
nobind
proto udp
float
client
remote 177.131.224.11 1194
auth SHA1
reneg-sec 0
remote-cert-tls server
auth-user-pass
<ca>
-----BEGIN CERTIFICATE-----
MIIDJDCCAgygAwIBAgIJANKA1y0qdCJTMA0GCSqGSIb3DQEBCwUAMBExDzANBgNV
-----END CERTIFICATE-----
</ca>
comp-lzo
cipher AES-128-CBC
"""

# Bug real: alguem colou o .tar inteiro (exportado pelo eWeb) em vez do
# client.ovpn extraido -- produz um cabecalho de tar colado na frente do
# conteudo real e deixa o container OpenVPN em crash-loop.
TAR_HEADER_PREFIX = (
    "etc/openvpn/client.ovpn" + " " * 77 + "0000777 0000000 0000000 "
    "00000002443 15231671641 014216  0" + " " * 100 + "ustar   root"
    + " " * 30 + "root" + " " * 30 + "\n" + REAL_OVPN
)


def test_accepts_real_client_ovpn():
    assert _looks_like_valid_ovpn_config(REAL_OVPN) is True


def test_rejects_raw_tar_with_ustar_header():
    assert _looks_like_valid_ovpn_config(TAR_HEADER_PREFIX) is False


def test_rejects_empty_or_unrelated_text():
    assert _looks_like_valid_ovpn_config("") is False
    assert _looks_like_valid_ovpn_config("qualquer coisa sem nada a ver") is False


def test_accepts_config_starting_with_dev_tap_or_comment():
    assert _looks_like_valid_ovpn_config("dev tap\nremote 1.2.3.4 1194\n") is True
    assert _looks_like_valid_ovpn_config("# comentario\nclient\nremote 1.2.3.4 1194\n") is True


def main() -> None:
    test_accepts_real_client_ovpn()
    test_rejects_raw_tar_with_ustar_header()
    test_rejects_empty_or_unrelated_text()
    test_accepts_config_starting_with_dev_tap_or_comment()
    print("OK: sightops_connector_ruijie_vpn_validation_test")


if __name__ == "__main__":
    main()
