"""MODULE_CATALOG (plano do cliente) cobre toda tela de menu dos MODULOS.

Tela fora do catalogo some de `parse_enabled_modules`: cliente com lista
explicita de modulos nunca consegue recebe-la (era o caso do PDV, de
alert-reports e de access-painel).
"""
import re
from pathlib import Path

from app.core import permissions
from app.services import auth_store

INDEX = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
# Usuario ONVIF nao e modulo de plano: vem junto com Ativacao/Implantar CFTV.
ADDON = {"deploy-onvif"}


def _views_do_menu():
    return set(re.findall(r'data-view="([a-z0-9-]+)"', INDEX.read_text(encoding="utf-8")))


def test_toda_tela_de_menu_dos_modulos_esta_no_catalogo():
    menu = _views_do_menu()
    faltam = sorted(
        v
        for m in permissions.MODULOS
        if not m.get("sempre_no_plano")
        for v in m["views"]
        if v in menu and v not in ADDON and v not in auth_store._MODULE_KEYS
    )
    assert faltam == []


def test_pdv_alerta_e_painel_de_acesso_no_catalogo():
    for chave in ("pdv-visao", "pdv-lojas", "pdv-vivo", "pdv-cupons", "alert-reports", "access-painel"):
        assert chave in auth_store._MODULE_KEYS


def test_catalogo_sem_chave_repetida():
    chaves = [m["key"] for m in auth_store.MODULE_CATALOG]
    assert len(chaves) == len(set(chaves))


def test_lista_explicita_guarda_pdv_e_ninguem_ganha_sem_pedir():
    lista = auth_store.parse_enabled_modules('["pdv-vivo", "alert-reports", "inexistente"]')
    assert lista == ["pdv-vivo", "alert-reports"]
    assert permissions.modulo_no_plano("pdv", lista)
    # cliente restrito sem nenhuma tela de PDV continua sem PDV
    assert not permissions.modulo_no_plano("pdv", ["inv-olt"])
    # NULL continua liberando tudo (nao muda nada para quem nunca foi configurado)
    assert auth_store.parse_enabled_modules(None) is None
