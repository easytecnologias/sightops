"""Relatorio de computadores em PDF (texto, ReportLab)."""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from app.services.windows_pdf_report import aceita_windows_11, build_windows_inventory_pdf, problemas

AGORA = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)


def _pc(**extra):
    base = {
        "hostname": "FIN-03", "ip": "10.0.0.43", "site": "SEDE", "sector": "FINANCEIRO",
        "status": "agent_reported", "last_seen": (AGORA - timedelta(minutes=5)).isoformat(),
        "os": {"name": "Microsoft Windows 11 Pro", "build": "26100"},
        "cpu": {"name": "Intel(R) Core(TM) i5-12400 CPU @ 2.50GHz", "cores": 6},
        "ram_gb": 15.7, "has_ssd": True, "disk_kind": "ssd", "disk_total_gb": 476,
        "security": {"defender_realtime": True, "defender_enabled": True, "tpm_present": True, "tpm_ready": True},
        "bitlocker": [{"mount_point": "C:", "protection_status": 1}],
        "volumes": [{"drive": "C:", "free_percent": 44, "free_gb": 210, "size_gb": 476}],
        "anydesk_id": "517204886", "serial": "7KXQ2M3",
    }
    base.update(extra)
    return base


@pytest.mark.parametrize("cpu, tpm, esperado", [
    ("Intel(R) Core(TM) i5-12400 CPU @ 2.50GHz", True, "sim"),
    ("Intel(R) Core(TM) i5-9500 CPU @ 3.00GHz", True, "sim"),
    ("Intel(R) Core(TM) i5-7400 CPU @ 3.00GHz", True, "nao"),        # 7a geracao
    ("11th Gen Intel(R) Core(TM) i3-1115G4 @ 3.00GHz", True, "sim"),
    ("AMD Ryzen 5 5600G with Radeon Graphics", True, "sim"),
    ("AMD Ryzen 5 1600 Six-Core Processor", True, "nao"),             # Ryzen 1000
    ("Intel(R) Celeron(R) J4005 CPU @ 2.00GHz", True, "verificar"),  # lista propria
    ("Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz", False, "nao"),       # sem TPM
    ("Intel(R) Core(TM) i5-10400 CPU @ 2.90GHz", None, "verificar"),  # agente sem admin
])
def test_aceita_windows_11(cpu, tpm, esperado):
    row = _pc(cpu={"name": cpu}, security={"tpm_present": tpm})
    assert aceita_windows_11(row)[0] == esperado


def test_problemas_seguem_a_tela():
    row = _pc(security={"defender_realtime": False, "tpm_present": True, "tpm_ready": True},
              volumes=[{"drive": "C:", "free_percent": 4, "free_gb": 9, "size_gb": 238}],
              os={"name": "Microsoft Windows 10 Pro"}, last_seen=(AGORA - timedelta(days=9)).isoformat())
    grupos = [p["grupo"] for p in problemas(row, AGORA)]
    assert grupos[:3] == ["seguranca", "disco", "contato"] and "windows" in grupos


def test_pc_saudavel_nao_tem_problema():
    assert problemas(_pc(), AGORA) == []


def _texto(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_e_texto_com_todas_as_secoes():
    rows = [_pc(), _pc(hostname="PORTARIA-01", has_ssd=False, disk_kind="hdd", ram_gb=3.8,
                       os={"name": "Microsoft Windows 10 Pro"},
                       cpu={"name": "Intel(R) Core(TM) i5-7400 CPU @ 3.00GHz"})]
    pdf = build_windows_inventory_pdf(rows, company_name="Mega Alarmes", agora=AGORA)
    assert pdf[:5] == b"%PDF-"
    txt = _texto(pdf)
    for trecho in ("Mega Alarmes", "Em resumo", "Precisa de atencao", "FICHA DO COMPUTADOR",
                   "Plano de troca", "Trocar o computador", "PORTARIA-01", "Inventario completo"):
        assert trecho in txt, trecho


def test_pdf_sem_computador_nao_quebra():
    txt = _texto(build_windows_inventory_pdf([], company_name="X", agora=AGORA))
    assert "Em resumo" in txt


def test_pdf_aguenta_dados_faltando():
    pdf = build_windows_inventory_pdf([{"hostname": "VAZIO", "ip": "10.0.0.9"}, {"ip": "10.0.0.10"}], agora=AGORA)
    assert "VAZIO" in _texto(pdf)
