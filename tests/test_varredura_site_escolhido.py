"""Varredura por conector: o site escolhido na tela vale sobre o site do
conector (um conector atende mais de um site). Dados ficticios."""
from __future__ import annotations

from app.services import ws_scan_service as W


def _rodar(monkeypatch, local):
    linhas = [{"ip": "10.10.11.51", "status": "online"}, {"ip": "10.10.11.99", "status": "online"}]
    gravado = {}
    monkeypatch.setattr(W, "_connector_from_payload", lambda p: {"id": "c-peru", "name": "PERUCABA", "site": "PERUCABA"})
    monkeypatch.setattr(W, "load_inventory_json", lambda mode="olt": [dict(x) for x in linhas])
    monkeypatch.setattr(W, "save_inventory_json", lambda rows, mode="olt": gravado.setdefault("rows", rows))
    W._tag_rows_for_connector({"alvo": "10.10.11.51", "local": local, "connector_id": "c-peru", "inventory_mode": "switch"},
                              {"ok": True}, "default")
    return {r["ip"]: r for r in gravado["rows"]}


def test_site_escolhido_vale(monkeypatch):
    rows = _rodar(monkeypatch, "JARDINS II")
    assert rows["10.10.11.51"]["local"] == "JARDINS II" and rows["10.10.11.51"]["site"] == "JARDINS II"
    assert rows["10.10.11.51"]["remote_connector_id"] == "c-peru"  # o pacote continua saindo pelo conector do PERUCABA
    assert "local" not in rows["10.10.11.99"]  # fora da faixa: intacta


def test_sem_site_escolhido_usa_o_do_conector(monkeypatch):
    rows = _rodar(monkeypatch, "")
    assert rows["10.10.11.51"]["local"] == "PERUCABA"
