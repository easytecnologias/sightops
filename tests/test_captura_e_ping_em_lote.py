"""Captura em paralelo nao perde foto; ping em lote respeita o IP virtual."""
import asyncio
import copy
import threading
import time

from app.api.endpoints import cameras as mod


def test_capturas_simultaneas_nao_perdem_a_foto_de_ninguem(tmp_path, monkeypatch):
    ips = [f"10.0.0.{n}" for n in range(1, 9)]
    banco = {"rows": [{"ip": ip, "titulo": ip} for ip in ips]}

    def carregar(mode="olt", site=""):
        rows = copy.deepcopy(banco["rows"])
        time.sleep(0.02)  # alarga a janela entre ler e gravar
        return rows

    def gravar(rows, mode="olt"):
        banco["rows"] = copy.deepcopy(rows)

    def foto(ip, user, password, pasta, timeout=None, retries=1):
        destino = tmp_path / f"{ip}.jpg"
        destino.write_bytes(b"jpg")
        return str(destino)

    monkeypatch.setattr(mod, "_ip_in_inventory", lambda ip, conector: True)
    monkeypatch.setattr(mod, "resolve_camera_password", lambda ip, u, p, c: ("admin", "x"))
    monkeypatch.setattr(mod, "snapshot_storage_dir", lambda: tmp_path)
    monkeypatch.setattr(mod, "get_snapshot", foto)
    monkeypatch.setattr(mod, "load_inventory_json", carregar)
    monkeypatch.setattr(mod, "save_inventory_json", gravar)

    largada = threading.Barrier(len(ips))
    erros = []

    def capturar(ip):
        largada.wait()
        try:
            mod.api_cameras_snapshot_capture(mod.SnapshotCaptureRequest(ip=ip))
        except Exception as exc:  # falha na thread nao derruba o teste sozinha
            erros.append(exc)

    threads = [threading.Thread(target=capturar, args=(ip,)) for ip in ips]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert erros == []
    sem_foto = [r["ip"] for r in banco["rows"] if not r.get("snapshot_url")]
    assert sem_foto == []


def _ping_fake(chamados):
    async def ping(ip, timeout, method, force, preferred_ports=None):
        chamados.append(ip)
        return {"ip": ip, "online": ip == "100.64.0.9", "rtt_ms": 3}
    return ping


def test_ping_em_lote_usa_o_ip_virtual_e_devolve_o_ip_real(monkeypatch):
    chamados = []
    monkeypatch.setattr(mod, "ping_with_cache", _ping_fake(chamados))
    monkeypatch.setattr(mod._vnat, "virtual_ip_for", lambda c, ip: "100.64.0.9" if c == "con1" else "")

    req = mod.PingBatchRequest(items=[{"ip": "10.200.0.5", "remote_connector_id": "con1"}])
    data = asyncio.run(mod.api_cameras_ping_many(req))

    assert chamados == ["100.64.0.9"]
    assert data["results"][0]["ip"] == "10.200.0.5"
    assert data["results"][0]["remote_connector_id"] == "con1"
    assert data["results"][0]["online"] is True


def test_ping_em_lote_mesmo_ip_em_dois_conectores_sao_duas_cameras(monkeypatch):
    chamados = []
    monkeypatch.setattr(mod, "ping_with_cache", _ping_fake(chamados))
    monkeypatch.setattr(
        mod._vnat, "virtual_ip_for", lambda c, ip: {"con1": "100.64.0.9", "con2": "100.64.0.10"}.get(c, "")
    )

    req = mod.PingBatchRequest(items=[
        {"ip": "10.200.0.5", "remote_connector_id": "con1"},
        {"ip": "10.200.0.5", "remote_connector_id": "con2"},
    ])
    data = asyncio.run(mod.api_cameras_ping_many(req))

    assert sorted(chamados) == ["100.64.0.10", "100.64.0.9"]
    assert data["count"] == 2


def test_ping_em_lote_atras_de_conector_sem_ip_virtual_nao_afirma_offline(monkeypatch):
    monkeypatch.setattr(mod, "ping_with_cache", _ping_fake([]))
    monkeypatch.setattr(mod._vnat, "virtual_ip_for", lambda c, ip: "")

    req = mod.PingBatchRequest(items=[{"ip": "10.200.0.5", "remote_connector_id": "con1"}])
    data = asyncio.run(mod.api_cameras_ping_many(req))

    assert data["results"][0]["online"] is False
    assert data["results"][0]["sem_rota"] is True
