"""Notificacao do Alerta Termico: quem recebe (cliente e site), token que muda de
dono, app desinstalado e falta da chave. Nada sai para a rede."""
import json

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug

T1, T2, T3 = "a" * 30, "b" * 30, "c" * 30
USERS = {}
CAM = {"id": "c1", "nome": "03 - CAM P 03", "site": "UFV-RODOANEL"}


class Resp:
    def __init__(self, status=200, text="{}"):
        self.status_code, self.text = status, text


@pytest.fixture()
def av(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    from app.services import db_store, termico_avisos as A
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(A, "_bearer", lambda: ("oauth", "sightops"))
    import app.services.auth_store as AS
    import app.core.permissions as P
    monkeypatch.setattr(AS, "usuario_para_aviso", lambda i: dict(USERS[i]) if i in USERS else None)
    monkeypatch.setattr(P, "sites_do_usuario", lambda u, dados=None: u.get("_sites", []))
    monkeypatch.setattr(P, "pode", lambda u, m, n="ver": u.get("_pode", True))
    USERS.clear()
    tok = set_current_tenant_slug("cliente-a")
    db_store.init_db()
    yield A
    reset_current_tenant_slug(tok)


def _u(i, tenant="cliente-a", **k):
    USERS[i] = {"id": i, "tenant_slug": tenant, "effective_enabled_modules": None, **k}


def _posts(A, monkeypatch, resposta=None):
    feitos = []
    monkeypatch.setattr(A.requests, "post", lambda url, json=None, timeout=0, headers=None: (feitos.append((url, json, headers)), resposta or Resp())[1])
    return feitos


def test_so_recebe_quem_pode_ver_o_site(av, monkeypatch):
    A = av
    _u(1); _u(2, _sites=["ufv-rodoanel"]); _u(3, _sites=["UFV-DEMERVAL-LOBAO"])
    A.registrar(T1, 1, "todos"); A.registrar(T2, 2, "rodoanel"); A.registrar(T3, 3, "demerval")
    feitos = _posts(A, monkeypatch)
    r = A.avisar_pessoa("cliente-a", CAM, {"id": "al1"}, {"temp_media": 34.1})
    assert r["enviados"] == 2
    assert {f[1]["message"]["token"] for f in feitos} == {T1, T2}
    u, corpo, h = feitos[0]
    assert u == "https://fcm.googleapis.com/v1/projects/sightops/messages:send" and h["Authorization"] == "Bearer oauth"
    m = corpo["message"]
    assert m["data"] == {"tipo": "termico", "alerta_id": "al1"} and m["android"]["priority"] == "HIGH"
    assert m["android"]["notification"]["channel_id"] == "alarme" and "34,1 °C" in m["notification"]["body"]


def test_desligado_ou_sem_modulo_para_de_receber_na_hora(av, monkeypatch):
    A = av
    _u(1); A.registrar(T1, 1, "ana")
    assert A._destinos("cliente-a", "UFV-RODOANEL") == [T1]
    del USERS[1]                                   # usuario inativo ou excluido
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []
    _u(1, _pode=False)                             # perdeu o modulo
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []
    _u(1, _sites=["OUTRA"])                        # perdeu o site
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []
    _u(1, effective_enabled_modules=["alert-live"])     # saiu do plano
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []


def test_erro_ao_ler_o_cadastro_nao_manda(av, monkeypatch):
    import app.services.auth_store as AS
    A = av
    _u(1); A.registrar(T1, 1, "ana")

    def cai(i):
        raise RuntimeError("banco fora")
    monkeypatch.setattr(AS, "usuario_para_aviso", cai)
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []


def test_alerta_de_um_cliente_nao_vai_para_outro(av, monkeypatch):
    A = av
    _u(1); A.registrar(T1, 1, "ana")
    feitos = _posts(A, monkeypatch)
    assert A.avisar_pessoa("cliente-b", CAM, {"id": "x"})["enviados"] == 0 and feitos == []


def test_quem_operava_como_outro_cliente_nao_recebe_dele(av):
    A = av
    _u(9, tenant="plataforma")
    A.registrar(T1, 9, "admin")        # registrado com cliente-a como efetivo
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []


def test_celular_que_troca_de_cliente_para_de_receber_o_antigo(av, monkeypatch):
    A = av
    _u(1); _u(2, tenant="cliente-b")
    A.registrar(T1, 1, "ana")
    tok = set_current_tenant_slug("cliente-b")
    try:
        A.registrar(T1, 2, "bia")
    finally:
        reset_current_tenant_slug(tok)
    feitos = _posts(A, monkeypatch)
    assert A.avisar_pessoa("cliente-a", CAM, {"id": "x"})["enviados"] == 0
    assert A.avisar_pessoa("cliente-b", CAM, {"id": "x"})["enviados"] == 1 and len(feitos) == 1


def test_app_desinstalado_some_e_falha_nao_derruba(av, monkeypatch):
    A = av
    _u(1); A.registrar(T1, 1, "ana")
    _posts(A, monkeypatch, Resp(404, json.dumps({"error": {"status": "NOT_FOUND"}})))
    assert A.avisar_pessoa("cliente-a", CAM, {"id": "x"})["removidos"] == 1
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []
    A.registrar(T1, 1, "ana")

    def cai(*a, **k):
        raise OSError("sem rede")
    monkeypatch.setattr(A.requests, "post", cai)
    assert A.avisar_pessoa("cliente-a", CAM, {"id": "x"})["falhas"] == 1


def test_sem_chave_nao_quebra_o_alerta(av, monkeypatch):
    A = av
    _u(1); A.registrar(T1, 1, "ana")

    def sem(*a):
        raise FileNotFoundError("chave do Firebase não encontrada")
    monkeypatch.setattr(A, "_bearer", sem)
    feitos = _posts(A, monkeypatch)
    assert A.avisar_pessoa("cliente-a", CAM, {"id": ""}) == {"enviados": 0, "falhas": 1, "removidos": 0} and feitos == []


def test_sair_ou_encerrar_sessoes_para_de_receber(av):
    A = av
    _u(1); A.registrar(T1, 1, "ana"); A.registrar(T2, 1, "ana")
    A.esquecer(T1)
    assert A._destinos("cliente-a", "UFV-RODOANEL") == [T2]
    A.esquecer_usuario(1)
    assert A._destinos("cliente-a", "UFV-RODOANEL") == []
    with pytest.raises(ValueError):
        A.registrar("curto", 1, "ana")


def test_sem_chave_do_firebase_conta_como_falha(monkeypatch):
    from app.services import termico_avisos as A
    monkeypatch.setattr(A, "_destinos", lambda t, s: ["a", "b"])
    def sem_chave():
        raise RuntimeError("chave invalida")
    monkeypatch.setattr(A, "_bearer", sem_chave)
    assert A.enviar_aviso("cliente-a", "S", "t", "c", {})["falhas"] == 2


def test_mensagem_leva_sirene_e_foto(monkeypatch):
    from app.services import termico_avisos as A
    a = A._mensagem("tk", "t", "c", {}, "https://x/foto")["message"]["android"]["notification"]
    assert a["channel_id"] == "alarme" and a["sound"] == "sirene" and a["image"] == "https://x/foto"
    assert "image" not in A._mensagem("tk", "t", "c", {})["message"]["android"]["notification"]


def test_link_da_foto_e_assinado_preso_ao_alerta_e_vence(monkeypatch):
    from app.services import termico_avisos as A
    monkeypatch.setenv("SIGHTOPS_PUBLIC_URL", "https://sightops.exemplo")
    monkeypatch.setattr("app.core.crypto._load_or_create_key", lambda: b"k" * 32)
    aid = "a" * 32
    partes = A.link_foto("cliente-a", aid, agora=1000).split("/")
    expira, sig = int(partes[-2]), partes[-1]
    assert partes[-4:-2] == ["cliente-a", aid] and expira == 1000 + A.FOTO_VALE_S
    assert A.foto_valida("cliente-a", aid, expira, sig, agora=1000)
    assert not A.foto_valida("cliente-b", aid, expira, sig, agora=1000)
    assert not A.foto_valida("cliente-a", "b" * 32, expira, sig, agora=1000)
    assert not A.foto_valida("cliente-a", aid, expira, sig, agora=expira + 1)
    assert not A.foto_valida("cliente-a", aid, expira + 99999, sig, agora=1000)
    monkeypatch.setenv("SIGHTOPS_PUBLIC_URL", "http://interno")
    assert A.link_foto("cliente-a", aid) == ""


def test_link_da_foto_nao_quebra_com_entrada_estranha(monkeypatch):
    from app.services import termico_avisos as A
    monkeypatch.setattr("app.core.crypto._load_or_create_key", lambda: b"k" * 32)
    assert not A.foto_valida("cliente-a", "a" * 32, 10 ** 400, "x", agora=1000)
    assert not A.foto_valida("cliente-a", "a" * 32, 1100, "é", agora=1000)
