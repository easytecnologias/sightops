"""Tela Saude do sistema: coletor de requisicoes, leitura da maquina e avaliacao."""
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import metricas_http as M
from app.core.observability import JsonFormatter, RequestContextMiddleware
from app.services import saude_service as S

AGORA = 1_800_000_000.0


@pytest.fixture(autouse=True)
def limpo():
    M.zerar()
    yield
    M.zerar()


def foto_boa(**extra):
    foto = {
        "maquina": {"nucleos": 4, "carga": [1.0, 1.0, 1.0],
                    "memoria": {"disponivel_pct": 50.0, "swap_pct": 0.0},
                    "swap_in_s": 0, "espera_disco_pct": 1.0,
                    "discos": [{"nome": "sda", "uso_pct": 10.0}]},
        "espacos": [{"nome": "Sistema", "usado_pct": 20.0}],
        "banco": {"ok": True, "conexoes": 5, "limite": 100},
        "servicos": [{"nome": "Zabbix", "ok": True}],
        "http": {"requisicoes": 100, "erros_5xx": 0, "p95_ms": 100},
    }
    foto.update(extra)
    return foto


def test_percentil_e_totais_da_janela():
    for ms in (10, 20, 30, 40, 2000):
        M.registrar("GET", "/api/x", 200, ms, agora=AGORA)
    r = M.resumo(60, agora=AGORA)
    assert r["requisicoes"] == 5
    assert r["lentas"] == 1
    assert r["p50_ms"] == 50
    assert r["p95_ms"] == 2500
    assert r["max_ms"] == 2000


def test_sem_requisicao_percentil_e_vazio_nao_zero():
    r = M.resumo(60, agora=AGORA)
    assert r["requisicoes"] == 0
    assert r["p95_ms"] is None and r["media_ms"] is None


def test_janela_ignora_o_que_e_mais_antigo():
    M.registrar("GET", "/velha", 200, 10, agora=AGORA - 7200)
    M.registrar("GET", "/nova", 200, 10, agora=AGORA)
    r = M.resumo(60, agora=AGORA)
    assert r["requisicoes"] == 1
    assert [x["rota"] for x in r["rotas"]] == ["/nova"]


def test_rota_mais_lenta_vem_primeiro():
    M.registrar("GET", "/rapida", 200, 10, agora=AGORA)
    M.registrar("POST", "/lenta", 200, 9000, agora=AGORA)
    assert M.resumo(60, agora=AGORA)["rotas"][0]["rota"] == "/lenta"


def test_erro_5xx_entra_na_lista_e_4xx_nao():
    M.registrar("GET", "/a", 404, 1, agora=AGORA)
    M.registrar("GET", "/b", 503, 1, agora=AGORA)
    r = M.resumo(60, agora=AGORA)
    assert r["erros_5xx"] == 1
    assert [e["rota"] for e in r["erros"]] == ["/b"]


def test_limite_de_rotas_nao_deixa_crescer_sem_fim():
    for i in range(M.MAX_ROTAS_POR_QUADRO + 50):
        M.registrar("GET", f"/r{i}", 200, 1, agora=AGORA)
    r = M.resumo(60, agora=AGORA, limite_rotas=1000)
    assert r["rotas_total"] == M.MAX_ROTAS_POR_QUADRO + 1
    outras = [x for x in r["rotas"] if x["rota"] == M.ROTA_OUTRAS]
    assert len(outras) == 1 and outras[0]["metodo"] == ""


def test_caminho_sem_rota_nunca_entra_no_contador():
    assert M.nome_da_rota({}) == M.SEM_ROTA


def test_404_nao_guarda_ip_nome_nem_token_do_caminho():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    cliente = TestClient(app)
    for caminho in ("/api/maintenance/web/10.200.0.15", "/api/cameras/Portaria%20Escola/x",
                    "/api/connectors/agent/tokenSecreto_ab12/nada"):
        assert cliente.get(caminho).status_code == 404
    assert [r["rota"] for r in M.resumo(60)["rotas"]] == [M.SEM_ROTA]


def test_log_leva_o_molde_e_nao_o_token_do_caminho(caplog):
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/api/foto/{token}")
    def foto(token: str):
        return {}

    with caplog.at_level(logging.INFO, logger="app.http"):
        TestClient(app).get("/api/foto/SEGREDO")
    registro = next(r for r in caplog.records if r.getMessage() == "request_completed")
    assert registro.path == "/api/foto/{token}"


