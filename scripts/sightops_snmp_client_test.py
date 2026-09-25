"""O cliente SNMP minimo fala BER direito -- codifica e decodifica sem rede.

Existe porque a telemetria da OLT 4840E vai depender deste cliente, e um erro
de codificacao BER nao aparece como excecao: aparece como "a OLT nao responde",
que e exatamente o sintoma que estavamos investigando. Os vetores abaixo tem
valor conhecido (sysDescr.0 codificado, inteiro negativo, comprimento longo).

Roda: python scripts/sightops_snmp_client_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.snmp_client import (
    GET_RESPONSE,
    OCTET_STRING,
    SEQUENCE,
    _dec_oid,
    _enc_int,
    _enc_len,
    _enc_oid,
    _parse,
    _tlv,
)


def _resposta(oid: str, valor_tlv: bytes, erro: int = 0) -> bytes:
    """Monta uma resposta SNMP v2c completa, como a OLT devolveria."""
    varbind = _tlv(SEQUENCE, _enc_oid(oid) + valor_tlv)
    pdu = _tlv(GET_RESPONSE, _enc_int(1) + _enc_int(erro) + _enc_int(0) + _tlv(SEQUENCE, varbind))
    return _tlv(SEQUENCE, _enc_int(1) + _tlv(OCTET_STRING, b"public") + pdu)


def main() -> None:
    # OID: o valor esperado e o encoding canonico de 1.3.6.1.2.1.1.1.0
    assert _enc_oid("1.3.6.1.2.1.1.1.0").hex() == "06082b06010201010100", _enc_oid("1.3.6.1.2.1.1.1.0").hex()
    assert _dec_oid(bytes.fromhex("2b06010201010100")) == "1.3.6.1.2.1.1.1.0"

    # OID com sub-identificador acima de 127 precisa dos 7 bits por byte.
    # 13464 e o enterprise da Fiberhome, base de toda a MIB usada na 4840E.
    assert _dec_oid(bytes.fromhex(_enc_oid("1.3.6.1.4.1.13464.1.13.3.3.1.8").hex()[4:])) == "1.3.6.1.4.1.13464.1.13.3.3.1.8"

    # Inteiros: zero, limite de 1 byte, e o primeiro que precisa de padding.
    assert _enc_int(0).hex() == "020100"
    assert _enc_int(127).hex() == "02017f"
    assert _enc_int(128).hex() == "02020080"

    # Comprimento longo (>127) usa a forma com contador de bytes.
    assert _enc_len(200).hex() == "81c8"

    # Resposta comum: sysDescr como texto.
    erro, oid, valor = _parse(_resposta("1.3.6.1.2.1.1.1.0", _tlv(OCTET_STRING, b"OLT4840E")))
    assert (erro, oid, valor) == (0, "1.3.6.1.2.1.1.1.0", "OLT4840E"), (erro, oid, valor)

    # RX optico vem como inteiro NEGATIVO (centesimos de dBm). Se o sinal se
    # perder aqui, -23,50 dBm viraria um numero positivo enorme e a tela
    # mostraria uma ONU otima onde o sinal esta ruim.
    rx = "1.3.6.1.4.1.13464.1.13.3.3.1.8.0.1.5"
    _, _, valor = _parse(_resposta(rx, _enc_int(-2350)))
    assert valor == -2350, valor

    # error-status diferente de zero nao pode ser engolido.
    erro, _, _ = _parse(_resposta("1.3.6.1.2.1.1.1.0", _tlv(OCTET_STRING, b"x"), erro=2))
    assert erro == 2, erro

    print("OK cliente SNMP: BER codifica e decodifica; RX negativo e erro preservados")


if __name__ == "__main__":
    main()
