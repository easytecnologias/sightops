"""Instalacao do coletor pelo SightOps: so pelo IP virtual do conector, senha
cifrada e nunca na linha de comando. SSH falso: nada sai da maquina."""
from __future__ import annotations

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services import pdv_instalador as I
from app.services import pdv_store as S

SENHA = "senha-do-caixa-123"


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    from app.core import crypto, tenant_context
    from app.services import db_store

    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(crypto, "_key_path", lambda: tmp_path / "chave.key")
    crypto.reset_cache()
    db_store.init_db()
    monkeypatch.setattr(S, "gravadores_do_cliente", lambda: {"192.168.24.227"})
    # conector "c1" mapeia 192.168.24.0/23 -> 10.211.198.0/23
    from app.services import connector_routing_vnat as V

    def vip(cid, ip):
        if cid != "c1":
            return ip
        a, b, c, d = ip.split(".")
        return "10.211.%d.%s" % (198 + int(c) - 24, d) if (a, b, c) in (("192", "168", "24"), ("192", "168", "25")) else ip
    monkeypatch.setattr(V, "virtual_ip_for", vip)
    tok = set_current_tenant_slug("mercado-a")
    yield
    reset_current_tenant_slug(tok)


def _caixa(conector="c1"):
    cx = S.salvar_caixa({"nome": "PDV 01", "numero": 1})
    from app.services import db_store
    with db_store._conn() as c:  # conector direto no banco (salvar_caixa exige conector real)
        c.execute("UPDATE pdv_caixas SET connector_id=? WHERE id=?", (conector, cx["id"]))
    return cx


class CaixaFalso(object):
    """Faz o papel do PDV: guarda comandos, entradas e arquivos recebidos."""

    def __init__(self, sudo_ok=True, python="Python 3.8.0", pasta=True, instalar_ok=True):
        self.cmds, self.entradas, self.arquivos = [], [], []
        self.sudo_ok, self.python, self.pasta, self.instalar_ok = sudo_ok, python, pasta, instalar_ok
        self.conexoes = []

    def abrir(self, vip, porta, usuario, senha, hostkey):
        self.conexoes.append((vip, porta, usuario, senha, hostkey))
        if senha != SENHA:
            raise Exception("Authentication failed.")
        if hostkey and hostkey != "SHA256:caixa1":
            raise I.ErroInstalacao("A chave SSH do caixa mudou")
        return _Cliente(self), "SHA256:caixa1"


class _Canal(object):
    def __init__(self, cod):
        self.cod = cod

    def shutdown_write(self):
        pass

    def recv_exit_status(self):
        return self.cod


class _Fluxo(object):
    def __init__(self, texto="", cod=0, onde=None):
        self.texto, self.channel, self.onde = texto, _Canal(cod), onde

    def write(self, s):
        self.onde.append(s)

    def flush(self):
        pass

    def read(self):
        return self.texto.encode()


class _Sftp(object):
    def __init__(self, cx):
        self.cx = cx

    def mkdir(self, d, modo):
        pass

    def put(self, origem, destino):
        self.cx.arquivos.append(destino)

    def close(self):
        pass


class _Cliente(object):
    def __init__(self, cx):
        self.cx = cx

    def exec_command(self, cmd, timeout=0):
        self.cx.cmds.append(cmd)
        cx = self.cx
        if cmd.startswith("python3"):
            out = cx.python + ("\nPASTA_OK\n3" if cx.pasta else "")
            cod = 0
        elif cmd == "sudo -S -p '' true":
            out, cod = "", 0 if cx.sudo_ok else 1
        elif "instalar.sh" in cmd:
            token = cmd.split("'")[7]
            out = ("Pronto. token %s" % token) if cx.instalar_ok else "falhou"
            cod = 0 if cx.instalar_ok else 1
        elif cmd.startswith("systemctl"):
            out, cod = "active\nTue 2026-10-27 15:00:00 -03", 0
        else:
            out, cod = "log...", 0
        return _Fluxo(onde=cx.entradas), _Fluxo(out, cod), _Fluxo("")

    def open_sftp(self):
        return _Sftp(self.cx)

    def close(self):
        pass


def _acesso(cx, **kw):
    dados = {"pdv_host": "192.168.24.97", "ssh_porta": 22, "ssh_usuario": "rpdv", "ssh_senha": SENHA}
    dados.update(kw)
    return I.salvar_acesso(cx["id"], dados)


def test_ip_publico_e_recusado(banco):
    cx = _caixa()
    with pytest.raises(ValueError):
        _acesso(cx, pdv_host="138.99.28.216")
    with pytest.raises(ValueError):
        _acesso(cx, pdv_host="nao-e-ip")


