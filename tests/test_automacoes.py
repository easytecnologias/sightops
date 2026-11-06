"""Automacoes do Alerta Termico: simular nao toca no equipamento, valer manda o
comando certo, alvo so do inventario do cliente, intervalo e isolamento.
Nada sai para a rede: `_put` e o inventario sao falsos."""
import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug

SPEED = {"ip": "10.0.0.10", "connector_id": "c1", "mac": "aa", "site": "UFV-RODOANEL", "porta": 80, "nome": "22 - SPEED P 01", "modelo": "DS-2DE7A432IW-AEB"}
TERMICA = {**SPEED, "ip": "10.0.0.81", "nome": "03 - CAM P 03"}
INV = {"cliente-a": [SPEED, TERMICA], "cliente-b": []}


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    from app.core.tenant_context import get_current_tenant_slug
    from app.services import automacao_acoes as A, automacao_store as S, camera_credentials, db_store, recorder_xray
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(S, "equipamento_do_inventario", lambda ip, cid="": next(
        (dict(e) for e in INV.get(get_current_tenant_slug(), []) if e["ip"] == ip and e["connector_id"] == cid), None))
    monkeypatch.setattr(camera_credentials, "resolve_camera_credential", lambda mac, site: {"username": "admin", "password": "x"})
    monkeypatch.setattr(recorder_xray, "_base", lambda ip, porta, cid: f"http://virtual-{ip}")
    chamadas = []
    monkeypatch.setattr(A, "_put", lambda url, u, s, corpo="": (chamadas.append((url, corpo)), (200, "OK"))[1])
    tok = set_current_tenant_slug("cliente-a")
    db_store.init_db()
    yield A, S, chamadas
    reset_current_tenant_slug(tok)


REGRA = {"nome": "Rodoanel à noite", "acoes": [
    {"tipo": "speed_preset", "ip": "10.0.0.10", "connector_id": "c1", "preset": 7},
    {"tipo": "saida", "ip": "10.0.0.81", "connector_id": "c1", "saida": 1, "segundos": 30}]}


def test_nasce_em_simular_e_nao_toca_no_equipamento(amb):
    A, S, chamadas = amb
    r = S.salvar(REGRA)
    assert r["modo"] == "simular"
    assert A.disparar("cliente-a", "qualquer", "alerta1") == 1
    assert chamadas == []
    ex = S.listar()["execucoes"]
    assert len(ex) == 2 and all(e["resposta"].startswith("simulado") and e["modo"] == "simular" for e in ex)


def test_valer_manda_preset_e_saida_e_desliga_depois(amb, monkeypatch):
    A, S, chamadas = amb
    agendados = []
    monkeypatch.setattr(A, "_timer", lambda s, fn, args: agendados.append((s, fn, args)))
    S.salvar({**REGRA, "modo": "valer"})
    A.disparar("cliente-a", "x", "alerta1")
    assert chamadas[0][0] == "http://virtual-10.0.0.10/ISAPI/PTZCtrl/channels/1/presets/7/goto"
    assert chamadas[1][0] == "http://virtual-10.0.0.81/ISAPI/System/IO/outputs/1/trigger" and "high" in chamadas[1][1]
    assert agendados[0][0] == 30.0
    s, fn, args = agendados[0]
    fn(*args)
    assert "low" in chamadas[2][1]


def test_speed_volta_para_onde_estava(amb, monkeypatch):
    A, S, chamadas = amb
    agendados = []
    monkeypatch.setattr(A, "_timer", lambda s, fn, args: agendados.append((s, fn, args)))
    monkeypatch.setattr(A, "_posicao", lambda base, cred: (84, 3087, 10))
    S.salvar({"nome": "Speed", "modo": "valer", "acoes": [{"tipo": "speed_preset", "ip": "10.0.0.10", "connector_id": "c1", "preset": 1, "voltar_s": 45}]})
    A.disparar("cliente-a", "x", "a")
    assert agendados[0][0] == 45.0
    s, fn, args = agendados[0]
    fn(*args)
    assert chamadas[-1][0].endswith("/ISAPI/PTZCtrl/channels/1/absolute")
    assert "<elevation>84</elevation><azimuth>3087</azimuth><absoluteZoom>10</absoluteZoom>" in chamadas[-1][1]