@pytest.mark.parametrize("usuario,esperado", [
    ({"is_platform_admin": 1}, 200),
    ({"is_platform_admin": 1, "acting_as": True}, 403),
    ({"is_platform_admin": 0, "role": "owner"}, 403),
    ({}, 403),
])
def test_rota_so_para_o_dono_fora_de_cliente(monkeypatch, usuario, esperado):
    from app.api.endpoints import monitoring

    monkeypatch.setattr(S, "fotografia", lambda janela: {"http": {}})
    pedido = type("Pedido", (), {"state": type("Estado", (), {"current_user": usuario})()})()
    if esperado == 200:
        assert monitoring.api_saude_sistema(pedido)["ok"] is True
    else:
        with pytest.raises(monitoring.HTTPException) as erro:
            monitoring.api_saude_sistema(pedido)
        assert erro.value.status_code == esperado


def test_middleware_usa_o_molde_da_rota_e_nao_o_caminho():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/api/camera/{cam_id}")
    def camera(cam_id: str):
        return {"id": cam_id}

    assert TestClient(app).get("/api/camera/segredo-do-cliente").status_code == 200
    rotas = M.resumo(60)["rotas"]
    assert [r["rota"] for r in rotas] == ["/api/camera/{cam_id}"]


def test_log_json_leva_rota_e_tempo():
    registro = logging.LogRecord("app.http", logging.INFO, "", 0, "request_completed", None, None)
    registro.method, registro.path, registro.status_code, registro.elapsed_ms = "GET", "/x", 200, 12.5
    saida = json.loads(JsonFormatter().format(registro))
    assert saida["path"] == "/x" and saida["elapsed_ms"] == 12.5 and saida["status_code"] == 200


def test_leitura_de_disco_e_memoria():
    antes = S._contadores_disco("8 0 sda 100 0 0 50 200 0 0 300 0 0 0\n8 1 sda1 1 0 0 1 1 0 0 1 0 0 0")
    depois = S._contadores_disco("8 0 sda 110 0 0 70 220 0 0 340 0 250 0\n8 1 sda1 2 0 0 2 2 0 0 2 0 2 0")
    linhas = S._taxa_discos(antes, depois, 0.5)
    assert len(linhas) == 1, "particao nao conta como disco"
    d = linhas[0]
    assert d["nome"] == "sda" and d["uso_pct"] == 50.0
    assert d["leituras_s"] == 20.0 and d["espera_leitura_ms"] == 2.0
    assert d["escritas_s"] == 40.0 and d["espera_escrita_ms"] == 2.0

    m = S._memoria("MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 100 kB\nSwapFree: 40 kB\n")
    assert m["disponivel_pct"] == 25.0 and m["swap_pct"] == 60.0


def test_tudo_bom_fica_ok():
    assert S.avaliar(foto_boa()) == {"nivel": "ok", "motivos": []}


def test_servico_fora_e_critico():
    s = S.avaliar(foto_boa(servicos=[{"nome": "Zabbix", "ok": False}]))
    assert s["nivel"] == "critico" and "Zabbix sem resposta" in s["motivos"]


def test_leitura_que_falhou_nunca_vira_ok():
    assert S.avaliar(foto_boa(maquina={"ok": False, "erro": "x"}))["nivel"] == "critico"
    assert S.avaliar(foto_boa(banco={"ok": False, "erro": "x"}))["nivel"] == "critico"
    assert S.avaliar(foto_boa(espacos={"ok": False, "erro": "x"}))["nivel"] == "atencao"


def test_carga_acima_dos_nucleos_pede_atencao():
    foto = foto_boa()
    foto["maquina"]["carga"] = [5.0, 5.0, 5.0]
    assert S.avaliar(foto)["nivel"] == "atencao"
    foto["maquina"]["carga"] = [9.0, 5.0, 5.0]
    assert S.avaliar(foto)["nivel"] == "critico"


def test_poucas_requisicoes_nao_disparam_alarme_de_erro():
    assert S.avaliar(foto_boa(http={"requisicoes": 3, "erros_5xx": 3, "p95_ms": 100}))["nivel"] == "ok"
