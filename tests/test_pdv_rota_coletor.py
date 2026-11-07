"""Rota HTTP do coletor: grava em thread, no cliente do token, e nao bloqueia o laco."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import pdv as rota
from app.core.tenant_context import get_current_tenant_slug, reset_current_tenant_slug, set_current_tenant_slug
from app.services import pdv_store as S
from tests.test_pdv_store import DIA, ESP, TEC, banco  # noqa: F401


def test_rota_grava_no_cliente_do_token_em_thread(banco):
    cx = S.salvar_caixa({"nome": "PDV 01", "numero": 1, "gravador_host": "192.168.24.227", "gravador_canal": 1})
    import threading
    visto = {}
    orig = S.receber_lote

    def espiao(caixa, payload, agora=None):
        visto["thread"] = threading.current_thread() is threading.main_thread()
        visto["tenant"] = get_current_tenant_slug()
        return orig(caixa, payload, agora=1000.0)

    S.receber_lote = espiao
    tok = set_current_tenant_slug("outro-cliente")  # o laco nao pode vazar cliente para a gravacao
    try:
        app = FastAPI(); app.include_router(rota.router)
        r = TestClient(app).post("/api/pdv/coletor/lote", headers={"x-pdv-caixa": cx["id"], "x-pdv-token": cx["token"]},
                                 json={"versao": "t", "lotes": [{"arquivo": "Espiao", "dia": DIA, "linhas": ESP},
                                                                 {"arquivo": "Teclas", "dia": DIA, "linhas": TEC}]})
        ruim = TestClient(app).post("/api/pdv/coletor/lote", headers={"x-pdv-caixa": cx["id"], "x-pdv-token": "x"}, json={})
        invalido = TestClient(app).post("/api/pdv/coletor/lote", headers={"x-pdv-caixa": cx["id"], "x-pdv-token": cx["token"]},
                                        json={"lotes": [{"arquivo": "Nada", "dia": DIA, "linhas": []}]})
    finally:
        reset_current_tenant_slug(tok)
        S.receber_lote = orig
    assert r.status_code == 200, r.text
    assert r.json()["ok"] and r.json()["aceito"]["Espiao/%s" % DIA] == len(ESP)
    assert visto == {"thread": False, "tenant": "mercado-a"}
    assert ruim.status_code == 401 and invalido.status_code == 400
    assert S.buscar_cupons(DIA)  # gravou no mercado-a