def test_falha_do_equipamento_fica_no_historico(amb, monkeypatch):
    A, S, _ = amb
    monkeypatch.setattr(A, "_put", lambda *a, **k: (500, "erro interno"))
    S.salvar({**REGRA, "modo": "valer"})
    A.disparar("cliente-a", "x", "a")
    ex = S.listar()["execucoes"]
    assert ex and all(e["ok"] == 0 and "HTTP 500" in e["resposta"] for e in ex)


def test_respeita_intervalo_e_regra_desligada(amb):
    A, S, _ = amb
    S.salvar(REGRA)
    assert A.disparar("cliente-a", "x", "a1") == 1
    assert A.disparar("cliente-a", "x", "a2") == 0
    S.salvar({**REGRA, "nome": "Desligada", "ativo": False})
    assert len(S.regras_da_camera("x")) == 1


def test_alvo_fora_do_inventario_e_recusado(amb):
    _, S, _ = amb
    with pytest.raises(ValueError, match="inventário"):
        S.salvar({"nome": "x", "acoes": [{"tipo": "saida", "ip": "8.8.8.8", "connector_id": "", "saida": 1}]})
    with pytest.raises(ValueError, match="faixa"):
        S.salvar({"nome": "x", "acoes": [{"tipo": "speed_preset", "ip": "10.0.0.10", "connector_id": "c1", "preset": 999}]})
    with pytest.raises(ValueError, match="ação"):
        S.salvar({"nome": "x", "acoes": []})


def test_isolamento_entre_clientes(amb):
    A, S, chamadas = amb
    r = S.salvar({**REGRA, "modo": "valer"})
    tok = set_current_tenant_slug("cliente-b")
    try:
        assert S.listar()["automacoes"] == [] and S.regras_da_camera("x") == []
        with pytest.raises(LookupError):
            S.excluir(r["id"])
        assert A.disparar("cliente-b", "x", "a") == 0
    finally:
        reset_current_tenant_slug(tok)
    assert chamadas == []


def _restringir(monkeypatch, sites):
    import app.core.permissions as P
    monkeypatch.setattr(P, "sites_da_sessao", lambda: sites)


def test_usuario_restrito_nao_ve_nem_aciona_regra_de_outro_site(amb, monkeypatch):
    A, S, chamadas = amb
    r = S.salvar({**REGRA, "modo": "valer"})
    assert r["acoes"][0]["site"] == "UFV-RODOANEL"
    S.registrar_execucao(r["id"], "a", "valer", r["acoes"][0], True, "ok")
    _restringir(monkeypatch, ["OUTRO-SITE"])
    d = S.listar()
    assert d["automacoes"] == [] and d["execucoes"] == []
    for fn in (lambda: S.obter(r["id"]), lambda: S.excluir(r["id"]), lambda: S.salvar(REGRA, r["id"])):
        with pytest.raises((LookupError, ValueError)):
            fn()
    assert chamadas == []
    # o motor em segundo plano nao tem usuario: continua rodando
    _restringir(monkeypatch, None)
    monkeypatch.setattr(A, "_dentro_do_intervalo", lambda regra: False)
    monkeypatch.setattr(A, "_timer", lambda s, fn, args: None)
    assert A.disparar("cliente-a", "x", "a2") == 1 and chamadas


def test_restrito_nao_cria_regra_para_todas_as_termicas(amb, monkeypatch):
    _, S, _ = amb
    _restringir(monkeypatch, ["UFV-RODOANEL"])
    with pytest.raises(ValueError, match="câmera de origem"):
        S.salvar(REGRA)


