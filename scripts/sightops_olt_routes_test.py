"""Exercita as rotas do cadastro de OLT pela HTTP e confere o sigilo da senha.

O teste de olt_registry cobre a camada de servico; este cobre o que sai pela
rede. Sao coisas diferentes: uma rota nova que devolva a linha do banco
inteira passaria no primeiro teste e vazaria a senha aqui.

A asercao central e literal -- a senha usada no cadastro nao pode aparecer no
corpo de NENHUMA resposta (criar, listar, buscar, editar).

Roda direto:  python scripts/sightops_olt_routes_test.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="rotas-olt-"))
os.environ["DATA_DIR"] = str(tmp / "data")
os.environ["SIGHTOPS_DB_PATH"] = str(tmp / "data" / "sightops.db")
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["AUTH_DATABASE_BACKEND"] = "sqlite"
os.environ["SIGHTOPS_SECRET_KEY"] = "chave-de-teste"
os.environ["AUTH_ENABLED"] = "0"
os.environ["ENABLE_LEGACY_STATE_IMPORT"] = "0"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
import app.main as m

SENHA = "senha-super-secreta"
falhas = []


def check(cond, msg):
    if not cond:
        falhas.append(msg)


with TestClient(m.app) as c:
    # criar
    r = c.post("/api/olt/registry", json={
        "name": "OLT Centro", "host": "10.0.0.10",
        "vendor": "Fiberhome", "model": "8820i",
        "username": "admin", "password": SENHA, "site": "Centro",
    })
    check(r.status_code == 200, f"criar falhou: {r.status_code} {r.text[:200]}")
    corpo = r.text
    check(SENHA not in corpo, f"A SENHA VOLTOU NA RESPOSTA DE CRIAR: {corpo[:300]}")
    item = r.json()["item"]
    olt_id = item["id"]
    print(f"criada: id={olt_id} vendor={item['vendor']} model={item['model']} has_password={item['has_password']}")

    # repetir a mesma identidade deve atualizar, nao tentar duplicar
    r = c.post("/api/olt/registry", json={
        "name": "OLT Centro atualizada", "host": "10.0.0.10", "site": "Centro",
        "vendor": "Fiberhome", "model": "8820i", "username": "admin",
    })
    check(r.status_code == 200, f"salvar identidade repetida falhou: {r.status_code} {r.text[:200]}")
    check(r.json()["item"]["id"] == olt_id, "identidade repetida criou outra OLT")
    check(r.json()["item"]["has_password"] is True, "upsert sem senha apagou a credencial")

    # listar
    r = c.get("/api/olt/registry")
    check(r.status_code == 200, f"listar falhou: {r.status_code}")
    check(SENHA not in r.text, "A SENHA VOLTOU NA LISTAGEM")
    check(r.json()["total"] == 1, f"deveria listar 1: {r.json()}")

    # buscar por id
    r = c.get(f"/api/olt/registry/{olt_id}")
    check(r.status_code == 200, f"buscar falhou: {r.status_code}")
    check(SENHA not in r.text, "A SENHA VOLTOU NA BUSCA POR ID")

    # editar sem mandar senha
    r = c.post("/api/olt/registry", json={"id": olt_id, "name": "OLT Centro II", "host": "10.0.0.10"})
    check(r.status_code == 200, f"editar falhou: {r.status_code} {r.text[:200]}")
    check(r.json()["item"]["has_password"] is True, "editar sem senha apagou a senha")
    check(r.json()["item"]["name"] == "OLT Centro II", "nome nao foi atualizado")
    check(r.json()["item"]["site"] == "Centro", "editar sem site apagou o vinculo do site")

    # validacao
    r = c.post("/api/olt/registry", json={"name": "", "host": "1.2.3.4"})
    check(r.status_code in (400, 422), f"nome vazio deveria dar erro, deu {r.status_code}")

    # id inexistente
    r = c.get("/api/olt/registry/99999")
    check(r.status_code == 404, f"id inexistente deveria dar 404, deu {r.status_code}")

    # apagar
    r = c.delete(f"/api/olt/registry/{olt_id}")
    check(r.status_code == 200, f"apagar falhou: {r.status_code}")
    check(c.get("/api/olt/registry").json()["total"] == 0, "lista deveria ficar vazia")
    check(c.delete(f"/api/olt/registry/{olt_id}").status_code == 404, "apagar 2x deveria dar 404")

print()
if falhas:
    print(f"FALHOU ({len(falhas)}):")
    for f in falhas:
        print("  -", f)
    raise SystemExit(1)
print("OK rotas do cadastro de OLT: CRUD completo e a senha nunca volta pela API")
