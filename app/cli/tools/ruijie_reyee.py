#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Driver para gateways Ruijie Reyee (ex: EG105G-P-V2/V3, ReyeeOS).

Diferente do MikroTik (que roda um script local no proprio equipamento,
pensado pra CPEs atras de CGNAT sem IP publico), o Reyee normalmente tem
IP publico e nao expoe SSH/scripting pro usuario final -- entao aqui o
SightOps fala DIRETO com a API HTTP interna do proprio eWeb (a mesma que
a tela web usa), sem nada rodando dentro do equipamento. E o mesmo padrao
dos drivers de OLT (SightOps conecta quando precisa), so que por HTTP.

O login usa uma chave de firmware FIXA (nao muda por equipamento):
GibberishAES.dec('U2FsdGVkX19ecPYL/ZAlcSG29wb6ivqD9YjEM30k1h8=', 'eweb')
-> 'RjYkhwzx$2018!'. A senha do usuario e cifrada com essa chave em
AES-256-CBC, formato OpenSSL "Salted__" (KDF EVP_BytesToKey/MD5) --
o mesmo formato de `openssl enc -aes-256-cbc -a -salt -md md5`.

Validado em campo contra um EG105G-P-V2 real (ReyeeOS 2.340.0.1629):
login + listagem de ~180 dispositivos da LAN (MAC/IP/hostname/porta).
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from typing import Any, Dict, List

import requests  # type: ignore[import]
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

FIRMWARE_KEY = "RjYkhwzx$2018!"


class RuijieAuthError(Exception):
    """Login recusado pelo gateway (senha errada, ou bloqueio temporario)."""


def _evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    """KDF EVP_BytesToKey/MD5 -- o mesmo do `openssl enc ... -md md5`."""
    derived = b""
    prev = b""
    while len(derived) < key_len + iv_len:
        prev = hashlib.md5(prev + password + salt).digest()
        derived += prev
    return derived[:key_len], derived[key_len:key_len + iv_len]


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def encrypt_password(plaintext: str, passphrase: str = FIRMWARE_KEY) -> str:
    """Reproduz `openssl enc -aes-256-cbc -a -salt -md md5 -pass pass:<passphrase>`."""
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    data = _pkcs7_pad(plaintext.encode("utf-8"))
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


class RuijieSession:
    """Sessao autenticada com o eWeb do gateway. Uma instancia = uma sessao."""

    def __init__(self, host: str, username: str, password: str, timeout: float = 15.0):
        self.host = host.strip()
        self.username = username.strip() or "admin"
        self.password = password
        self.timeout = timeout
        self.sid = ""
        self.sn = ""
        self._base = f"https://{self.host}"

    def login(self) -> None:
        body = {
            "method": "login",
            "params": {
                "password": encrypt_password(self.password),
                "username": self.username,
                "time": str(int(time.time())),
                "encry": True,
            },
        }
        resp = requests.post(f"{self._base}/cgi-bin/luci/api/auth", json=body, timeout=self.timeout, verify=False)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0 or not isinstance(data.get("data"), dict):
            raise RuijieAuthError(f"login recusado pelo gateway: {data}")
        self.sid = str(data["data"].get("sid") or "")
        self.sn = str(data["data"].get("sn") or "")
        if not self.sid or not self.sn:
            raise RuijieAuthError("login sem sid/sn na resposta do gateway")

    def call(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.sid:
            self.login()
        resp = requests.post(
            f"{self._base}/cgi-bin/luci/api/cmd?auth={self.sid}",
            json={"method": method, "params": params},
            cookies={self.sn: self.sid},
            timeout=self.timeout,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()


def parse_user_list(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrai a lista de dispositivos da resposta de `cmdArr(devSta.get/user_list)`."""
    rows: List[Dict[str, Any]] = []
    data = raw.get("data")
    if not isinstance(data, list):
        return rows
    for entry in data:
        if not isinstance(entry, dict):
            continue
        for item in entry.get("list") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "mac": str(item.get("mac") or "").lower(),
                "ip": str(item.get("userIp") or ""),
                "hostname": str(item.get("hostName") or ""),
                "connect_type": str(item.get("connectType") or ""),
                "port": str(item.get("port") or ""),
                "ssid": str(item.get("ssid") or ""),
                "band": str(item.get("band") or ""),
                "vlan": str(item.get("access_vlan") or ""),
                "up_bytes": str(item.get("up") or item.get("flowUp") or ""),
                "down_bytes": str(item.get("down") or item.get("flowDown") or ""),
            })
    return rows


def lan_inventory(host: str, username: str, password: str, timeout: float = 15.0) -> Dict[str, Any]:
    """Loga no gateway e devolve o inventario de dispositivos da LAN.

    Equivalente ao job `lan_inventory` do conector MikroTik, so que
    chamado direto pelo SightOps (sem agente rodando no equipamento).
    """
    session = RuijieSession(host, username, password, timeout=timeout)
    session.login()
    raw = session.call(
        "cmdArr",
        {
            "device": "pc",
            "params": [
                {
                    "method": "devSta.get",
                    "params": {
                        "module": "user_list",
                        "noParse": True,
                        "async": None,
                        "remoteIp": False,
                        "data": {"devType": "all", "dataType": "timely"},
                    },
                }
            ],
        },
    )
    devices = parse_user_list(raw)
    return {"ok": True, "sn": session.sn, "count": len(devices), "devices": devices}
