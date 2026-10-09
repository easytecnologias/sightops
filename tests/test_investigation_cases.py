"""Casos da Investigacao: isolamento por tenant e regras de item."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import investigation_cases as ic


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    token = tenant_context.set_current_tenant_slug("cliente-a")
    yield tmp_path
    tenant_context.reset_current_tenant_slug(token)


def _item(**mudar):
    base = {"host": "10.10.9.120", "http_port": 80, "canal": 28, "camera": "28 · Oficina 02",
            "momento": "2026-10-09 02:13:48", "inicio": "2026-10-09 02:12:00", "fim": "2026-10-09 02:16:30"}
    base.update(mudar)
    return base


def test_caso_nasce_numerado_e_guarda_itens_em_ordem():
    c1 = ic.criar("Furto oficina", site="Perucaba", autor="Elishafan")
    c2 = ic.criar("Portao aberto")
    assert (c1["numero"], c2["numero"]) == (1, 2)
    ic.adicionar_item(c1["id"], _item(momento="2026-10-09 02:13:48"))
    caso = ic.adicionar_item(c1["id"], _item(canal=30, momento="2026-10-09 02:08:41"))
    assert [i["momento"][11:] for i in caso["itens"]] == ["02:08:41", "02:13:48"]
    assert {c["id"] for c in ic.listar()} == {c1["id"], c2["id"]}


def test_cliente_nao_ve_caso_do_outro():
    ic.criar("Caso do A")
    tenant_context.set_current_tenant_slug("cliente-b")
    assert ic.listar() == []
    ic.criar("Caso do B")
    assert [c["titulo"] for c in ic.listar()] == ["Caso do B"]
    tenant_context.set_current_tenant_slug("cliente-a")
    assert [c["titulo"] for c in ic.listar()] == ["Caso do A"]


def test_item_sem_horario_ou_canal_e_recusado():
    c = ic.criar("x")
    with pytest.raises(ValueError):
        ic.adicionar_item(c["id"], _item(momento=""))
    with pytest.raises(ValueError):
        ic.adicionar_item(c["id"], _item(canal=0))
    with pytest.raises(ValueError):
        ic.criar("   ")
    with pytest.raises(KeyError):
        ic.adicionar_item("nao-existe", _item())


def test_item_nao_guarda_campo_estranho_nem_senha():
    c = ic.criar("x")
    caso = ic.adicionar_item(c["id"], _item(password="segredo", user="admin"))
    assert "password" not in caso["itens"][0] and "user" not in caso["itens"][0]


def test_notas_e_remocao():
    c = ic.criar("x")
    caso = ic.adicionar_item(c["id"], _item())
    item_id = caso["itens"][0]["id"]
    caso = ic.atualizar(c["id"], notas="Sai com caixa azul", item_id=item_id, nota_item="entra pelo portao")
    assert caso["notas"] == "Sai com caixa azul" and caso["itens"][0]["nota"] == "entra pelo portao"
    assert ic.remover_item(c["id"], item_id)["itens"] == []
