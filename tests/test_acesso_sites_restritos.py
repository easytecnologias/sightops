"""Usuario restrito a uma escola nao ve nem grava grupos/pessoas das outras
(cadastro de pessoa oferecia os grupos de todas as escolas, 29/10/2026)."""
import pytest
from fastapi import HTTPException

from app.api.endpoints import access_control as ac

GRUPOS = [
    {"id": "g1", "name": "ESCOLA M.CONCEICAO", "site": "ESCOLA M. CONCEICAO"},
    {"id": "g2", "name": "ESCOLA PRESIDENTE DUTRA", "site": "ESCOLA PRESIDENTE DUTRA"},
]


@pytest.fixture
def restrito(monkeypatch):
    monkeypatch.setattr(ac.permissions, "sites_da_sessao", lambda: ["ESCOLA M. CONCEICAO"])
    monkeypatch.setattr(ac, "list_groups", lambda: [dict(g) for g in GRUPOS])


def test_pessoas_so_do_site(restrito, monkeypatch):
    import app.services.access_control_pessoas as svc
    visto = {}

    def falso(site=""):
        visto["site"] = site
        return {"ok": True,
                "pessoas": [{"id": "1", "site": "ESCOLA M. CONCEICAO"}, {"id": "2", "site": "ESCOLA PRESIDENTE DUTRA"}],
                "grupos": [{"id": g["id"], "site": g["site"]} for g in GRUPOS],
                "sites": ["ESCOLA M. CONCEICAO", "ESCOLA PRESIDENTE DUTRA"],
                "perfil": {"locais": [{"site": "ESCOLA M. CONCEICAO"}, {"site": "ESCOLA PRESIDENTE DUTRA"}]}}

    monkeypatch.setattr(svc, "pessoas", falso)
    r = ac.api_access_control_painel_pessoas(site="")
    assert visto["site"] == "ESCOLA M. CONCEICAO"
    assert [p["id"] for p in r["pessoas"]] == ["1"]
    assert [g["id"] for g in r["grupos"]] == ["g1"]
    assert r["sites"] == ["ESCOLA M. CONCEICAO"]
    assert [x["site"] for x in r["perfil"]["locais"]] == ["ESCOLA M. CONCEICAO"]
    with pytest.raises(HTTPException) as e:
        ac.api_access_control_painel_pessoas(site="ESCOLA PRESIDENTE DUTRA")
    assert e.value.status_code == 403


def test_grupos_da_pessoa_barra_outro_site_e_preserva(restrito, monkeypatch):
    import app.services.access_control_pessoas as svc
    import app.services.access_control_store as store
    monkeypatch.setattr(store, "list_people", lambda *a, **k: [{"id": "p1", "site": "ESCOLA M. CONCEICAO"}])
    monkeypatch.setattr(ac, "_membros_da_pessoa", lambda pid: [{"group_id": "g2"}])
    gravado = {}
    monkeypatch.setattr(svc, "definir_grupos", lambda pid, grupos: gravado.setdefault("g", grupos))
    with pytest.raises(HTTPException) as e:
        ac.api_access_control_painel_pessoa_grupos("p1", ac.PessoaGruposRequest(grupos=["g2"]))
    assert e.value.status_code == 403
    ac.api_access_control_painel_pessoa_grupos("p1", ac.PessoaGruposRequest(grupos=["g1"]))
    assert gravado["g"] == ["g1", "g2"]   # g2 (outra escola) nao some


def test_sem_restricao_nada_muda(monkeypatch):
    monkeypatch.setattr(ac.permissions, "sites_da_sessao", lambda: None)
    monkeypatch.setattr(ac, "list_groups", lambda: [dict(g) for g in GRUPOS])
    monkeypatch.setattr(ac, "list_group_members", lambda gid: [])
    assert len(ac.api_access_control_groups()["groups"]) == 2
