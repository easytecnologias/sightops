"""Relatorios do Painel de Acesso: catalogo por modo, presenca honesta com dia
fora da conta, diario, uso, avisos, cadastro e o PDF de cada um. SQLite
temporario e pessoas ficticias."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.core import tenant_context
from app.services import access_control_horarios as H
from app.services import access_control_painel as P
from app.services import access_control_relatorios as R
from app.services import access_control_store as S
from app.services import db_store
from app.services.access_control_relatorios_pdf import gerar_pdf

# 2026-10-23 e sexta. Semana: seg 19 a sex 23.
AGORA = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(P, "_agora", lambda: AGORA)
    monkeypatch.setattr(P, "_mensagens", lambda desde: [])
    token = tenant_context.set_current_tenant_slug("escola-teste")
    S.ensure_access_control_schema()
    yield
    tenant_context.reset_current_tenant_slug(token)


def _escola():
    leitor = S.save_device({"name": "ENTRADA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.201", "password": "x"})
    alunos = []
    for i in range(8):
        alunos.append(S.save_person({"full_name": f"ALUNO {i}", "person_type": "student", "class_name": "1º Ano" if i < 4 else "2º Ano",
                                     "enrollment_code": str(900 + i), "document_id": "", "site": "ESCOLA",
                                     "controller_user_id": str(900 + i), "guardian_phone": "82999990000"}))
        S.upsert_provision_status(alunos[-1]["id"], leitor["id"], "ok")
    return leitor, alunos


def _passa(leitor, pessoa, quando, tipo="entrada"):
    with db_store._conn() as c:
        c.execute("INSERT INTO access_events(id, tenant_slug, site, device_id, device_name, person_id, event_type, occurred_at) "
                  "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                  (f"e{quando}{tipo}{pessoa['id']}", "escola-teste", "ESCOLA", leitor["id"], leitor["name"], pessoa["id"], tipo, quando))


def test_catalogo_muda_por_modo(banco):
    _escola()
    c = R.catalogo("ESCOLA")
    assert c["modo"] == "escola" and [r["id"] for r in c["relatorios"]][0] == "frequencia"
    assert c["grupos"] == ["1º Ano", "2º Ano"]
    P.definir_tipo_local("ESCOLA", "condominio", "teste")
    c = R.catalogo("ESCOLA")
    assert c["modo"] == "condominio" and "cadastro" in [r["id"] for r in c["relatorios"]]
    with pytest.raises(HTTPException):
        R.gerar("frequencia", site="ESCOLA")                  # nao existe no condominio


def test_frequencia_deixa_fora_dia_com_leitor_fora_e_feriado(banco):
    leitor, alunos = _escola()
    for a in alunos:                                         # seg 19: todos
        _passa(leitor, a, "2026-10-19 07:10:00")
    for a in alunos[:6]:                                     # ter 20: 6 de 8
        _passa(leitor, a, "2026-10-20 07:10:00")
    _passa(leitor, alunos[0], "2026-10-21 07:10:00")         # qua 21: so 1 (leitor fora?)
    for a in alunos:                                         # sex 23 (hoje): nao conta
        _passa(leitor, a, "2026-10-23 07:10:00")
    H.salvar_feriados("ESCOLA", [{"data": "2026-10-22", "nome": "Padroeira"}])   # qui 22
    r = R.gerar("frequencia", site="ESCOLA", de="2026-10-19", ate="2026-10-23", agora=AGORA)
    assert r["dias_contados"] == ["2026-10-19", "2026-10-20"]
    motivos = {d["dia"]: d["motivo"] for d in r["dias_fora"]}
    assert "só 1 de 8" in motivos["2026-10-21"] and "Padroeira" in motivos["2026-10-22"]
    assert r["ate"] == "2026-10-22"                           # hoje fica de fora
    assert r["resumo"]["faltas"] == 2 and r["resumo"]["pct"] == 88
    seis = next(x for x in r["pessoas"] if x["nome"] == "ALUNO 6")
    assert seis["dias_falta"] == ["2026-10-20"]
    sem_id = S.save_person({"full_name": "SEM ID", "person_type": "student", "class_name": "1º Ano",
                            "enrollment_code": "abc", "document_id": "52998224725", "site": "ESCOLA"})
    S.upsert_provision_status(sem_id["id"], leitor["id"], "failed", "Informe o ID na controladora")
    r = R.gerar("frequencia", site="ESCOLA", de="2026-10-19", ate="2026-10-23", agora=AGORA)
    assert r["resumo"]["pessoas"] == 8 and [x["nome"] for x in r["fora_leitor"]] == ["SEM ID"]   # sem falta inventada
    so_2 = R.gerar("frequencia", site="ESCOLA", de="2026-10-19", ate="2026-10-23", grupo="2º Ano", agora=AGORA)
    assert so_2["resumo"]["pessoas"] == 4 and [g["grupo"] for g in so_2["grupos"]] == ["2º Ano"]


def test_diario_uso_e_pdf_de_cada_relatorio(banco):
    leitor, alunos = _escola()
    sai = S.save_device({"name": "SAIDA", "site": "ESCOLA", "vendor": "intelbras", "host": "192.168.1.202",
                         "password": "x", "access_direction": "saida"})
    for a in alunos[:5]:
        _passa(leitor, a, "2026-10-22 07:05:00")
        _passa(sai, a, "2026-10-22 12:30:00", "saida")
    d = R.gerar("diario", site="ESCOLA", dia="2026-10-22", agora=AGORA)
    assert d["resumo"]["pessoas"] == 5 and d["pessoas"][0]["minutos"] == 325 and len(d["nao_vieram"]) == 3
    u = R.gerar("uso", site="ESCOLA", de="2026-10-20", ate="2026-10-22", agora=AGORA)
    assert u["resumo"]["passagens"] == 10 and u["resumo"]["pico"] == 5 and u["resumo"]["pico_hora"] == "07:05"
    for a in alunos[5:]:                                       # entram e ninguem registra saida
        for dia in ("20", "21"):
            _passa(leitor, a, f"2026-10-{dia} 07:00:00")
    u = R.gerar("uso", site="ESCOLA", de="2026-10-20", ate="2026-10-22", agora=AGORA)
    assert u["saidas_confiaveis"] is False and u["resumo"]["pico"] is None
    for rid in ("frequencia", "diario", "uso", "avisos"):
        r = R.gerar(rid, site="ESCOLA", de="2026-10-01", ate="2026-10-22", dia="2026-10-22", agora=AGORA)
        pdf = gerar_pdf(r, usuario="teste")
        assert pdf.startswith(b"%PDF") and len(pdf) > 1500, rid


def test_cadastro_do_condominio_e_pdf(banco):
    leitor, alunos = _escola()
    P.definir_tipo_local("ESCOLA", "condominio", "teste")
    S.save_person({"full_name": "MORADOR SEM TURMA C06", "person_type": "resident", "site": "ESCOLA",
                   "controller_user_id": "5001", "document_id": ""})
    _passa(leitor, alunos[0], "2026-10-22 07:05:00")
    r = R.gerar("cadastro", site="ESCOLA", agora=AGORA)
    assert "C06" in [g["grupo"] for g in r["grupos"]]            # unidade tirada do nome
    assert r["resumo"]["pessoas"] == 9 and r["resumo"]["sem_foto"] == 9
    assert gerar_pdf(r).startswith(b"%PDF")


def test_usuario_restrito_nao_ve_outro_local(banco, monkeypatch):
    _escola()
    from app.core import permissions
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: ["OUTRA ESCOLA"])
    with pytest.raises(HTTPException) as e:
        R.gerar("frequencia", site="ESCOLA", agora=AGORA)
    assert e.value.status_code == 403


def test_aviso_de_numero_compartilhado_com_outro_local_fica_de_fora(banco, monkeypatch):
    """Irmaos em duas escolas com o mesmo numero: a mensagem nao diz de qual local foi."""
    _escola()
    S.save_person({"full_name": "IRMAO NA OUTRA", "person_type": "student", "class_name": "1º Ano", "enrollment_code": "77",
                   "document_id": "52998224725", "site": "OUTRA ESCOLA", "guardian_phone": "82999990000"})
    msg = {"contact_number": "5582999990000", "status": "read", "error": "", "created_at": "2026-10-22 10:00:00", "updated_at": "2026-10-22 10:00:00"}
    monkeypatch.setattr(P, "_mensagens", lambda desde: [msg])
    r = R.gerar("avisos", site="ESCOLA", de="2026-10-20", ate="2026-10-22", agora=AGORA)
    assert r["resumo"]["enviados"] == 0 and r["resumo"]["numeros_compartilhados"] == 1


def test_perfil_do_catalogo_so_tem_os_locais_liberados(banco, monkeypatch):
    _escola()
    S.save_device({"name": "ENTRADA B", "site": "OUTRA ESCOLA", "vendor": "intelbras", "host": "192.168.9.1", "password": "x"})
    from app.core import permissions
    monkeypatch.setattr(permissions, "sites_da_sessao", lambda: ["ESCOLA"])
    c = R.catalogo("")
    assert c["site"] == "ESCOLA" and [x["site"] for x in c["perfil"]["locais"]] == ["ESCOLA"]