def test_saida_que_nao_desliga_fica_no_historico(amb, monkeypatch):
    A, S, _ = amb
    monkeypatch.setattr(A, "ESPERA_DESLIGAR_S", 0)
    r = S.salvar(REGRA)
    tentativas = []
    monkeypatch.setattr(A, "_put", lambda *a, **k: (tentativas.append(1), (500, "erro"))[1])
    A._desligar_depois("cliente-a", r["acoes"][1], r["id"])
    assert len(tentativas) == 3
    assert S.listar()["execucoes"][0]["ok"] == 0 and "não desligou" in S.listar()["execucoes"][0]["resposta"]


def test_saida_que_nao_desliga_fica_ligada_ao_alerta(monkeypatch):
    from app.services import automacao_acoes as A
    gravados = []
    monkeypatch.setattr(A, "_saida_estado", lambda t, a, e: (False, "sem resposta"))
    monkeypatch.setattr(A, "ESPERA_DESLIGAR_S", 0)
    monkeypatch.setattr(A.automacao_store, "registrar_execucao", lambda *a: gravados.append(a))
    A._desligar_depois("cliente-a", {"ip": "1.1.1.1"}, "regra", "alerta1")
    assert gravados[0][1] == "alerta1" and gravados[0][4] is False


# ------------------------------------------------------ seguir o alarme ----
PONTOS = [{"x": 0.1, "y": 0.1, "az": 100, "el": 50}, {"x": 0.9, "y": 0.1, "az": 900, "el": 50},
          {"x": 0.9, "y": 0.9, "az": 900, "el": 450}, {"x": 0.1, "y": 0.9, "az": 100, "el": 450}]


def test_calibracao_acerta_os_4_pontos_e_o_meio():
    from app.services.speed_calibracao import apontar
    for p in PONTOS:
        assert apontar(PONTOS, p["x"], p["y"]) == (p["az"], p["el"])
    assert apontar(PONTOS, 0.5, 0.5) == (500, 250)


def test_calibracao_atravessa_o_norte():
    from app.services.speed_calibracao import apontar
    p = [dict(q) for q in PONTOS]
    p[0]["az"], p[3]["az"] = 3500, 3500
    p[1]["az"], p[2]["az"] = 100, 100
    assert apontar(p, 0.5, 0.5)[0] == 0     # meio entre 350 e 10 graus


def test_calibracao_recusa_pontos_ruins():
    from app.services.speed_calibracao import validar
    assert len(validar(PONTOS)) == 4
    with pytest.raises(ValueError):
        validar(PONTOS[:3])
    with pytest.raises(ValueError):       # em linha
        validar([{**q, "y": 0.5} for q in PONTOS])
    with pytest.raises(ValueError):       # espremidos
        validar([{**q, "x": 0.5 + q["x"] / 100, "y": 0.5 + q["y"] / 100} for q in PONTOS])
    with pytest.raises(ValueError):
        validar([{**PONTOS[0], "az": 9999}] + PONTOS[1:])


def test_seguir_vai_para_a_posicao_do_alarme_e_volta(monkeypatch):
    from app.services import automacao_acoes as A
    feitos, agenda = [], []
    monkeypatch.setattr(A, "_alvo", lambda a: ("http://speed", {"username": "u", "password": "s"}))
    monkeypatch.setattr(A, "_posicao", lambda b, c: (10, 20, 30))
    monkeypatch.setattr(A, "_absoluto", lambda b, c, pos: (feitos.append(pos), (200, ""))[1])
    acao = {"tipo": "speed_seguir", "nome": "S", "pontos": PONTOS, "zoom": 12, "voltar_s": 60}
    ok, msg = A.executar_acao("cliente-a", acao, "valer", agendar=lambda s, fn, a: agenda.append((s, a[2])), ponto=(0.5, 0.5))
    assert ok and feitos == [(250, 500, 12)] and agenda == [(60.0, (10, 20, 30))]
    feitos.clear()
    ok, msg = A.executar_acao("cliente-a", acao, "simular", ponto=(0.5, 0.5))
    assert ok and msg.startswith("simulado") and feitos == []
