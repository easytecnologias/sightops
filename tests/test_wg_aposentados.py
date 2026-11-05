"""Conector migrado a mao (iso_manual) sai do wg-sightops so se estiver na lista."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ARQ = Path(__file__).resolve().parent.parent / "deploy" / "host-scripts" / "sightops_wireguard_sync.py"


@pytest.fixture()
def wg(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("wg_sync_teste", ARQ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.delenv("SIGHTOPS_WG_APOSENTADOS", raising=False)
    monkeypatch.setattr(m, "WG_APOSENTADOS_PATH", tmp_path / "wg_aposentados.txt")

    class ComInterface:
        """Finge que /sys/class/net/wgc<N> existe."""

        def __init__(self, caminho):
            self.caminho = str(caminho)

        def exists(self):
            return self.caminho.startswith("/sys/class/net/wgc")

    monkeypatch.setattr(m, "Path", ComInterface)
    return m


MANUAL = {
    "id": "conn-a", "name": "A", "iso_manual": True, "iso_index": 2,
    "tunnel": {"enabled": True, "type": "wireguard", "client_public_key": "chave-a",
               "client_address": "10.250.0.9/32", "client_lans": ["172.16.16.0/20"]},
}


def test_manual_fora_da_lista_segue_como_antes(wg):
    assert wg._is_auto_isolated(MANUAL) is False
    assert "chave-a" in wg.compute_target_state([MANUAL])
    assert wg.isolated_pubkeys([MANUAL]) == {}


def test_manual_na_lista_sai_do_tunel_antigo(wg):
    wg.WG_APOSENTADOS_PATH.write_text("# aposentados\nconn-a  # Mata Grande\n", encoding="utf-8")
    assert wg._is_auto_isolated(MANUAL) is True
    assert wg.compute_target_state([MANUAL]) == {}
    assert wg.isolated_pubkeys([MANUAL]) == {"chave-a": "A"}


def test_variavel_substitui_o_arquivo_para_simular(wg, monkeypatch):
    wg.WG_APOSENTADOS_PATH.write_text("conn-a\n", encoding="utf-8")
    monkeypatch.setenv("SIGHTOPS_WG_APOSENTADOS", "")
    assert wg._is_auto_isolated(MANUAL) is False
    monkeypatch.setenv("SIGHTOPS_WG_APOSENTADOS", "outro, conn-a")
    assert wg._is_auto_isolated(MANUAL) is True


def test_sem_interface_nova_nao_aposenta(wg, monkeypatch):
    monkeypatch.setenv("SIGHTOPS_WG_APOSENTADOS", "conn-a")
    monkeypatch.setattr(wg, "Path", Path)  # /sys/class/net/wgc2 nao existe aqui
    assert wg._is_auto_isolated(MANUAL) is False
