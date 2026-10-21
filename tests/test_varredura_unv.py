"""Varredura de camera UNV/Uniview: identificar pela LAPI em poucos pedidos e
nunca insistir com a senha (a UNV trava o usuario). Camera falsa, sem rede."""
from __future__ import annotations

import json

from app.services.camsnapshot import device_info as D


class _Resp:
    def __init__(self, code, corpo=""):
        self.status_code = code
        self.text = corpo


def _lapi(code=0, status=0, texto="Succeed", data=None):
    return json.dumps({"Response": {"ResponseCode": code, "StatusCode": status, "StatusString": texto, "Data": data or ""}})


def _camera(monkeypatch, rotas):
    """rotas: caminho -> (codigo, corpo). Conta todos os pedidos."""
    pedidos = []

    def falso(url, user, password, timeout, use_digest=False, stream=False):
        caminho = "/" + url.split("/", 3)[3]
        pedidos.append((caminho, "digest" if use_digest else "basic"))
        code, corpo = rotas.get(caminho, (404, ""))
        return _Resp(code, corpo)

    monkeypatch.setattr(D, "_try_get", falso)
    monkeypatch.setattr(D, "best_guess_model", lambda *a, **k: None)
    return pedidos


def test_unv_travada_para_no_primeiro_pedido(monkeypatch):
    travada = (200, _lapi(1, 364, "UserLocked"))
    pedidos = _camera(monkeypatch, {"/LAPI/V1.0/System/DeviceInfo": travada, "/LAPI/V1.0/Network/Interfaces": travada})
    info = D.probe_device("10.0.0.5", "admin", "x", timeout=(0.6, 3.0), retries=1)
    assert info["status"] == "auth_failed" and info["auth_code"] == "usuario_bloqueado" and info["fabricante"] == "UNV"
    assert pedidos == [("/LAPI/V1.0/System/DeviceInfo", "digest")]  # um pedido, nenhuma insistencia


def test_unv_identificada_so_pela_lapi(monkeypatch):
    info_ok = (200, _lapi(data={"DeviceModel": "IPC2122LB-ASF28-ECO", "SerialNumber": "S1", "DeviceName": "PORTARIA"}))
    rede_ok = (200, _lapi(data={"MACAddress": "c4:79:05:b7:fe:61"}))
    pedidos = _camera(monkeypatch, {"/LAPI/V1.0/System/DeviceInfo": info_ok, "/LAPI/V1.0/Network/Interfaces": rede_ok})
    info = D.probe_device("10.0.0.5", "admin", "certa", timeout=(0.6, 3.0), retries=1)
    assert info.get("status") != "auth_failed"
    assert info["fabricante"] == "UNV" and info["modelo"] == "IPC2122LB-ASF28-ECO" and info["mac"] == "c4:79:05:b7:fe:61"
    assert all(c.startswith("/LAPI/") for c, _ in pedidos), pedidos  # nada de Dahua/Hikvision
    assert len(pedidos) <= 5, pedidos
    assert ("/LAPI/V1.0/System/DeviceInfo", "basic") not in pedidos


def test_unv_senha_errada_nao_tenta_basic(monkeypatch):
    pedidos = _camera(monkeypatch, {"/LAPI/V1.0/System/DeviceInfo": (401, "")})
    info = D.probe_device("10.0.0.5", "admin", "errada", timeout=(0.6, 3.0), retries=1)
    assert info["status"] == "auth_failed"
    assert pedidos == [("/LAPI/V1.0/System/DeviceInfo", "digest")]


def test_intelbras_segue_o_caminho_de_sempre(monkeypatch):
    pedidos = _camera(monkeypatch, {
        "/cgi-bin/snapshot.cgi": (200, "jpg"),
        "/cgi-bin/magicBox.cgi?action=getDeviceType": (200, "type=VIP-3230-B"),
        "/cgi-bin/configManager.cgi?action=getConfig&name=Network.eth0": (200, "table.Network.eth0.PhysicalAddress=11:22:33:44:55:66"),
    })
    info = D.probe_device("10.0.0.6", "admin", "certa", timeout=(0.6, 3.0), retries=1)
    assert info.get("status") != "auth_failed" and info["modelo"] == "VIP-3230-B"
    assert pedidos[0] == ("/LAPI/V1.0/System/DeviceInfo", "digest")  # 1 pedido a mais, 404 rapido
    assert ("/cgi-bin/snapshot.cgi", "digest") in pedidos
