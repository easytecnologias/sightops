"""Exercita pela HTTP o ciclo do provider Evolution: salvar config, ler
conexao com refresh_qr, desconectar. Confere tambem que o campo instance
nao volta mais fixo em "sightops" quando o front nao manda nada (colidiria
entre clientes no container Evolution compartilhado).

Roda direto: python scripts/sightops_whatsapp_evolution_routes_test.py
"""
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="rotas-whatsapp-evolution-"))
os.environ["DATA_DIR"] = str(tmp / "data")
os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["AUTH_DATABASE_BACKEND"] = "sqlite"
os.environ["SIGHTOPS_SECRET_KEY"] = "chave-de-teste-evolution"
os.environ["AUTH_ENABLED"] = "0"
os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
os.environ["SIGHTOPS_EVOLUTION_URL"] = "http://evolution.teste:8090"
os.environ["SIGHTOPS_EVOLUTION_API_KEY"] = "chave-teste"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
import app.main as m

falhas = []


def check(cond, msg):
    if not cond:
        falhas.append(msg)


class FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self._body = body
        self.content = b"1" if body else b""
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


def fake_get(url: str, **kwargs: Any) -> FakeResponse:
    if "connectionState" in url:
        return FakeResponse(200, {"instance": {"state": "open"}})
    return FakeResponse(200, {"base64": "qr-fake"})


def fake_delete(url: str, **kwargs: Any) -> FakeResponse:
    return FakeResponse(200, {})


import requests

requests.get = fake_get
requests.delete = fake_delete

with TestClient(m.app) as c:
    r = c.put("/api/access-control/whatsapp", json={"site": "", "enabled": True, "provider": "evolution"})
    check(r.status_code == 200, f"salvar config evolution falhou: {r.status_code} {r.text[:200]}")
    dados = r.json()
    check(dados["provider"] == "evolution", dados)
    check(dados["instance"] != "sightops", f"instance nao pode voltar ser a string fixa 'sightops': {dados}")
    check(dados["instance"].endswith("-padrao"), dados)

    r = c.get("/api/access-control/whatsapp/connection?refresh_qr=1")
    check(r.status_code == 200, f"conexao com refresh_qr falhou: {r.status_code} {r.text[:200]}")
    conexao = r.json()
    check(conexao["connected"] is True, conexao)
    check(conexao["qrcode"] == "qr-fake", conexao)

    check("base_url" not in dados, f"base_url interno da plataforma nao pode voltar na resposta: {dados}")

    r = c.post("/api/access-control/whatsapp/disconnect", json={"site": ""})
    check(r.status_code == 200, f"desconectar falhou: {r.status_code} {r.text[:200]}")
    check(r.json()["state"] == "disconnected", r.json())

    # instance escolhido pelo cliente nao pode chegar no Evolution: o container
    # e a chave de admin sao compartilhados entre todos os tenants, entao um
    # nome livre no corpo do PUT daria acesso a sessao de outro cliente
    r = c.put("/api/access-control/whatsapp", json={
        "site": "", "enabled": True, "provider": "evolution", "instance": "cliente-vitima-matriz",
    })
    check(r.status_code == 200, f"salvar com instance no corpo falhou: {r.status_code} {r.text[:200]}")
    dados = r.json()
    check(dados["instance"] != "cliente-vitima-matriz", f"instance do corpo foi aceito: {dados}")
    check(dados["instance"].endswith("-padrao"), dados)

    # site em cloud_api: "nao usa Evolution" e erro de pedido (400), nao falha
    # de gateway (502) -- 502 mandava o operador caçar problema de rede inexistente
    r = c.put("/api/access-control/whatsapp", json={"site": "Unidade Meta", "enabled": True, "provider": "cloud_api"})
    check(r.status_code == 200, f"salvar cloud_api falhou: {r.status_code} {r.text[:200]}")
    r = c.post("/api/access-control/whatsapp/disconnect", json={"site": "Unidade Meta"})
    check(r.status_code == 400, f"desconectar site cloud_api devia ser 400, veio {r.status_code}: {r.text[:200]}")

if falhas:
    print("FALHAS:")
    for f in falhas:
        print(f" - {f}")
    sys.exit(1)

print("whatsapp evolution routes regression ok")
