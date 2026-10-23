"""Controle de Rotas -- cadastro da frota (operadores, veiculos, motoristas).

Serve prefeitura e empresa: o cliente cadastra quem roda as rotas (operador =
frota propria ou empresa contratada) e cada veiculo/motorista pertence a um.

A situacao de cada documento e calculada aqui, nunca gravada: o que vence
amanha muda sem ninguem editar o cadastro. Regras do PNATE (veiculo vistoriado
e autorizado, motorista habilitado) e do CTB art. 138 (categoria D, curso de
transporte escolar):
- veiculo: vistoria ou autorizacao vencida/faltando bloqueia; seguro so avisa;
- motorista: CNH vencida/faltando, categoria abaixo de D ou curso vencido/faltando bloqueia;
- monitor: nao dirige, nao tem documento obrigatorio aqui.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.services import db_store

AVISO_DIAS = 30
TIPOS_OPERADOR = ("frota_propria", "empresa")
TIPOS_VEICULO = ("onibus", "micro", "van", "outro")
FUNCOES = ("motorista", "monitor")
CATEGORIAS_HABILITADAS = ("D", "E")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _text(value: Any, limit: int = 255) -> str:
    return str(value or "").strip()[:limit]


def _digits(value: Any, limit: int) -> str:
    return re.sub(r"\D", "", str(value or ""))[:limit]


def _int(value: Any, minimo: int, maximo: int, campo: str) -> int:
    if value is None or str(value).strip() == "":
        return 0
    try:
        out = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{campo}: informe um número.")
    if out < minimo or out > maximo:
        raise ValueError(f"{campo}: valor fora do esperado ({minimo} a {maximo}).")
    return out


def _data(value: Any, campo: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        raise ValueError(f"{campo}: data inválida (use AAAA-MM-DD).")


def _opcao(value: Any, opcoes: tuple, campo: str) -> str:
    raw = str(value or "").strip().lower()
    if raw not in opcoes:
        raise ValueError(f"{campo}: escolha uma opção válida.")
    return raw


def _ativo(value: Any) -> int:
    # "nao"/"0"/False desligam; string qualquer nao pode virar verdadeiro sem querer.
    if value is None:
        return 1
    if isinstance(value, bool):
        return 1 if value else 0
    return 0 if str(value).strip().lower() in ("0", "false", "nao", "não", "off") else 1


def _placa(value: Any) -> str:
    out = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if not re.fullmatch(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}", out):
        raise ValueError("Placa inválida: use o formato ABC1D23 ou ABC1234.")
    return out


def _rows(c: Any, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def _row(c: Any, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    r = c.execute(sql, params).fetchone()
    return dict(r) if r else None


# --------------------------------------------------------------------------- situacao

def situacao_doc(validade: str, hoje: Optional[date] = None) -> Dict[str, Any]:
    """faltando | vencido | vence (ate AVISO_DIAS) | ok, com os dias que faltam."""
    hoje = hoje or date.today()
    if not validade:
        return {"st": "faltando", "dias": None}
    try:
        d = date.fromisoformat(validade[:10])
    except ValueError:
        return {"st": "faltando", "dias": None}
    dias = (d - hoje).days
    if dias < 0:
        return {"st": "vencido", "dias": dias}
    if dias <= AVISO_DIAS:
        return {"st": "vence", "dias": dias}
    return {"st": "ok", "dias": dias}


def _resultado(bloqueios: List[str], avisos: List[str], ativo: int) -> Dict[str, Any]:
    if not ativo:
        return {"situacao": "inativo", "motivos": []}
    if bloqueios:
        return {"situacao": "bloqueado", "motivos": bloqueios + avisos}
    if avisos:
        return {"situacao": "atencao", "motivos": avisos}
    return {"situacao": "liberado", "motivos": []}


def _conferir(docs: Dict[str, Dict[str, Any]], nomes: Dict[str, str], obrigatorios: tuple):
    bloqueios: List[str] = []
    avisos: List[str] = []
    for chave, sit in docs.items():
        nome = nomes[chave]
        if sit["st"] in ("vencido", "faltando"):
            texto = f"{nome} {'vencida' if sit['st'] == 'vencido' else 'não informada'}"
            (bloqueios if chave in obrigatorios else avisos).append(texto)
        elif sit["st"] == "vence":
            avisos.append(f"{nome} vence em {sit['dias']} dia(s)")
    return bloqueios, avisos


def situacao_veiculo(v: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    docs = {
        "vistoria": situacao_doc(v.get("vistoria_validade") or "", hoje),
        "autorizacao": situacao_doc(v.get("autorizacao_validade") or "", hoje),
        "seguro": situacao_doc(v.get("seguro_validade") or "", hoje),
    }
    nomes = {"vistoria": "Vistoria", "autorizacao": "Autorização escolar", "seguro": "Seguro"}
    bloqueios, avisos = _conferir(docs, nomes, ("vistoria", "autorizacao"))
    return {"docs": docs, **_resultado(bloqueios, avisos, int(v.get("ativo") or 0))}


def situacao_motorista(m: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    if m.get("funcao") == "monitor":
        return {"docs": {}, **_resultado([], [], int(m.get("ativo") or 0))}
    docs = {
        "cnh": situacao_doc(m.get("cnh_validade") or "", hoje),
        "curso": situacao_doc(m.get("curso_validade") or "", hoje),
    }
    nomes = {"cnh": "CNH", "curso": "Curso de transporte escolar"}
    bloqueios, avisos = _conferir(docs, nomes, ("cnh", "curso"))
    if (m.get("cnh_categoria") or "") not in CATEGORIAS_HABILITADAS:
        bloqueios.insert(0, "CNH sem categoria D ou E")
    return {"docs": docs, **_resultado(bloqueios, avisos, int(m.get("ativo") or 0))}


# --------------------------------------------------------------------------- leitura

def frota(hoje: Optional[date] = None) -> Dict[str, Any]:
    tenant = _tenant()
    with db_store._conn() as c:
        operadores = _rows(c, "SELECT * FROM rotas_operadores WHERE tenant_slug=? ORDER BY nome", (tenant,))
        veiculos = _rows(c, "SELECT * FROM rotas_veiculos WHERE tenant_slug=? ORDER BY placa", (tenant,))
        motoristas = _rows(c, "SELECT * FROM rotas_motoristas WHERE tenant_slug=? ORDER BY nome", (tenant,))
    for v in veiculos:
        v.update(situacao_veiculo(v, hoje))
    for m in motoristas:
        m.update(situacao_motorista(m, hoje))
    for o in operadores:
        o["veiculos"] = sum(1 for v in veiculos if v["operador_id"] == o["id"])
        o["motoristas"] = sum(1 for m in motoristas if m["operador_id"] == o["id"])

    def _conta(itens, st):
        return sum(1 for i in itens if i["situacao"] == st)

    ativos_v = [v for v in veiculos if v["ativo"]]
    ativos_m = [m for m in motoristas if m["ativo"]]
    resumo = {
        "veiculos": len(ativos_v), "veiculos_liberados": len(ativos_v) - _conta(ativos_v, "bloqueado"),
        "motoristas": len(ativos_m), "motoristas_liberados": len(ativos_m) - _conta(ativos_m, "bloqueado"),
        "atencao": _conta(ativos_v, "atencao") + _conta(ativos_m, "atencao"),
        "bloqueados": _conta(ativos_v, "bloqueado") + _conta(ativos_m, "bloqueado"),
    }
    return {"operadores": operadores, "veiculos": veiculos, "motoristas": motoristas, "resumo": resumo}


# --------------------------------------------------------------------------- gravacao

def _operador_existe(c: Any, tenant: str, operador_id: str) -> None:
    if not operador_id:
        raise ValueError("Escolha a empresa ou frota responsável.")
    if not _row(c, "SELECT id FROM rotas_operadores WHERE tenant_slug=? AND id=?", (tenant, operador_id)):
        raise ValueError("Empresa ou frota não encontrada.")


def _gravar(c: Any, tabela: str, tenant: str, item_id: str, valores: Dict[str, Any]) -> str:
    now = _now()
    if item_id:
        if not _row(c, f"SELECT id FROM {tabela} WHERE tenant_slug=? AND id=?", (tenant, item_id)):
            raise LookupError("Cadastro não encontrado.")
        cols = ", ".join(f"{k}=?" for k in valores)
        c.execute(f"UPDATE {tabela} SET {cols}, updated_at=? WHERE tenant_slug=? AND id=?",
                  (*valores.values(), now, tenant, item_id))
        return item_id
    novo = uuid.uuid4().hex
    cols = ", ".join(["id", "tenant_slug", *valores.keys(), "created_at", "updated_at"])
    marks = ", ".join("?" for _ in range(len(valores) + 4))
    c.execute(f"INSERT INTO {tabela}({cols}) VALUES({marks})", (novo, tenant, *valores.values(), now, now))
    return novo


def salvar_operador(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    nome = _text(payload.get("nome"), 160)
    if not nome:
        raise ValueError("Informe o nome da empresa ou da frota.")
    valores = {
        "nome": nome,
        "tipo": _opcao(payload.get("tipo") or "empresa", TIPOS_OPERADOR, "Tipo"),
        "documento": _digits(payload.get("documento"), 14),
        "contato": _text(payload.get("contato"), 160),
        "telefone": _digits(payload.get("telefone"), 13),
        "ativo": _ativo(payload.get("ativo")),
    }
    with db_store._conn() as c:
        item_id = _gravar(c, "rotas_operadores", tenant, _text(payload.get("id"), 64), valores)
    return {"ok": True, "id": item_id}


def salvar_veiculo(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    item_id = _text(payload.get("id"), 64)
    valores = {
        "operador_id": _text(payload.get("operador_id"), 64),
        "placa": _placa(payload.get("placa")),
        "modelo": _text(payload.get("modelo"), 120),
        "tipo": _opcao(payload.get("tipo") or "onibus", TIPOS_VEICULO, "Tipo"),
        "lugares": _int(payload.get("lugares"), 0, 120, "Lugares"),
        "ano": _int(payload.get("ano"), 0, 2100, "Ano"),
        "vistoria_validade": _data(payload.get("vistoria_validade"), "Vistoria"),
        "autorizacao_numero": _text(payload.get("autorizacao_numero"), 60),
        "autorizacao_validade": _data(payload.get("autorizacao_validade"), "Autorização"),
        "seguro_validade": _data(payload.get("seguro_validade"), "Seguro"),
        "observacoes": _text(payload.get("observacoes"), 1000),
        "ativo": _ativo(payload.get("ativo")),
    }
    with db_store._conn() as c:
        _operador_existe(c, tenant, valores["operador_id"])
        dup = _row(c, "SELECT id FROM rotas_veiculos WHERE tenant_slug=? AND placa=? AND id<>?",
                   (tenant, valores["placa"], item_id))
        if dup:
            raise ValueError(f"Já existe um veículo com a placa {valores['placa']}.")
        item_id = _gravar(c, "rotas_veiculos", tenant, item_id, valores)
    return {"ok": True, "id": item_id}


def salvar_motorista(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    item_id = _text(payload.get("id"), 64)
    nome = _text(payload.get("nome"), 160)
    if not nome:
        raise ValueError("Informe o nome.")
    cpf = _digits(payload.get("cpf"), 11)
    if cpf and len(cpf) != 11:
        raise ValueError("CPF deve ter 11 dígitos.")
    funcao = _opcao(payload.get("funcao") or "motorista", FUNCOES, "Função")
    categoria = _text(payload.get("cnh_categoria"), 3).upper()
    if categoria and not re.fullmatch(r"A?[B-E]|A", categoria):
        raise ValueError("Categoria da CNH inválida.")
    valores = {
        "operador_id": _text(payload.get("operador_id"), 64),
        "nome": nome,
        "funcao": funcao,
        "cpf": cpf,
        "telefone": _digits(payload.get("telefone"), 13),
        "cnh_numero": _digits(payload.get("cnh_numero"), 11),
        # "AD"/"AE" (moto + onibus) vale como D/E para o transporte escolar.
        "cnh_categoria": categoria[-1:] if categoria.startswith("A") and len(categoria) == 2 else categoria,
        "cnh_validade": _data(payload.get("cnh_validade"), "Validade da CNH"),
        "curso_validade": _data(payload.get("curso_validade"), "Curso de transporte escolar"),
        "antecedentes_data": _data(payload.get("antecedentes_data"), "Antecedentes"),
        "observacoes": _text(payload.get("observacoes"), 1000),
        "ativo": _ativo(payload.get("ativo")),
    }
    with db_store._conn() as c:
        _operador_existe(c, tenant, valores["operador_id"])
        if cpf:
            dup = _row(c, "SELECT nome FROM rotas_motoristas WHERE tenant_slug=? AND cpf=? AND id<>?",
                       (tenant, cpf, item_id))
            if dup:
                raise ValueError(f"Este CPF já está cadastrado ({dup['nome']}).")
        item_id = _gravar(c, "rotas_motoristas", tenant, item_id, valores)
    return {"ok": True, "id": item_id}


# Chave da URL -> (tabela, [quem usa este cadastro: (tabela, coluna, nome no aviso)]).
# Cadastro em uso nao sai: some do historico das viagens e da prestacao de contas.
_EXCLUIVEIS = {
    "operadores": ("rotas_operadores", [("rotas_veiculos", "operador_id", "veículos"),
                                        ("rotas_motoristas", "operador_id", "motoristas"),
                                        ("rotas_contratos", "operador_id", "contratos")]),
    "veiculos": ("rotas_veiculos", [("rotas_rotas", "veiculo_id", "rotas")]),
    "motoristas": ("rotas_motoristas", [("rotas_rotas", "motorista_id", "rotas"),
                                        ("rotas_rotas", "monitor_id", "rotas")]),
    "contratantes": ("rotas_contratantes", [("rotas_contratos", "contratante_id", "contratos")]),
    "contratos": ("rotas_contratos", [("rotas_rotas", "contrato_id", "rotas")]),
    "escolas": ("rotas_escolas", [("rotas_rotas", "escola_id", "rotas"), ("rotas_alunos", "escola_id", "alunos")]),
    "rotas": ("rotas_rotas", [("rotas_alunos", "rota_id", "alunos")]),
    "alunos": ("rotas_alunos", []),
}


def excluir(tabela: str, item_id: str) -> Dict[str, Any]:
    if tabela not in _EXCLUIVEIS:
        raise LookupError("Cadastro não encontrado.")
    nome_tabela, dependentes = _EXCLUIVEIS[tabela]
    tenant = _tenant()
    item_id = _text(item_id, 64)
    with db_store._conn() as c:
        if not _row(c, f"SELECT id FROM {nome_tabela} WHERE tenant_slug=? AND id=?", (tenant, item_id)):
            raise LookupError("Cadastro não encontrado.")
        for dep_tabela, coluna, rotulo in dependentes:
            uso = _row(c, f"SELECT COUNT(*) AS n FROM {dep_tabela} WHERE tenant_slug=? AND {coluna}=?", (tenant, item_id))
            n = int((uso or {}).get("n") or 0)
            if n:
                raise ValueError(f"Ainda em uso por {n} {rotulo}. Mude esses cadastros ou só desative este.")
        if tabela == "rotas":
            c.execute("DELETE FROM rotas_paradas WHERE tenant_slug=? AND rota_id=?", (tenant, item_id))
        c.execute(f"DELETE FROM {nome_tabela} WHERE tenant_slug=? AND id=?", (tenant, item_id))
    return {"ok": True}
