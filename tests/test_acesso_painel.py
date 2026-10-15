"""Painel novo do controle de acesso: saude dos avisos, incidentes e recibo."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import access_control_painel as P

AGORA = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)


def _msg(min_atras, status, erro="", numero="5582999990000"):
    t = (AGORA - timedelta(minutes=min_atras)).strftime("%Y-%m-%d %H:%M:%S.000000+00")
    return {"contact_number": numero, "status": status, "error": erro, "created_at": t, "updated_at": t}


def test_alerta_quando_meta_recusa_mesmo_com_canal_conectado(monkeypatch):
    """O caso de 15/09 a 07/10: token valido, envios recusados por pagamento."""
    msgs = [_msg(i, "failed", "Business eligibility payment issue") for i in range(12)] + [_msg(1, "read")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: [m for m in msgs if m["created_at"] >= P._utc_txt(desde)])
    s = P.saude_avisos(agora=AGORA)
    assert s["alerta"] is True
    assert s["falhas"] == 12 and s["enviados"] == 13
    assert s["erro_principal"] == "Business eligibility payment issue"


def test_pouco_volume_nao_vira_alarme(monkeypatch):
    msgs = [_msg(3, "failed", "Message undeliverable"), _msg(2, "read")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: msgs)
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def test_envio_normal_nao_alerta(monkeypatch):
    msgs = [_msg(i, "read") for i in range(30)] + [_msg(5, "failed", "Message undeliverable")]
    monkeypatch.setattr(P, "_mensagens", lambda desde: msgs)
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def _consulta(msgs):
    return lambda desde: [m for m in msgs if m["created_at"] >= P._utc_txt(desde)]


def test_noite_sem_envio_nao_recupera_canal_bloqueado(monkeypatch):
    """Bloqueio de pagamento: a tarde falhou tudo; de noite ninguem passa.
    O canal nao pode voltar a online so porque a janela de 30 min ficou vazia."""
    msgs = [_msg(300 + i, "failed", "Business eligibility payment issue") for i in range(25)]
    monkeypatch.setattr(P, "_mensagens", _consulta(msgs))
    s = P.saude_avisos(agora=AGORA)
    assert s["alerta"] is True and s["enviados"] == 20


def test_noite_tranquila_com_avisos_entregues_nao_alerta(monkeypatch):
    msgs = [_msg(300 + i, "read") for i in range(25)] + [_msg(310, "failed", "Message undeliverable")]
    monkeypatch.setattr(P, "_mensagens", _consulta(msgs))
    assert P.saude_avisos(agora=AGORA)["alerta"] is False


def test_incidentes_juntam_dias_vizinhos_e_trazem_o_motivo():
    def dia(d, n_falha, n_ok, erro="Business eligibility payment issue"):
        base = f"2026-09-{d:02d} 12:00:00"
        return ([{"status": "failed", "error": erro, "created_at": base}] * n_falha
                + [{"status": "read", "error": "", "created_at": base}] * n_ok)
    msgs = dia(15, 120, 2) + dia(16, 110, 0) + dia(18, 100, 5) + dia(22, 0, 150) + dia(29, 90, 3)
    inc = P._incidentes(msgs)
    assert [(i["inicio"], i["fim"]) for i in inc] == [("2026-09-15", "2026-09-18"), ("2026-09-29", "2026-09-29")]
    assert inc[0]["falhas"] == 330 and inc[0]["erro"] == "Business eligibility payment issue"


@pytest.mark.parametrize("bruto, esperado", [
    ("(82) 9 9812-0000", "5582998120000"),
    ("5582998120000", "5582998120000"),
    ("", ""),
])
def test_numero_igual_ao_do_log(bruto, esperado):
    assert P._numero(bruto) == esperado


def test_classe_dos_status():
    assert [P._classe(s) for s in ("read", "delivered", "sent", "whatsapp_sent", "failed", "whatsapp_failed")] == \
        ["lido", "entregue", "enviado", "enviado", "falha", "falha"]


def test_hora_local_do_leitor_casa_com_utc_do_whatsapp():
    """Leitor grava 18:43 local; o aviso sai 21:43 UTC -- e o mesmo instante."""
    # No segundo: o Python 3.11 da imagem le os .123 ms do Postgres e o 3.10 nao;
    # o recibo do aviso compara por faixa de minutos, milissegundo nao importa.
    assert P._ler_local("2026-10-14 18:43:15") == P._ler_utc("2026-10-14 21:43:15.123+00").replace(microsecond=0)


def test_relatorios_mapa_chegada_e_nao_veio(monkeypatch):
    """AGORA = 14/10 18:00 local (quarta). Evento de 1999 nao entra no mapa."""
    eventos = [
        {"person_id": "a", "person_name_raw": "", "event_type": "entrada", "device_name": "PORTARIA", "occurred_at": "2026-10-14 07:10:00"},
        {"person_id": "a", "person_name_raw": "", "event_type": "saida", "device_name": "PORTARIA", "occurred_at": "2026-10-14 12:30:00"},
        {"person_id": "b", "person_name_raw": "", "event_type": "entrada", "device_name": "LATERAL", "occurred_at": "2026-10-14 07:40:00"},
        {"person_id": "", "person_name_raw": "VISITANTE", "event_type": "entrada", "device_name": "LATERAL", "occurred_at": "2026-10-13 09:00:00"},
    ]
    vistos = {}

    def rows(sql, params):
        vistos["params"] = params
        return [e for e in eventos if params[1] <= e["occurred_at"] <= params[2]]

    pessoas = [
        {"id": "a", "full_name": "Ana", "class_name": "7B", "person_type": "student", "active": True, "site": "ESCOLA"},
        {"id": "b", "full_name": "Bruno", "class_name": "7B", "person_type": "student", "active": True, "site": "ESCOLA"},
        {"id": "c", "full_name": "Carla", "class_name": "9A", "person_type": "student", "active": True, "site": "ESCOLA"},
        {"id": "d", "full_name": "Dona", "class_name": "", "person_type": "employee", "active": True, "site": "ESCOLA"},
    ]
    monkeypatch.setattr(P, "_leitores", lambda site="": [])
    monkeypatch.setattr(P, "_rows", rows)
    monkeypatch.setattr(P, "_tenant", lambda: "t")
    monkeypatch.setattr(P, "_pessoas", lambda: pessoas)
    r = P.relatorios(agora=AGORA)
    assert vistos["params"][1] == "2026-09-17 00:00:00"   # 28 dias contando hoje, hora local
    assert r["mapa"][2][7] == 2 and r["mapa"][1][9] == 1  # quarta 7h, terca 9h
    assert sum(map(sum, r["mapa"])) == 4
    ana = next(x for x in r["hoje"] if x["pessoa_id"] == "a")
    assert ana["chegou"].endswith("07:10:00") and ana["saiu"].endswith("12:30:00") and ana["ultimo_tipo"] == "saida"
    assert [x["nome"] for x in r["nao_vieram"]] == ["Carla"]       # funcionario nao conta como falta
    assert r["serie"][-1] == {"dia": "2026-10-14", "passagens": 3, "pessoas": 2}
    assert r["perfil"]["tipo"] == "escola"


def test_relatorios_sem_movimento_hoje_nao_lista_falta(monkeypatch):
    monkeypatch.setattr(P, "_rows", lambda sql, params: [])
    monkeypatch.setattr(P, "_tenant", lambda: "t")
    monkeypatch.setattr(P, "_pessoas", lambda: [{"id": "c", "full_name": "Carla", "person_type": "student", "active": True}])
    monkeypatch.setattr(P, "_leitores", lambda site="": [])
    r = P.relatorios(agora=AGORA)
    assert r["nao_vieram"] == [] and r["hoje_total"] == 0


# ---------------------------------------------------------------- escola x condominio

def _p(i, site, tipo="student", turma="", fone=""):
    return {"id": str(i), "full_name": f"P{i}", "person_type": tipo, "class_name": turma,
            "guardian_phone": fone, "site": site, "active": True}


def test_condominio_com_moradores_cadastrados_como_aluno():
    """O caso do RESERVA: 192 'alunos' sem turma nem telefone sao moradores."""
    pessoas = [_p(i, "RESERVA") for i in range(192)]
    r = P.perfil_locais(pessoas, ["RESERVA", "JARDINS II"], "RESERVA")
    assert r["tipo"] == "condominio"
    # Local sem ninguem no cadastro (moradores so no leitor) tambem e condominio.
    assert {x["site"]: x["tipo"] for x in r["locais"]} == {"JARDINS II": "condominio", "RESERVA": "condominio"}


def test_escola_e_misto():
    escola = [_p(i, "ESCOLA PRESIDENTE DUTRA", turma="4º Ano", fone="82999990000") for i in range(88)]
    escola += [_p(100 + i, "ESCOLA PRESIDENTE DUTRA") for i in range(3)]
    condo = [_p(200 + i, "RESERVA") for i in range(50)]
    assert P.perfil_locais(escola, [], "ESCOLA PRESIDENTE DUTRA")["tipo"] == "escola"
    assert P.perfil_locais(escola + condo, [], "")["tipo"] == "misto"
    assert P.perfil_locais(escola, [], "")["tipo"] == "escola"


def test_morador_nao_aparece_como_aluno_sem_responsavel(monkeypatch):
    monkeypatch.setattr(P, "_mensagens", lambda desde: [])
    pessoas = [_p(1, "RESERVA"), _p(2, "ESCOLA", turma="7B"), _p(3, "ESCOLA", turma="7B", fone="82999990000")]
    av = P._avisos(AGORA, pessoas, {"ESCOLA"})
    assert [x["pessoa"] for x in av["sem_numero"]] == ["P2"]


def test_local_sem_cadastro_herda_pelo_nome_ou_pelo_cliente():
    """RADS: so a Presidente Dutra tem alunos; ESCOLA MEDEA (nome) e CANAPI
    (resto do cliente) tambem sao escola. No default, JARDINS II segue o RESERVA."""
    escola = [_p(i, "ESCOLA PRESIDENTE DUTRA", turma="4º Ano") for i in range(20)]
    r = P.perfil_locais(escola, ["ESCOLA MEDEA", "CANAPI", "ESCOLA PRESIDENTE DUTRA"])
    tipos = {x["site"]: (x["tipo"], x["origem"]) for x in r["locais"]}
    assert tipos == {"CANAPI": ("escola", "cliente"), "ESCOLA MEDEA": ("escola", "nome"),
                     "ESCOLA PRESIDENTE DUTRA": ("escola", "cadastro")}
    assert r["tipo"] == "escola"
    condo = [_p(i, "RESERVA") for i in range(30)]
    r = P.perfil_locais(condo, ["JARDINS II", "RESERVA", "ESCOLINHA DO CLUBE"])
    assert {x["site"]: x["tipo"] for x in r["locais"]}["JARDINS II"] == "condominio"
    assert P.perfil_locais([], [], "ESCOLA NOVA")["tipo"] == "escola"


def test_ip_virtual_sem_conector_e_com_mapa(monkeypatch):
    from app.services import connector_routing_vnat as V
    monkeypatch.setattr(P, "_conectores", lambda: [{"id": "c1"}, {"id": "c2"}, {"id": "outro-cliente"}])
    monkeypatch.setattr(V, "virtual_ip_for", lambda cid, ip: "10.209.128.201" if cid == "c1" else ip)
    assert P.ip_virtual("c1", "192.168.1.201") == {"host": "192.168.1.201", "connector_id": "c1",
                                                   "virtual": "10.209.128.201", "traduzido": True, "bloqueado": False}
    assert P.ip_virtual("c2", "192.168.1.201")["traduzido"] is False
    monkeypatch.setattr(V, "virtual_ip_for", lambda cid, ip: V.IP_BLOQUEADO)
    r = P.ip_virtual("outro-cliente", "192.168.1.201")
    assert r["bloqueado"] is True and r["virtual"] == ""


def test_ip_virtual_de_conector_alheio_e_sempre_bloqueado(monkeypatch):
    from app.services import connector_routing_vnat as V
    monkeypatch.setattr(P, "_conectores", lambda: [{"id": "meu"}])
    monkeypatch.setattr(V, "virtual_ip_for", lambda cid, ip: ip)   # sem faixa: antes devolvia o host
    r = P.ip_virtual("de-outro-cliente", "192.168.1.201")
    assert r["bloqueado"] is True and r["virtual"] == ""


def test_tipo_escolhido_manda_e_o_palpite_vira_sugestao():
    escola = [_p(i, "ESCOLA PRESIDENTE DUTRA", turma="4º Ano") for i in range(20)]
    escolhidos = {"ARENA": {"site": "ARENA", "tipo": "evento"},
                  "ESCOLA PRESIDENTE DUTRA": {"site": "ESCOLA PRESIDENTE DUTRA", "tipo": "empresa"}}
    r = P.perfil_locais(escola, ["CANAPI"], "", escolhidos)
    por = {x["site"]: x for x in r["locais"]}
    assert (por["ARENA"]["tipo"], por["ARENA"]["origem"]) == ("evento", "escolhido")   # local so com o tipo escolhido
    assert (por["ESCOLA PRESIDENTE DUTRA"]["tipo"], por["ESCOLA PRESIDENTE DUTRA"]["sugestao"]) == ("empresa", "escola")
    assert por["CANAPI"]["origem"] == "cliente"
    assert r["tipo"] == "misto"
    assert P.perfil_locais(escola, [], "ARENA", escolhidos)["tipo"] == "evento"


def test_definir_tipo_local_grava_por_cliente(tmp_path, monkeypatch):
    from app.core import tenant_context
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(P, "_tenant", lambda: "cliente-a")
    P.definir_tipo_local("Arena Norte", "evento", "rads")
    assert P.tipos_escolhidos()["ARENA NORTE"]["tipo"] == "evento"
    monkeypatch.setattr(P, "_tenant", lambda: "cliente-b")
    assert P.tipos_escolhidos() == {}                    # outro cliente nao ve
    monkeypatch.setattr(P, "_tenant", lambda: "cliente-a")
    with pytest.raises(ValueError):
        P.definir_tipo_local("Arena Norte", "shopping")
    P.definir_tipo_local("Arena Norte", "")               # volta ao palpite
    assert P.tipos_escolhidos() == {}


def test_relogio_errado_so_acusa_o_que_chegou_na_ultima_semana(monkeypatch):
    linhas = [{"device_id": "d1", "synced_at": "2026-09-18 10:00:00+00"},      # queda antiga
              {"device_id": "d2", "synced_at": "2026-10-13 08:00:00.123+00"}]   # recente
    monkeypatch.setattr(P, "_rows", lambda sql, params: linhas if "occurred_at <" in sql else [])
    monkeypatch.setattr(P, "_tenant", lambda: "t")
    r = P._relogio_errado(agora=AGORA)
    assert list(r) == ["d2"] and r["d2"]["qtd"] == 1


def test_relogio_errado_ignora_historico_antigo_baixado_ao_recadastrar(monkeypatch):
    """ACADEMIA RESERVA: registros 1-18 de 2000 baixados hoje junto com o 24373
    de hoje. O relogio ja foi acertado; so acende se o erro e o mais novo."""
    ruins = [{"device_id": "acad", "synced_at": "2026-10-15 16:27:52+00", "raw_event_id": "17"},
             {"device_id": "agora", "synced_at": "2026-10-15 16:27:52+00", "raw_event_id": "900"}]
    certos = {"acad": [{"raw_event_id": "24373"}, {"raw_event_id": "24372"}], "agora": [{"raw_event_id": "899"}]}
    monkeypatch.setattr(P, "_rows", lambda sql, params: ruins if "occurred_at <" in sql else certos[params[1]])
    monkeypatch.setattr(P, "_tenant", lambda: "t")
    r = P._relogio_errado(agora=AGORA)
    assert list(r) == ["agora"]
