"""Achados da revisao de isolamento sobre a regra unica de destino: varredura e
inventario nao viram posse de rede alheia, e as saidas web passam pela regra."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.endpoints import maintenance as M
from app.api.endpoints import ws as W
from app.core import destino as D
from app.services import inventory_json as I
from app.services import ws_scan_service as S
from test_destino_permitido import rede  # noqa: F401  (fixture)


class _WsScan:
    def __init__(self):
        self.enviados = []

    async def send_text(self, texto):
        self.enviados.append(texto)


def _varrer(alvo, **extra):
    ws = _WsScan()
    asyncio.run(S.run_ws_scan(ws, {"alvo": alvo, "append_inventory": True, **extra}, tenant_slug="cliente-a"))
    return ws


@pytest.mark.parametrize("alvo", ["10.208.1.5", "10.208.1.0/28", "10.208.0.9,10.208.1.9",
                                  "10.208.1.1-10.208.1.3", "10.208.1.1-3", "10.208.1.5:81",
                                  "127.0.0.1", "10.0.0.0/8"])
def test_varredura_recusa_destino_alheio_sem_rodar(rede, monkeypatch, alvo):
    rodou = []
    monkeypatch.setattr(S, "run_http_scan", lambda req: rodou.append(req) or {"ok": True})
    ws = _varrer(alvo)
    assert rodou == []
    assert any('"error"' in t for t in ws.enviados)


def test_varredura_da_faixa_do_proprio_conector_roda(rede, monkeypatch):
    rodou = []
    monkeypatch.setattr(S, "run_http_scan", lambda req: rodou.append(req.alvo) or {"ok": True, "inventory": []})
    _varrer("10.208.0.1-3")
    assert rodou == ["10.208.0.1-3"]


def test_varredura_remota_nao_exige_lan_ja_conhecida(rede, monkeypatch):
    """Pelo MikroTik do proprio cliente o pacote sai la de dentro: a LAN pode
    ainda nem ter sido coletada. So o destino interno/alheio e recusado."""
    monkeypatch.setattr(S, "_connector_from_payload", lambda p: {"id": "conn-a"})
    monkeypatch.setattr(S, "_decide_remote_only", lambda **k: True)
    rodou = []

    async def _remoto(ws, payload, result, slug):
        rodou.append(payload["alvo"])
        return {"ok": True, "inventory": []}

    monkeypatch.setattr(S, "_remote_inventory_via_connector", _remoto)
    _varrer("10.99.0.0/24", connector_id="conn-a")
    assert rodou == ["10.99.0.0/24"]
    rodou.clear()
    _varrer("10.208.1.0/24", connector_id="conn-a")
    assert rodou == []


def test_filtro_de_faixa_virtual_alheia(rede):
    linhas = [{"ip": "10.208.1.5"}, {"ip": "10.208.0.5"}, {"ip": "192.168.10.9:81"}, {"ip": "10.208.1.6:81"}]
    assert D.sem_faixa_virtual_alheia("cliente-a", linhas) == [{"ip": "10.208.0.5"}, {"ip": "192.168.10.9:81"}]


def test_save_inventory_json_nao_grava_faixa_virtual_alheia(rede, monkeypatch, tmp_path):
    gravado = {}
    monkeypatch.setattr(I, "set_json_state", lambda chave, valor: gravado.update(valor))
    monkeypatch.setattr(I, "replace_ip_inventory_rows", lambda rows: None)
    monkeypatch.setattr(I, "_inventory_path", lambda modo: tmp_path / "inv.json")
    I.save_inventory_json([{"ip": "10.208.1.5"}, {"ip": "192.168.10.9"}], mode="olt")
    assert [r["ip"] for r in gravado["inventory"]] == ["192.168.10.9"]


def test_proxy_web_recusa_virtual_alheio_com_linha_no_inventario(rede, monkeypatch):
    monkeypatch.setattr(M, "_ip_belongs_to_current_tenant", lambda ip: True)  # inventario envenenado
    with pytest.raises(HTTPException) as exc:
        M._camera_web_target_url("10.208.1.5")
    assert exc.value.status_code == 403
    # camera propria: a linha aponta o conector isolado dela, o alvo e o virtual
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    assert "10.208.0.9" in M._camera_web_target_url("192.168.10.9")


def test_ponte_web_recusa_virtual_alheio_com_linha_no_inventario(rede, monkeypatch):
    monkeypatch.setattr(M, "_ip_belongs_to_current_tenant", lambda ip: True)
    monkeypatch.setattr(M, "web_liberada_para", lambda u, ip, hint="": (True, ""))
    assert W._web_tunnel_destino({}, "10.208.1.5", 80) == ""
    monkeypatch.setattr(M, "_camera_row_for_ip", lambda ip, hint="": {"remote_connector_id": "conn-a"})
    assert W._web_tunnel_destino({}, "192.168.10.9", 80) == "10.208.0.9"
