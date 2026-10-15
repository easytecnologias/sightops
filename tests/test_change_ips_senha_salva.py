"""Troca de IP pelo editor do Mapa: sem senha digitada, usa a guardada de cada camera."""
from __future__ import annotations

from app.api.endpoints import maintenance as M


def _sem_rede(monkeypatch, credenciais):
    chamadas = []
    monkeypatch.setattr(M, "_credencial_que_responde",
                        lambda ip, user, pw, cid="": credenciais.get(ip, (user, "")))
    from app.services import camera_xray
    monkeypatch.setattr(camera_xray, "raio_x_camera",
                        lambda ip, u, p, connector_id="": {"rede": {"mascara": "255.255.255.0", "gateway": "10.0.0.1"}})

    def troca(**kw):
        chamadas.append(kw)
        return {"ok": True, "ip": kw["ip"], "new_ip": kw["new_ip"]}
    monkeypatch.setattr(M, "_change_ip_one", troca)
    return chamadas


def test_sem_senha_usa_a_guardada_de_cada_camera(monkeypatch):
    chamadas = _sem_rede(monkeypatch, {"10.0.0.5": ("admin", "senha-da-5")})
    r = M.maintenance_batch_change_ips({"itens": [{"ip": "10.0.0.5", "new_ip": "10.0.0.50"}], "user": "admin"})
    assert r["ok"] is True
    assert chamadas[0]["password"] == "senha-da-5"


def test_sem_senha_guardada_recusa_sem_tocar_na_camera(monkeypatch):
    chamadas = _sem_rede(monkeypatch, {})
    r = M.maintenance_batch_change_ips({"itens": [{"ip": "10.0.0.6", "new_ip": "10.0.0.60"}], "user": "admin"})
    assert r["ok"] is False and "sem senha guardada" in r["results"][0]["error"]
    assert chamadas == []


def test_senha_digitada_continua_valendo_para_todas(monkeypatch):
    chamadas = _sem_rede(monkeypatch, {"10.0.0.5": ("admin", "outra")})
    M.maintenance_batch_change_ips({"itens": [{"ip": "10.0.0.5", "new_ip": "10.0.0.51"}], "user": "admin", "pass": "digitada"})
    assert chamadas[0]["password"] == "digitada"
