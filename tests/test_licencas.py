"""Planos e licencas por equipamento. SQLite temporario; o parque do "sierra"
reproduz a contagem real de monitoring_entities em 20/10/2026."""
from __future__ import annotations

import pytest

from app.core import tenant_context
from app.services import db_store
from app.services import licensing_service as L

SIERRA = {"camera": 70, "nvr": 2, "connector": 1, "olt": 1, "onu": 151, "switch": 1, "windows": 1}
DONO = {"id": 1, "tenant_id": 1, "is_platform_admin": 1}
CLIENTE = {"id": 9, "tenant_id": 5, "is_platform_admin": 0, "role": "owner"}
_AUDIT_REAL = L._audit  # a fixture troca por um no-op


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setattr(db_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db_store, "SIGHTOPS_DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(tenant_context, "DATA_DIR", tmp_path)
    monkeypatch.setattr(L, "_audit", lambda *a, **k: None)
    db_store.init_db()
    yield tmp_path


def _parque(slug, tipos):
    with db_store._conn() as c:
        for tipo, n in tipos.items():
            for i in range(n):
                c.execute(
                    "INSERT INTO monitoring_entities(tenant_slug, entity_key, entity_type, display_name) VALUES(?,?,?,?)",
                    (slug, f"{tipo}:{i}", tipo, f"{tipo} {i}"),
                )


def test_conta_com_peso_e_arredonda_para_cima(banco):
    _parque("sierra", SIERRA)
    s = L.tenant_summary("sierra")
    # 70 + 2 + 1 (switch) + 5 (OLT) + 15,1 (ONU) + 0,5 (windows) + 0 (conector) = 93,6 -> 94
    assert s["licenses_used"] == 94
    onu = next(r for r in s["breakdown"] if r["type"] == "onu")
    assert onu["count"] == 151 and onu["licenses"] == 15.1
    assert s["status"] == "sem_plano" and s["license_limit"] is None


def test_outro_cliente_nao_entra_na_conta(banco):
    _parque("sierra", SIERRA)
    _parque("rads", {"camera": 471})
    assert L.tenant_summary("sierra")["licenses_used"] == 94


def test_aviso_tolerancia_e_volta_ao_normal(banco):
    _parque("sierra", SIERRA)
    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial"})  # 100
    assert L.tenant_summary("sierra")["status"] == "aviso"  # 94 >= 90%

    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial", "license_limit": 90})
    s = L.tenant_summary("sierra")
    assert s["status"] == "tolerancia" and s["over_since"]  # 94 <= 90 + 10%

    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial", "license_limit": 80})
    assert L.tenant_summary("sierra")["status"] == "excedido"  # 94 > 80 + 10%

    L.set_tenant_plan(DONO, "sierra", {"plan": "profissional", "license_limit": ""})
    s = L.tenant_summary("sierra")
    assert s["status"] == "ok" and s["over_since"] is None and s["license_limit"] == 250


def test_tolerancia_vence_pelo_prazo(banco, monkeypatch):
    _parque("sierra", SIERRA)
    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial", "license_limit": 90})
    L.tenant_summary("sierra")
    L._save_over({"sierra": "2026-01-01T00:00:00+00:00"})
    assert L.tenant_summary("sierra")["status"] == "excedido"


def test_peso_novo_muda_a_conta(banco):
    _parque("sierra", SIERRA)
    L.save_weights(DONO, {"onu": "0,2"})
    assert L.tenant_summary("sierra")["licenses_used"] == 109  # 78,5 + 30,2


def test_cliente_nao_escreve_nada_de_plataforma(banco):
    for fn, args in [
        (L.save_plan, ("teste", {"name": "Grátis"})),
        (L.save_weights, ({"camera": 0},)),
        (L.save_policy, ({"tolerance_pct": 100},)),
        (L.set_tenant_plan, ("sierra", {"plan": "empresarial"})),
    ]:
        with pytest.raises(PermissionError):
            fn(CLIENTE, *args)


def test_plano_inexistente_e_valores_invalidos(banco):
    with pytest.raises(ValueError):
        L.set_tenant_plan(DONO, "sierra", {"plan": "nao-existe"})
    with pytest.raises(ValueError):
        L.save_policy(DONO, {"after": "desligar_monitoramento"})
    with pytest.raises(ValueError):
        L.save_weights(DONO, {"camera": "abc"})


def test_visao_do_dono_traz_todos_e_conta_clientes_por_plano(banco):
    _parque("sierra", SIERRA)
    _parque("grupo-jangadeiros", {"camera": 104, "nvr": 4, "switch": 2, "access_point": 1, "windows": 1, "connector": 2})
    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial"})
    L.set_tenant_plan(DONO, "grupo-jangadeiros", {"plan": "profissional"})
    tenants = [{"id": 2, "slug": "sierra", "name": "sierra", "users": 1},
               {"id": 3, "slug": "grupo-jangadeiros", "name": "GRUPO JANGADEIROS", "users": 1},
               {"id": 1, "slug": "default", "name": "Easy Tecnologias", "users": 2}]
    v = L.platform_overview(tenants)
    por_slug = {t["tenant_slug"]: t for t in v["tenants"]}
    assert por_slug["grupo-jangadeiros"]["licenses_used"] == 112  # 104+4+2+1+0,5 = 111,5
    assert por_slug["default"]["status"] == "sem_limite"  # Interno
    planos = {p["key"]: p["tenants"] for p in v["plans"]}
    assert planos["essencial"] == 1 and planos["profissional"] == 1 and planos["interno"] == 1


def test_estado_fica_fora_de_qualquer_cliente(banco):
    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial"})
    with db_store._conn() as c:
        linhas = c.execute("SELECT tenant_slug, k FROM json_state").fetchall()
    assert {r["tenant_slug"] for r in linhas} == {"_platform"}


def test_leitura_do_cliente_nao_regrava_planos(banco):
    _parque("sierra", SIERRA)
    L.set_tenant_plan(DONO, "sierra", {"plan": "essencial", "license_limit": 90, "note": "cobrar dia 5"})
    antes = L._read_row("licensing")
    assert L.tenant_summary("sierra")["status"] == "tolerancia"
    assert L._read_row("licensing") == antes  # excesso foi para licensing_over
    assert "sierra" in L._load_over()


def test_auditoria_vai_para_plataforma_sem_nota(banco, monkeypatch):
    import app.services.auth_store as A

    gravados = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(A, "_conn", lambda: Conn())
    monkeypatch.setattr(A, "_audit", lambda c, **k: gravados.append(k))
    _AUDIT_REAL(DONO, "licensing.tenant_plan", "sierra", {"after": {"plan": "essencial", "note": "cobrar dia 5"}})
    assert gravados[0]["tenant_id"] is None
    assert "cobrar" not in gravados[0]["detail_json"] and "essencial" in gravados[0]["detail_json"]
