"""Parte 5 do mini DVR: edicao de canal vira registro com estado anterior, o
desfazer volta o canal e recusa registro de outro gravador."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import recorder_canais as RC


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("cliente-teste")
    yield tmp_path / "gb"
    tenant_context.reset_current_tenant_slug(token)


def test_apontar_canal_registra_e_desfaz_para_o_ip_velho(base):
    reg = RC.registrar("editar", host="10.10.9.120", conector="c1", canal=7, por="ana", base=base,
                       antes={"ip": "10.10.10.57", "nome": "PORTARIA", "mac": "aa:bb", "senha": "nao-guarda"},
                       depois={"ip": "10.10.10.157", "mac": "aa:bb"})
    assert reg["titulo"] == "Canal 07: camera apontada para 10.10.10.157" and reg["por"] == "ana"
    assert reg["desfazivel_canal"] and reg["desfazivel"] is False          # o desfazer de configuracao nao mexe
    assert "senha" not in reg["antes"]                                       # senha nunca vai para o registro
    plano = RC.plano_desfazer(RC.ler(reg["id"], base), "10.10.9.120", "c1")
    assert plano == {"acao": "editar", "canal": 7, "ip": "10.10.10.57", "mac": "aa:bb", "user": "",
                     "protocolo": "", "nome": "PORTARIA"}
    RC.marcar_desfeito(RC.ler(reg["id"], base), "bia", base)
    with pytest.raises(ValueError, match="ja foi desfeito"):
        RC.plano_desfazer(RC.ler(reg["id"], base), "10.10.9.120", "c1")


def test_desfazer_recusa_outro_gravador_e_registro_sem_estado(base):
    reg = RC.registrar("editar", host="10.10.9.120", conector="c1", canal=3, por="", base=base, depois={"ip": "1.1.1.1"})
    assert not reg["desfazivel_canal"]                                       # tela antiga nao mandou o antes
    with pytest.raises(ValueError, match="nao guardou"):
        RC.plano_desfazer(reg, "10.10.9.120", "c1")
    ok = RC.registrar("renomear", host="10.10.9.120", conector="c1", canal=3, por="", base=base,
                      antes={"nome": "VELHO"}, depois={"nome": "NOVO"})
    with pytest.raises(ValueError, match="outro gravador"):
        RC.plano_desfazer(ok, "10.10.9.120", "c2")                          # mesmo IP, outro conector
    assert RC.plano_desfazer(ok, "10.10.9.120", "c1") == {"acao": "renomear", "canal": 3, "nome": "VELHO"}
    exc = RC.registrar("excluir", host="h", conector="", canal=5, por="", base=base, antes={"ip": "10.0.0.5", "nome": "X"})
    assert RC.plano_desfazer(exc, "h", "")["acao"] == "adicionar"


def test_registro_com_id_inventado_e_recusado(base):
    for rid in ("../../etc", "abc", ""):
        with pytest.raises(ValueError):
            RC.ler(rid, base)


def test_senha_da_camera_usa_a_salva_quando_a_tela_nao_manda(monkeypatch):
    import app.services.camera_credentials as CC
    monkeypatch.setattr(CC, "resolve_camera_credential", lambda mac, site: {"username": "admin", "password": "s3cr3t"} if mac == "aa:bb" else None)
    assert RC.senha_da_camera("aa:bb", "SITE", "", "") == ("admin", "s3cr3t")
    assert RC.senha_da_camera("aa:bb", "SITE", "op", "digitada") == ("op", "digitada")
    assert RC.senha_da_camera("cc:dd", "SITE", "", "") == ("admin", "")


def test_senha_salva_so_com_o_mac_que_o_inventario_tem_para_o_canal(monkeypatch):
    import app.services.camera_credentials as CC
    monkeypatch.setattr(CC, "resolve_camera_credential", lambda mac, site: {"username": "admin", "password": "s3cr3t"} if mac else (
        {"username": "admin", "password": "dosite"} if site == "RESERVA" else None))
    monkeypatch.setattr(RC, "canal_no_inventario", lambda host, canal: {"mac": "AA:BB:CC:DD:EE:07", "site": "RESERVA"} if canal == 7 else {"mac": "", "site": ""})
    assert RC.senha_autorizada("h", 7, "aa-bb-cc-dd-ee-07", "", "") == ("admin", "s3cr3t")   # mesmo MAC, outro formato
    assert RC.senha_autorizada("h", 7, "11:22:33:44:55:66", "", "") == ("admin", "")        # MAC inventado: sem senha salva
    assert RC.senha_autorizada("h", 3, "aa:bb:cc:dd:ee:07", "", "") == ("admin", "")        # canal sem MAC no inventario
    assert RC.senha_autorizada("h", 7, "", "op", "digitada") == ("op", "digitada")
