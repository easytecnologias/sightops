"""Rota leve do app: so o id da ultima passagem, com o local permitido ao
usuario e uma porta virando filtro de leitor."""
from app.api.endpoints import access_control as A


def test_ultima_passagem_respeita_local_e_porta(monkeypatch):
    pedidos = []
    monkeypatch.setattr(A, "_site_do_painel", lambda s: "JARDINS II")
    monkeypatch.setattr(A, "list_access_report_events",
                        lambda f: pedidos.append(f) or [{"id": "e9", "occurred_at": "2026-11-03 14:02:50"}])
    r = A.api_access_control_painel_ao_vivo_ultima(site="OUTRO", portas="leitor-1")
    assert r == {"id": "e9", "hora": "2026-11-03 14:02:50"}
    assert pedidos[0]["site"] == "JARDINS II" and pedidos[0]["device_id"] == "leitor-1" and pedidos[0]["limit"] == 1
    monkeypatch.setattr(A, "list_access_report_events", lambda f: [])
    assert A.api_access_control_painel_ao_vivo_ultima(site="", portas="") == {"id": "", "hora": ""}