def test_senha_cifrada_e_nunca_volta(banco):
    cx = _caixa()
    a = _acesso(cx)
    assert a["tem_senha"] and "ssh_senha" not in a
    from app.services import db_store
    with db_store._conn() as c:
        enc = c.execute("SELECT ssh_senha_enc FROM pdv_caixas WHERE id=?", (cx["id"],)).fetchone()[0]
    assert enc and SENHA not in enc
    assert S.listar_caixas()[0]["tem_senha"] is True and "ssh_senha_enc" not in S.listar_caixas()[0]
    assert _acesso(cx, ssh_senha="")["tem_senha"]                        # em branco mantem
    assert not _acesso(cx, pdv_host="192.168.24.98", ssh_senha="")["tem_senha"]  # outro destino: apaga


def test_sem_conector_ou_fora_da_rede_nao_instala(banco):
    sem = _caixa(conector="")
    _acesso(sem)
    falso = CaixaFalso()
    r = I.instalar(sem["id"], "https://x", abrir=falso.abrir)
    assert not r["ok"] and "conector" in r["passos"][0]["detalhe"] and falso.conexoes == []
    from app.services import db_store
    with db_store._conn() as c:
        c.execute("UPDATE pdv_caixas SET connector_id='c1'")
    _acesso(sem, pdv_host="10.0.0.5")  # privado, mas fora das redes do conector
    r = I.instalar(sem["id"], "https://x", abrir=falso.abrir)
    assert not r["ok"] and "não está nas redes do conector" in r["passos"][0]["detalhe"] and falso.conexoes == []


def test_instala_pelo_ip_virtual_sem_senha_na_linha_de_comando(banco):
    cx = _caixa()
    _acesso(cx)
    falso = CaixaFalso()
    r = I.instalar(cx["id"], "https://sightops.exemplo", abrir=falso.abrir)
    assert r["ok"], r
    assert falso.conexoes[0][:3] == ("10.211.198.97", 22, "rpdv")  # IP VIRTUAL, nunca o real nem o publico
    assert all(SENHA not in c for c in falso.cmds)                  # senha so pela entrada padrao
    assert SENHA + "\n" in falso.entradas
    assert {a.rsplit("/", 1)[1] for a in falso.arquivos} == set(I.ARQUIVOS)
    instalar = next(c for c in falso.cmds if "instalar.sh" in c)
    assert "'https://sightops.exemplo'" in instalar and "rm -rf /tmp/sightops-pdv-" in instalar
    detalhes = " ".join(p["detalhe"] for p in r["passos"])
    token = instalar.split("'")[7]
    assert token.startswith("pdv_") and token not in detalhes and SENHA not in detalhes
    assert S.autenticar(cx["id"], token)                            # token novo vale
    caixa = S.listar_caixas()[0]
    assert caixa["instalacao_estado"] == "instalado"


def test_chave_do_caixa_e_lembrada(banco):
    cx = _caixa()
    _acesso(cx)
    falso = CaixaFalso()
    I.instalar(cx["id"], "https://x", abrir=falso.abrir)
    I.instalar(cx["id"], "https://x", abrir=falso.abrir)
    assert falso.conexoes[1][4] == "SHA256:caixa1"


@pytest.mark.parametrize("falso,passo", [
    (CaixaFalso(sudo_ok=False), "sudo"),
    (CaixaFalso(pasta=False), "Conferir"),
    (CaixaFalso(instalar_ok=False), "Instalar"),
])
def test_falhas_param_e_dizem_onde(banco, falso, passo):
    cx = _caixa()
    _acesso(cx)
    r = I.instalar(cx["id"], "https://x", abrir=falso.abrir)
    assert not r["ok"] and passo in r["passos"][-1]["passo"] and not r["passos"][-1]["ok"]
    assert S.listar_caixas()[0]["instalacao_estado"] == "falhou"


def test_senha_errada(banco):
    cx = _caixa()
    _acesso(cx, ssh_senha="outra")
    r = I.instalar(cx["id"], "https://x", abrir=CaixaFalso().abrir)
    assert not r["ok"] and r["passos"][-1]["passo"] == "Entrar no caixa"


def test_status_do_servico(banco):
    cx = _caixa()
    _acesso(cx)
    st = I.status(cx["id"], abrir=CaixaFalso().abrir)
    assert st["ok"] and st["ativo"] and st["estado"] == "active"


def test_rotas_de_instalacao_sao_de_admin():
    from fastapi import FastAPI

    from app.core.security import ApiAuthMiddleware
    from app.core.settings import get_settings
    m = ApiAuthMiddleware(FastAPI(), get_settings())
    for rota in ("acesso", "instalar", "coletor"):
        assert m._match_role_rule("/api/pdv/caixas/abc/%s" % rota, "POST") == "admin"
