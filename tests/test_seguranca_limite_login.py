"""Limite de login e de ativacao do app nao cai com X-Forwarded-For forjado, e
trocar de IP nao livra da trava por usuario. So dados ficticios."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.endpoints import alert as AL
from app.api.endpoints import auth as A
from app.core.security import ip_do_cliente


def _pedido(par="172.28.0.5", **cab):
    cabecalhos = {k.replace("_", "-").lower(): v for k, v in cab.items()}
    return SimpleNamespace(headers=cabecalhos, client=SimpleNamespace(host=par))


def test_cf_connecting_ip_vale_vindo_do_proxy():
    assert ip_do_cliente(_pedido(cf_connecting_ip="200.1.2.3", x_forwarded_for="9.9.9.9")) == "200.1.2.3"


def test_primeiro_x_forwarded_for_nao_vale():
    assert ip_do_cliente(_pedido(x_real_ip="200.1.2.4", x_forwarded_for="1.1.1.1, 200.1.2.4")) == "200.1.2.4"
    assert ip_do_cliente(_pedido(x_forwarded_for="1.1.1.1")) == "172.28.0.5"


def test_conexao_direta_de_fora_nao_escolhe_o_proprio_ip():
    assert ip_do_cliente(_pedido("8.8.8.8", cf_connecting_ip="1.1.1.1", x_real_ip="2.2.2.2")) == "8.8.8.8"


def test_cabecalho_invalido_e_ignorado():
    assert ip_do_cliente(_pedido(cf_connecting_ip="nao-e-ip", x_real_ip="200.1.2.5")) == "200.1.2.5"


def test_chave_nao_muda_com_x_forwarded_for_forjado():
    a = A._login_key(_pedido(cf_connecting_ip="200.1.2.3", x_forwarded_for="1.1.1.1"), "dono")
    b = A._login_key(_pedido(cf_connecting_ip="200.1.2.3", x_forwarded_for="2.2.2.2"), "dono")
    assert a == b
    assert AL._ativa_origem(_pedido(cf_connecting_ip="200.1.2.3", x_forwarded_for="1.1.1.1")) == "200.1.2.3"


@pytest.fixture()
def login(monkeypatch):
    monkeypatch.setattr(A, "authenticate_user", lambda u, p: None)
    A._LOGIN_FAILS.clear()
    yield
    A._LOGIN_FAILS.clear()


def _tentar(pedido, usuario="dono-a"):
    with pytest.raises(HTTPException) as e:
        A.api_auth_login(A.LoginRequest(username=usuario, password="errada"), pedido, None)
    return e.value.status_code


def test_ip_forjado_nao_escapa_do_limite(login):
    codigos = [_tentar(_pedido(cf_connecting_ip="200.1.2.3", x_forwarded_for=f"10.9.0.{i}")) for i in range(A._LOGIN_MAX_FAILS + 1)]
    assert codigos[:-1] == [401] * A._LOGIN_MAX_FAILS and codigos[-1] == 429


def test_trocar_de_ip_nao_escapa_da_trava_por_usuario(login):
    codigos = [_tentar(_pedido(cf_connecting_ip=f"200.1.{i // 200}.{i % 200 + 1}")) for i in range(A._LOGIN_MAX_FAILS_USUARIO + 1)]
    assert codigos[-1] == 429 and codigos[-2] == 401


def test_trava_de_um_usuario_nao_pega_outro(login):
    for i in range(A._LOGIN_MAX_FAILS_USUARIO):
        _tentar(_pedido(cf_connecting_ip=f"200.1.{i // 200}.{i % 200 + 1}"))
    assert _tentar(_pedido(cf_connecting_ip="200.9.9.9"), "outro-usuario") == 401
