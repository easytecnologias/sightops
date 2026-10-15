"""Ensinar uma senha ao site inteiro sem bloquear camera Intelbras."""
from __future__ import annotations

import time

from app.services import camera_senha_lote as L


class _R:
    def __init__(self, cod):
        self.status_code = cod


def _cenario(monkeypatch, cameras, senha_certa, guardadas, sem_resposta=()):
    tentativas, salvas, site_trocado = {}, {}, []

    def get(url, auth=None, timeout=0, verify=True):
        ip = url.split("//")[1].split("/")[0]
        tentativas[ip] = tentativas.get(ip, 0) + 1
        if ip in sem_resposta:
            raise TimeoutError()
        return _R(200 if auth.password == senha_certa[ip] else 401)

    monkeypatch.setattr(L.requests, "get", get)
    monkeypatch.setattr(L, "cameras_do_site", lambda site: cameras)
    monkeypatch.setattr(L, "resolve_camera_credential", lambda mac, site: guardadas.get(mac))
    monkeypatch.setattr(L, "save_camera_credential", lambda mac, site, u, p: salvas.__setitem__(mac, p))
    monkeypatch.setattr(L, "definir_senha_do_site", lambda site, u, p: site_trocado.append(p))
    monkeypatch.setattr(L.vnat, "virtual_ip_for", lambda cid, ip: ip)
    monkeypatch.setattr(L.vnat, "has_mapping", lambda cid: False)
    return tentativas, salvas, site_trocado


def _rodar(site="RESERVA", user="admin", senha="NOVA"):
    job = L.iniciar(site, user, senha)["job_id"]
    for _ in range(200):
        e = L.estado(job)
        if e["estado"] != "rodando":
            return e
        time.sleep(0.01)
    raise AssertionError("nao terminou")


def test_aprende_so_onde_a_guardada_falha_e_nunca_mais_de_2_tentativas(monkeypatch):
    cams = [{"ip": "10.0.0.1", "mac": "m1"}, {"ip": "10.0.0.2", "mac": "m2"}, {"ip": "10.0.0.3", "mac": "m3"}]
    certa = {"10.0.0.1": "VELHA", "10.0.0.2": "NOVA", "10.0.0.3": "OUTRA"}
    guardadas = {m: {"username": "admin", "password": "VELHA"} for m in ("m1", "m2", "m3")}
    tent, salvas, site = _cenario(monkeypatch, cams, certa, guardadas)
    e = _rodar()
    assert e["resultado"] == {"guardada_funciona": 1, "aprendeu": 1, "nova_recusada": 1}
    assert salvas == {"m2": "NOVA"}            # so onde a nova funcionou
    assert tent["10.0.0.1"] == 1                # guardada funcionou: nem testa a nova
    assert max(tent.values()) <= 2              # Intelbras bloqueia com mais
    assert site == ["NOVA"]                     # 1 aprendeu >= 1 recusou as duas


def test_sem_resposta_nao_grava_nada(monkeypatch):
    cams = [{"ip": "10.0.0.9", "mac": "m9"}]
    tent, salvas, site = _cenario(monkeypatch, cams, {"10.0.0.9": "NOVA"},
                                  {"m9": {"username": "admin", "password": "VELHA"}}, sem_resposta={"10.0.0.9"})
    e = _rodar()
    assert e["resultado"] == {"sem_resposta": 1} and salvas == {} and site == []


def test_ip_fora_do_conector_nao_e_consultado(monkeypatch):
    cams = [{"ip": "192.168.1.5", "mac": "m5", "remote_connector_id": "c1"}]
    tent, salvas, _ = _cenario(monkeypatch, cams, {"192.168.1.5": "NOVA"}, {})
    monkeypatch.setattr(L.vnat, "has_mapping", lambda cid: True)  # isolado, IP fora do mapa
    e = _rodar()
    assert e["resultado"] == {"fora_do_conector": 1} and tent == {}


def test_tarefa_de_outro_cliente_nao_aparece(monkeypatch):
    from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
    _cenario(monkeypatch, [], {}, {})
    tok = set_current_tenant_slug("cliente-a")
    try:
        job = L.iniciar("X", "admin", "s")["job_id"]
    finally:
        reset_current_tenant_slug(tok)
    tok = set_current_tenant_slug("cliente-b")
    try:
        assert L.estado(job) is None
    finally:
        reset_current_tenant_slug(tok)
