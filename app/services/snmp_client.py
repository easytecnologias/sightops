"""Cliente SNMP v2c minimo (GET / GETNEXT), sem dependencia externa.

Escrito para a telemetria da OLT Intelbras 4840E. Duas razoes para nao usar
pysnmp: a imagem de producao nao o tem (e a OLT so e alcancavel de DENTRO do
container, porque o IP virtual do vnat nao existe na tabela de rota do host),
e o que a telemetria precisa cabe em GET e GETNEXT -- ler escalares e caminhar
uma tabela. Nao implementa v3, nem SET, nem tipos exoticos.

Validado contra a OLT da Barra de Sao Miguel em 2026-09-25: o GetRequest sai
pelo tunel e chega em 100.65.10.200:161 (confirmado por tcpdump no wgc5).
"""
from __future__ import annotations

import socket
import struct
from typing import Any, Iterator, Tuple

SEQUENCE = 0x30
INTEGER = 0x02
OCTET_STRING = 0x04
NULL = 0x05
OID_TYPE = 0x06
GET_REQUEST = 0xA0
GETNEXT_REQUEST = 0xA1
GET_RESPONSE = 0xA2
COUNTER32, GAUGE32, TIMETICKS, COUNTER64 = 0x41, 0x42, 0x43, 0x46
NO_SUCH_OBJECT, NO_SUCH_INSTANCE, END_OF_MIB = 0x80, 0x81, 0x82


def _enc_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out = b""
    while n:
        out = bytes([n & 0xFF]) + out
        n >>= 8
    return bytes([0x80 | len(out)]) + out


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _enc_len(len(body)) + body


def _enc_int(value: int) -> bytes:
    if value == 0:
        return _tlv(INTEGER, b"\x00")
    body = b""
    v = value
    negative = v < 0
    while (not negative and v) or (negative and v != -1):
        body = bytes([v & 0xFF]) + body
        v >>= 8
    if not negative and body and body[0] & 0x80:
        body = b"\x00" + body
    if negative and body and not (body[0] & 0x80):
        body = b"\xff" + body
    return _tlv(INTEGER, body or b"\x00")


def _enc_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip().strip(".").split(".")]
    body = bytes([parts[0] * 40 + parts[1]])
    for p in parts[2:]:
        if p < 0x80:
            body += bytes([p])
            continue
        chunk = bytes([p & 0x7F])
        p >>= 7
        while p:
            chunk = bytes([(p & 0x7F) | 0x80]) + chunk
            p >>= 7
        body += chunk
    return _tlv(OID_TYPE, body)


def _dec_len(data: bytes, i: int) -> Tuple[int, int]:
    first = data[i]
    i += 1
    if first < 0x80:
        return first, i
    n = first & 0x7F
    value = int.from_bytes(data[i:i + n], "big")
    return value, i + n


def _dec_oid(body: bytes) -> str:
    if not body:
        return ""
    parts = [str(body[0] // 40), str(body[0] % 40)]
    value = 0
    for byte in body[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(str(value))
            value = 0
    return ".".join(parts)


def _dec_int(body: bytes) -> int:
    return int.from_bytes(body, "big", signed=True) if body else 0


def _parse_value(tag: int, body: bytes) -> Any:
    if tag == INTEGER:
        return _dec_int(body)
    if tag in (COUNTER32, GAUGE32, TIMETICKS, COUNTER64):
        return int.from_bytes(body, "big") if body else 0
    if tag == OCTET_STRING:
        try:
            texto = body.decode("utf-8")
        except UnicodeDecodeError:
            return body.hex(":")
        # String com bytes de controle quase sempre e binario (MAC, mascara).
        return texto if texto.isprintable() or not texto else body.hex(":")
    if tag == OID_TYPE:
        return _dec_oid(body)
    if tag == NULL:
        return None
    if tag == NO_SUCH_OBJECT:
        return "<noSuchObject>"
    if tag == NO_SUCH_INSTANCE:
        return "<noSuchInstance>"
    if tag == END_OF_MIB:
        return "<endOfMibView>"
    return body.hex(":")


def _build(community: str, oid: str, pdu_type: int, request_id: int) -> bytes:
    varbind = _tlv(SEQUENCE, _enc_oid(oid) + _tlv(NULL, b""))
    varbinds = _tlv(SEQUENCE, varbind)
    pdu = _tlv(pdu_type, _enc_int(request_id) + _enc_int(0) + _enc_int(0) + varbinds)
    return _tlv(SEQUENCE, _enc_int(1) + _tlv(OCTET_STRING, community.encode()) + pdu)


def _next_tlv(data: bytes, i: int) -> Tuple[int, bytes, int]:
    """Le um TLV em `i`. Devolve (tag, corpo, proximo indice)."""
    tag = data[i]
    tam, j = _dec_len(data, i + 1)
    return tag, data[j:j + tam], j + tam


def _parse(data: bytes) -> Tuple[int, str, Any]:
    """Devolve (error-status, oid, valor) do primeiro varbind da resposta."""
    _, msg, _ = _next_tlv(data, 0)          # SEQUENCE da mensagem
    i = 0
    _, _, i = _next_tlv(msg, i)             # version
    _, _, i = _next_tlv(msg, i)             # community
    tag, pdu, _ = _next_tlv(msg, i)
    if tag != GET_RESPONSE:
        raise ValueError(f"PDU inesperada: 0x{tag:02x}")

    j = 0
    _, _, j = _next_tlv(pdu, j)             # request-id
    _, corpo_erro, j = _next_tlv(pdu, j)    # error-status
    erro = _dec_int(corpo_erro)
    _, _, j = _next_tlv(pdu, j)             # error-index
    _, varbinds, _ = _next_tlv(pdu, j)

    _, varbind, _ = _next_tlv(varbinds, 0)  # primeiro varbind
    _, corpo_oid, k = _next_tlv(varbind, 0)
    tag_valor, corpo_valor, _ = _next_tlv(varbind, k)
    return erro, _dec_oid(corpo_oid), _parse_value(tag_valor, corpo_valor)


class Snmp:
    def __init__(self, host: str, community: str = "public", port: int = 161, timeout: float = 3.0):
        self.host, self.community, self.port, self.timeout = host, community, port, timeout
        self._rid = 1000

    def _ask(self, oid: str, pdu_type: int) -> Tuple[int, str, Any]:
        self._rid += 1
        pacote = _build(self.community, oid, pdu_type, self._rid)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(self.timeout)
        try:
            s.sendto(pacote, (self.host, self.port))
            resposta, _ = s.recvfrom(65535)
        finally:
            s.close()
        return _parse(resposta)

    def get(self, oid: str) -> Any:
        erro, _, valor = self._ask(oid, GET_REQUEST)
        if erro:
            raise ValueError(f"erro SNMP {erro} em {oid}")
        return valor

    def walk(self, raiz: str, limite: int = 5000) -> Iterator[Tuple[str, Any]]:
        atual = raiz
        for _ in range(limite):
            erro, oid, valor = self._ask(atual, GETNEXT_REQUEST)
            if erro or not oid.startswith(raiz.strip(".") + "."):
                return
            if valor == "<endOfMibView>":
                return
            yield oid, valor
            atual = oid
