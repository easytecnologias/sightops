"""Camera que nunca foi medida nao pode aparecer "online".

Caso real, JANGADEIROS, 19/10/2026: 38 das 41 cameras do inventario Switch
nunca ganharam host no Zabbix (o loop so criava hosts quando o cliente tinha
ZERO; ali havia 3). Ficaram com o "online" da importacao, sem data de medicao,
e a tela mostrava online duas cameras caidas (172.16.81.1 e .2).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import main
from app.services import dashboard_service as dash
from app.services import status_efetivo as se


def _iso(min_atras: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=min_atras)).isoformat()


def test_camera_sem_data_vira_nunca_verificado():
    linha = se.aplicar_em_linha({"ip": "172.16.81.2", "status": "online"}, set(), exigir_data=True)
    assert linha["status"] == "unknown"
    assert linha["status_motivo"] == se.MOTIVO_NUNCA
    assert linha["status_lido"] == "online"


def test_camera_medida_agora_segue_valendo():
    linha = se.aplicar_em_linha({"status": "online", "status_checked_at": _iso(2)}, set(), exigir_data=True)
    assert linha["status"] == "online"
    assert "status_motivo" not in linha


def test_sem_exigir_data_comportamento_antigo_para_olt_e_gravador():
    # OLT/gravador/conector ainda nao gravam data em todo caminho.
    linha = se.aplicar_em_linha({"status": "online"}, set())
    assert linha["status"] == "online"


def test_canal_nao_herda_camera_sem_data():
    canal = {"camera_ip": "172.16.81.2", "status": "online"}
    medidas = {"172.16.81.2": {"status": "online", "status_checked_at": None, "modo": "switch"}}
    linha = se.herdar_da_camera(canal, medidas)
    assert linha["status"] == "unknown"
    assert linha["status_motivo"] == se.MOTIVO_SEM_CAMERA


def test_dashboard_nao_conta_camera_sem_data():
    contas = dash._status_counts([
        {"ip": "172.16.81.1", "status": "online"},
        {"ip": "172.16.81.9", "status": "offline"},
        {"ip": "172.16.81.3", "status": "online", "status_checked_at": _iso(1)},
    ])
    assert contas == {"total": 3, "online": 1, "offline": 0, "unknown": 2}


def test_loop_cria_hosts_quando_falta_parte(monkeypatch):
    chamadas = []

    def falso_sync(payload):
        chamadas.append(payload["ensure_hosts"])
        return {"ok": True, "total": 82, "matched": 3, "sem_host": 38}

    monkeypatch.setattr(main, "scripts_zabbix_status_sync", falso_sync)
    main._ZABBIX_BOOTSTRAP_PARCIAL.clear()
    main._run_zabbix_status_sync_for_mode("switch", "grupo-jangadeiros")
    assert chamadas == [False, True]
    # no ciclo seguinte (menos de 1 h) so le, nao recria
    chamadas.clear()
    main._run_zabbix_status_sync_for_mode("switch", "grupo-jangadeiros")
    assert chamadas == [False]


def test_loop_nao_cria_quando_tudo_tem_host(monkeypatch):
    chamadas = []
    monkeypatch.setattr(main, "scripts_zabbix_status_sync",
                        lambda p: chamadas.append(p["ensure_hosts"]) or {"ok": True, "total": 82, "matched": 41, "sem_host": 0})
    main._ZABBIX_BOOTSTRAP_PARCIAL.clear()
    main._run_zabbix_status_sync_for_mode("switch", "rads")
    assert chamadas == [False]
