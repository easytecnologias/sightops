"""Maquete 3D: projeto por cliente (isolamento), salvar layout e excluir.

A leitura do PDF (maquete_planta) e substituida por uma funcao falsa: o teste
confere o fluxo do projeto, nao o reconhecimento de parede.
"""
import time

import pytest

from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug


@pytest.fixture()
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    from app.services import db_store, maquete_planta, maquete_store
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "t.db")
    import app.core.tenant_context as tc
    monkeypatch.setattr(tc, "DATA_DIR", tmp_path)

    def falsa(pdf, pasta):
        (pasta / "piso_0.jpg").write_bytes(b"jpg")
        return {"escala": "1/50", "modo": "hachura", "pisos": [{"id": "p0", "nome": "Térreo", "largura": 10, "profundidade": 30,
                                                               "paredes": [[0, 0, 10, 0.15]], "vaos": [], "rotulos": [], "textura": "piso_0.jpg"}]}
    monkeypatch.setattr(maquete_planta, "ler_planta", falsa)
    tok = set_current_tenant_slug("cliente-a")
    db_store.init_db()
    yield maquete_store
    reset_current_tenant_slug(tok)


def _espera_pronto(store, pid):
    for _ in range(50):
        p = store.obter(pid)["projeto"]
        if p["status"] != "processando":
            return p
        time.sleep(0.05)
    raise AssertionError("ficou processando")


def test_fluxo_e_isolamento(ambiente):
    store = ambiente
    r = store.criar("Prédio", "planta.pdf", b"%PDF-1.7 teste", "ana")
    p = _espera_pronto(store, r["id"])
    assert p["status"] == "pronto" and p["pisos"] == ["Térreo"]
    assert store.textura(r["id"], "piso_0.jpg").read_bytes() == b"jpg"

    store.salvar(r["id"], {"layout": {"cams": [{"id": 1}], "resumo": {"metros": 42.5, "caixas": 2}, "nomes": {"p0": "Garagem"}},
                           "nome": "Prédio A", "local": "Centro", "observacao": "obra nova"})
    p = store.obter(r["id"])["projeto"]
    assert p["nome"] == "Prédio A" and p["cameras"] == 1
    assert p["local"] == "Centro" and p["observacao"] == "obra nova" and p["metros"] == 42.5 and p["pisos"] == ["Garagem"]

    # outro cliente nao ve, nao salva, nao apaga
    tok = set_current_tenant_slug("cliente-b")
    try:
        assert store.listar()["projetos"] == []
        with pytest.raises(LookupError):
            store.obter(r["id"])
        with pytest.raises(LookupError):
            store.salvar(r["id"], {"nome": "x"})
        with pytest.raises(LookupError):
            store.textura(r["id"], "piso_0.jpg")
        with pytest.raises(LookupError):
            store.excluir(r["id"])
    finally:
        reset_current_tenant_slug(tok)

    store.excluir(r["id"])
    assert store.listar()["projetos"] == []


def test_recusa_arquivo_que_nao_e_pdf(ambiente):
    with pytest.raises(ValueError):
        ambiente.criar("x", "foto.jpg", b"\xff\xd8\xff", "ana")


def test_textura_nao_sai_da_pasta(ambiente):
    store = ambiente
    r = store.criar("Prédio", "planta.pdf", b"%PDF-1.7 teste", "ana")
    _espera_pronto(store, r["id"])
    for nome in ("../planta.pdf", "planta.pdf", "piso_0.jpg/../../x"):
        with pytest.raises(LookupError):
            store.textura(r["id"], nome)
    with pytest.raises(LookupError):
        store.obter("../../etc")
