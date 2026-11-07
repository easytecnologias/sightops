"""Calibrador e medidor de horario do PDV: gravador x caixa, hora do caixa na chegada, Zabbix."""
from datetime import datetime, timedelta, timezone

from app.services import pdv_store as S
from app.services import zabbix_monitoring_service as Z
from tests.test_pdv_store import banco  # noqa: F401


def _caixa(nome, numero, host="192.168.24.227"):
    return S.salvar_caixa({"nome": nome, "numero": numero, "gravador_host": host, "gravador_canal": numero})


def _contato(caixa_id, offset_s, ha_s=10):
    from app.services import db_store
    quando = (datetime.now(timezone.utc) - timedelta(seconds=ha_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db_store._conn() as c:
        c.execute("UPDATE pdv_caixas SET ultimo_contato=?, relogio_pdv_offset_s=? WHERE id=?", (quando, offset_s, caixa_id))


def test_calibra_cada_caixa_lendo_o_gravador_uma_vez(banco):
    a, b, parado = _caixa("PDV 01", 1), _caixa("PDV 02", 2), _caixa("PDV 03", 3)
    _contato(a["id"], 0)
    _contato(b["id"], -1)
    _contato(parado["id"], 0, ha_s=900)  # coletor parado: hora do caixa velha
    lidos = []

    def ler(host, conector):
        lidos.append(host)
        return {"diferenca_s": -2, "latencia_s": 0.1}

    r = S.calibrar_relogios(ler=ler)
    assert r == {"medidos": 2, "pulados": 1, "falhas": []}
    assert lidos == ["192.168.24.227"]  # um gravador, uma leitura
    caixas = {c["nome"]: c for c in S.listar_caixas()}
    assert caixas["PDV 01"]["relogio_dvr_offset_s"] == -2   # -2 - 0
    assert caixas["PDV 02"]["relogio_dvr_offset_s"] == -1   # -2 - (-1)
    assert caixas["PDV 03"]["relogio_dvr_offset_s"] is None
    j = S.janela_video(a["id"], "2026-11-07 12:00:20")
    assert j["momento_gravador"] == "2026-11-07 12:00:18"


def test_gravador_fora_nao_para_os_outros_nem_mostra_senha(banco, monkeypatch):
    monkeypatch.setattr(S, "gravadores_do_cliente", lambda: {"192.168.24.227", "10.0.0.9"})
    a = _caixa("PDV 01", 1)
    b = _caixa("PDV 02", 2, host="10.0.0.9")
    _contato(a["id"], 0)
    _contato(b["id"], 0)

    def ler(host, conector):
        if host == "10.0.0.9":
            raise RuntimeError("http://admin:segredo123@10.0.0.9/ sem resposta")
        return {"diferenca_s": 3, "latencia_s": 0.1}

    r = S.calibrar_relogios(ler=ler)
    assert r["medidos"] == 1 and len(r["falhas"]) == 1
    assert "segredo123" not in r["falhas"][0]


def test_hora_do_caixa_e_medida_na_chegada_e_nao_depois_da_fila(banco, monkeypatch):
    import time
    cx = _caixa("PDV 01", 1)
    relogio = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    orig = S._processador

    def lento(*a, **k):  # fila/reconstrucao demorando como apos um restart
        time.sleep(2.2)
        return orig(*a, **k)

    monkeypatch.setattr(S, "_processador", lento)
    S.receber_lote(S.autenticar(cx["id"], cx["token"]), {"versao": "t", "relogio": relogio,
                        "lotes": [{"arquivo": "Teclas", "dia": "2026-10-27", "linhas": [[1, "x"]]}]})
    assert abs(S.listar_caixas()[0]["relogio_pdv_offset_s"]) <= 1


def test_entidade_leva_o_relogio_ao_zabbix(banco):
    cx = _caixa("PDV 01", 1)
    _contato(cx["id"], 0)
    S.registrar_relogio_dvr(cx["id"], -2)
    d = S.entidades_monitoramento()[0]["detail"]
    assert d["relogio_caixa_s"] == 0 and d["relogio_gravador_s"] == -2
    assert 0 <= d["relogio_medido_s"] < 60


def test_gatilhos_do_relogio_so_com_item_e_sem_duplicar():
    chamadas = []

    def fake_call(url, metodo, params, auth, req_id):
        chamadas.append((metodo, params))
        if metodo == "trigger.get":  # host 1 ja tem o de coletor parado
            return [{"triggerid": "9", "description": Z.GATILHO_PDV_CAIU, "hosts": [{"hostid": "1"}]}]
        return {"triggerids": ["x"]}

    orig = Z._call
    Z._call = fake_call
    try:
        nomes = {"pdv-a": {"entity_type": "pdv"}, "pdv-b": {"entity_type": "pdv"}}
        itens = {("1", "sightops.status"): "i1", ("1", "sightops.pdv_relogio_gravador_s"): "i2",
                 ("1", "sightops.pdv_relogio_caixa_s"): "i3", ("1", "sightops.pdv_relogio_medido_s"): "i4",
                 ("2", "sightops.status"): "i5"}
        n = Z._garantir_gatilhos_pdv("u", "a", nomes, {"pdv-a": "1", "pdv-b": "2"}, itens)
    finally:
        Z._call = orig
    criados = [g for m, p in chamadas if m == "trigger.create" for g in p]
    assert n == 4 == len(criados)
    desc = sorted(g["description"] for g in criados)
    assert desc == sorted([Z.GATILHO_PDV_RELOGIO_GRAVADOR, Z.GATILHO_PDV_RELOGIO_CAIXA, Z.GATILHO_PDV_CALIBRACAO,
                           Z.GATILHO_PDV_CAIU])
    por = {g["description"]: g for g in criados}
    assert por[Z.GATILHO_PDV_RELOGIO_GRAVADOR]["expression"] == "abs(last(/pdv-a/sightops.pdv_relogio_gravador_s))>5"
    assert "/pdv-b/" in por[Z.GATILHO_PDV_CAIU]["expression"]  # b so tem status: so o de coletor
    assert "min(/pdv-a/sightops.status,15m)=1" in por[Z.GATILHO_PDV_CALIBRACAO]["expression"]


def test_conector_de_um_gravador_nao_vale_para_o_proximo(banco, monkeypatch):
    import contextvars
    monkeypatch.setattr(S, "gravadores_do_cliente", lambda: {"192.168.24.227", "10.0.0.9"})
    a = _caixa("PDV 01", 1)
    b = _caixa("PDV 02", 2, host="10.0.0.9")
    _contato(a["id"], 0)
    _contato(b["id"], 0)
    conector = contextvars.ContextVar("conector_teste", default="")
    visto = []

    def ler(host, cid):  # como _abrir: deixa o conector no contexto
        visto.append(conector.get())
        conector.set("conector-do-" + host)
        return {"diferenca_s": 0, "latencia_s": 0.1}

    assert S.calibrar_relogios(ler=ler)["medidos"] == 2
    assert visto == ["", ""]


def test_nunca_medido_avisa_e_caixa_desligado_nao_manda_hora(banco):
    cx = _caixa("PDV 01", 1)
    _contato(cx["id"], 4, ha_s=3600)  # desligado ha 1 h, gravador nunca medido
    d = S.entidades_monitoramento()[0]["detail"]
    assert d["relogio_medido_s"] == S.RELOGIO_NUNCA_MEDIDO_S
    assert d["relogio_caixa_s"] is None
    _contato(cx["id"], 4)
    assert S.entidades_monitoramento()[0]["detail"]["relogio_caixa_s"] == 4


def test_laco_so_remede_quem_esta_velho(banco):
    a, b = _caixa("PDV 01", 1), _caixa("PDV 02", 2)
    _contato(a["id"], 0)
    _contato(b["id"], 0)
    S.registrar_relogio_dvr(a["id"], -2)  # medido agora
    lidos = []

    def ler(host, cid):
        lidos.append(host)
        return {"diferenca_s": -1, "latencia_s": 0.1}

    r = S.calibrar_relogios(ler=ler, idade_min_s=1800)
    assert r["medidos"] == 1  # so o PDV 02, nunca medido
    caixas = {c["nome"]: c for c in S.listar_caixas()}
    assert caixas["PDV 01"]["relogio_dvr_offset_s"] == -2 and caixas["PDV 02"]["relogio_dvr_offset_s"] == -1


def test_lote_atrasado_nao_vira_caixa_atrasado(banco):
    cx = _caixa("PDV 01", 1)
    caixa = S.autenticar(cx["id"], cx["token"])
    seq = iter(range(1, 100))

    def enviar(atraso_s):
        rel = (datetime.now() - timedelta(seconds=atraso_s)).strftime("%Y-%m-%d %H:%M:%S")
        S.receber_lote(caixa, {"versao": "t", "relogio": rel,
                               "lotes": [{"arquivo": "Teclas", "dia": "2026-10-27", "linhas": [[next(seq), "x"]]}]})
        return S.listar_caixas()[0]["relogio_pdv_offset_s"]

    assert enviar(1) == -1
    assert enviar(7) == -1   # lote que demorou a subir: ignorado
    assert enviar(1) == -1
