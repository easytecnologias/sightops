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


def test_precos_por_cliente(ambiente):
    store = ambiente
    store.salvar_precos({"precos": {"cam:d2_28": {"preco": "289.9", "descricao": "Dome", "un": "un"}, "x": "lixo"}})
    assert store.precos()["precos"]["cam:d2_28"]["preco"] == 289.9
    tok = set_current_tenant_slug("cliente-b")
    try:
        assert store.precos()["precos"] == {}
    finally:
        reset_current_tenant_slug(tok)


def test_pdf_relatorio_e_orcamento():
    from app.services.maquete_pdf import calcular_orcamento, gerar_pdf
    orc = {"itens": [{"grupo": "Câmeras", "descricao": "Dome 2 MP", "qtd": 3, "un": "un", "preco": 100},
                     {"grupo": "Cabeamento", "descricao": "Cabo Cat6", "qtd": 2, "un": "cx", "preco": "abc"},
                     {"grupo": "Câmeras", "descricao": "zero", "qtd": 0, "preco": 50}],
           "desconto_pct": 10, "condicoes": "Pagamento 50% na aprovação"}
    o = calcular_orcamento(orc)
    assert o["subtotal"] == 300 and o["desconto"] == 30 and o["total"] == 270 and o["sem_preco"] == 1 and len(o["itens"]) == 2
    projeto = {"nome": "Prédio <A>", "local": "Centro", "arquivo": "p.pdf", "escala": "1/50", "pisos": ["Térreo"]}
    dados = {"resumo": {"cameras": 1, "metros": 30.5, "categoria": "Cat6", "rack": "Parede 12U"},
             "cameras": [{"cabo": "C-01", "nome": "CAM-01", "piso": "Térreo", "modelo": "Dome", "metros": 30.5}],
             "rack": [{"u": "U12", "nome": "Patch panel"}], "imagens": [{"titulo": "x", "jpg": "nao-e-imagem"}],
             "incluirOrcamento": True, "orcamento": orc}
    for tipo in ("relatorio", "orcamento"):
        pdf = gerar_pdf(projeto, dict(dados, tipo=tipo))
        assert pdf[:4] == b"%PDF" and len(pdf) > 1500
