"""Controle de Rotas -- contratantes, contratos, escolas, rotas (com paradas) e alunos.

Contratante = quem paga (prefeitura/secretaria); contrato = contratante x operador
(rotas_store) com preco por km e vigencia; rota = trajeto de um contrato, com
paradas em ordem, que o GPS vai conferir; aluno = pessoa ligada a uma parada.

Como na frota, a situacao e calculada na leitura. Uma rota bloqueada nao pode
gerar viagem valida: sem contrato vigente, sem veiculo/motorista liberado ou
com menos de 2 paradas.
"""
from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from app.services import db_store
from app.services.rotas_store import (
    _ativo,
    _data,
    _digits,
    _gravar,
    _int,
    _now,
    _opcao,
    _row,
    _rows,
    _tenant,
    _text,
    frota,
    situacao_doc,
)

TURNOS = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite", "integral": "Integral"}
MAX_PARADAS = 60


def _coord(value: Any, limite: float, campo: str) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        out = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise ValueError(f"{campo}: coordenada inválida.")
    if abs(out) > limite:
        raise ValueError(f"{campo}: coordenada fora do mapa.")
    return round(out, 7)


def _par_coord(payload: Dict[str, Any], rotulo: str):
    lat = _coord(payload.get("lat"), 90, f"{rotulo} (latitude)")
    lon = _coord(payload.get("lon"), 180, f"{rotulo} (longitude)")
    if (lat is None) != (lon is None):
        raise ValueError(f"{rotulo}: informe latitude e longitude juntas.")
    return lat, lon


def _horario(value: Any, campo: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"{campo}: horário inválido (use HH:MM).")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _preco(value: Any) -> str:
    raw = str(value or "").strip().replace("R$", "").strip()
    if not raw:
        return ""
    if "," in raw:  # "1.234,56" -> "1234.56"
        raw = raw.replace(".", "").replace(",", ".")
    try:
        out = Decimal(raw)
    except InvalidOperation:
        raise ValueError("Preço por km inválido.")
    if out < 0 or out > 1000:
        raise ValueError("Preço por km fora do esperado.")
    return str(out.quantize(Decimal("0.0001")).normalize())


def _km(value: Any) -> float:
    if value is None or str(value).strip() == "":
        return 0.0
    try:
        out = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise ValueError("Km previsto: informe um número.")
    if out < 0 or out > 2000:
        raise ValueError("Km previsto fora do esperado.")
    return round(out, 2)


def _existe(c: Any, tabela: str, tenant: str, item_id: str, aviso: str) -> Dict[str, Any]:
    r = _row(c, f"SELECT * FROM {tabela} WHERE tenant_slug=? AND id=?", (tenant, item_id))
    if not r:
        raise ValueError(aviso)
    return r


# --------------------------------------------------------------------------- situacao

def situacao_contrato(ct: Dict[str, Any], hoje: Optional[date] = None) -> Dict[str, Any]:
    hoje = hoje or date.today()
    if not int(ct.get("ativo") or 0):
        return {"situacao": "inativo", "motivos": []}
    if ct.get("inicio") and ct["inicio"] > hoje.isoformat():
        return {"situacao": "bloqueado", "motivos": [f"Contrato começa em {ct['inicio']}"]}
    if not ct.get("fim"):
        return {"situacao": "liberado", "motivos": []}
    sit = situacao_doc(ct["fim"], hoje)
    if sit["st"] == "vencido":
        return {"situacao": "bloqueado", "motivos": ["Contrato vencido"]}
    if sit["st"] == "vence":
        return {"situacao": "atencao", "motivos": [f"Contrato vence em {sit['dias']} dia(s)"]}
    return {"situacao": "liberado", "motivos": []}


def situacao_rota(rota: Dict[str, Any], contrato: Optional[Dict[str, Any]], veiculo: Optional[Dict[str, Any]],
                  motorista: Optional[Dict[str, Any]], monitor: Optional[Dict[str, Any]],
                  paradas: List[Dict[str, Any]], n_alunos: int) -> Dict[str, Any]:
    if not int(rota.get("ativo") or 0):
        return {"situacao": "inativo", "motivos": []}
    bloq: List[str] = []
    aviso: List[str] = []

    def _pessoa_ou_veiculo(item, nome_faltando, nome):
        if not item:
            bloq.append(nome_faltando)
        elif item.get("situacao") in ("bloqueado", "inativo"):
            bloq.append(f"{nome} {'inativo' if item['situacao'] == 'inativo' else 'bloqueado'}")
        elif item.get("situacao") == "atencao":
            aviso.append(f"{nome} com documento vencendo")

    if not contrato:
        bloq.append("Sem contrato")
    elif contrato["situacao"] in ("bloqueado", "inativo"):
        bloq.append(contrato["motivos"][0] if contrato["motivos"] else "Contrato inativo")
    elif contrato["situacao"] == "atencao":
        aviso.extend(contrato["motivos"])
    _pessoa_ou_veiculo(veiculo, "Sem veículo", "Veículo")
    _pessoa_ou_veiculo(motorista, "Sem motorista", "Motorista")
    if monitor and monitor.get("situacao") in ("bloqueado", "inativo"):
        aviso.append("Monitor(a) inativo(a)")
    if len(paradas) < 2:
        bloq.append("Menos de 2 paradas")
    sem_coord = sum(1 for p in paradas if p.get("lat") is None)
    if sem_coord:
        aviso.append(f"{sem_coord} parada(s) sem localização: o GPS não confere")
    if not rota.get("escola_id"):
        aviso.append("Sem escola de destino")
    if not float(rota.get("km_previsto") or 0):
        aviso.append("Sem km previsto")
    lugares = int((veiculo or {}).get("lugares") or 0)
    if lugares and n_alunos > lugares:
        aviso.append(f"{n_alunos} alunos para {lugares} lugares")
    if bloq:
        return {"situacao": "bloqueado", "motivos": bloq + aviso}
    if aviso:
        return {"situacao": "atencao", "motivos": aviso}
    return {"situacao": "liberado", "motivos": []}


def situacao_aluno(a: Dict[str, Any]) -> Dict[str, Any]:
    if not int(a.get("ativo") or 0):
        return {"situacao": "inativo", "motivos": []}
    aviso = []
    if not a.get("parada_id"):
        aviso.append("Sem parada")
    if not a.get("matricula"):
        aviso.append("Sem matrícula: não conta para o PNATE")
    return {"situacao": "atencao" if aviso else "liberado", "motivos": aviso}


# --------------------------------------------------------------------------- leitura

def cadastro(hoje: Optional[date] = None) -> Dict[str, Any]:
    tenant = _tenant()
    fr = frota(hoje)
    with db_store._conn() as c:
        contratantes = _rows(c, "SELECT * FROM rotas_contratantes WHERE tenant_slug=? ORDER BY nome", (tenant,))
        contratos = _rows(c, "SELECT * FROM rotas_contratos WHERE tenant_slug=? ORDER BY numero", (tenant,))
        escolas = _rows(c, "SELECT * FROM rotas_escolas WHERE tenant_slug=? ORDER BY nome", (tenant,))
        rotas = _rows(c, "SELECT * FROM rotas_rotas WHERE tenant_slug=? ORDER BY nome, turno", (tenant,))
        paradas = _rows(c, "SELECT * FROM rotas_paradas WHERE tenant_slug=? ORDER BY rota_id, ordem", (tenant,))
        alunos = _rows(c, "SELECT * FROM rotas_alunos WHERE tenant_slug=? ORDER BY nome", (tenant,))

    contratantes_por_id = {x["id"]: x for x in contratantes}
    operadores_por_id = {x["id"]: x for x in fr["operadores"]}
    veiculos = {x["id"]: x for x in fr["veiculos"]}
    pessoas = {x["id"]: x for x in fr["motoristas"]}
    for ct in contratos:
        ct.update(situacao_contrato(ct, hoje))
        ct["contratante_nome"] = contratantes_por_id.get(ct["contratante_id"], {}).get("nome", "")
        ct["operador_nome"] = operadores_por_id.get(ct["operador_id"], {}).get("nome", "")
        ct["rotas"] = sum(1 for r in rotas if r["contrato_id"] == ct["id"])
    contratos_por_id = {x["id"]: x for x in contratos}
    for ctt in contratantes:
        ctt["contratos"] = sum(1 for ct in contratos if ct["contratante_id"] == ctt["id"])

    paradas_por_rota: Dict[str, List[Dict[str, Any]]] = {}
    for p in paradas:
        paradas_por_rota.setdefault(p["rota_id"], []).append(p)
    alunos_ativos = [a for a in alunos if a["ativo"]]
    for r in rotas:
        r["paradas"] = paradas_por_rota.get(r["id"], [])
        n = sum(1 for a in alunos_ativos if a["rota_id"] == r["id"])
        r["alunos"] = n
        for p in r["paradas"]:
            p["alunos"] = sum(1 for a in alunos_ativos if a["parada_id"] == p["id"])
        r.update(situacao_rota(
            r, contratos_por_id.get(r["contrato_id"]), veiculos.get(r["veiculo_id"]),
            pessoas.get(r["motorista_id"]), pessoas.get(r["monitor_id"]), r["paradas"], n,
        ))
    for e in escolas:
        e["rotas"] = sum(1 for r in rotas if r["escola_id"] == e["id"])
        e["alunos"] = sum(1 for a in alunos_ativos if a["escola_id"] == e["id"])
    for a in alunos:
        a.update(situacao_aluno(a))

    ativas = [r for r in rotas if r["ativo"]]
    resumo = {
        "rotas": len(ativas),
        "rotas_liberadas": sum(1 for r in ativas if r["situacao"] == "liberado"),
        "rotas_bloqueadas": sum(1 for r in ativas if r["situacao"] == "bloqueado"),
        "alunos": len(alunos_ativos),
        "alunos_sem_parada": sum(1 for a in alunos_ativos if not a["parada_id"]),
        "km_dia": round(sum(float(r["km_previsto"] or 0) for r in ativas), 1),
    }
    return {
        "contratantes": contratantes, "contratos": contratos, "escolas": escolas,
        "rotas": rotas, "alunos": alunos, "resumo": resumo,
        # para os selects do formulario: so o que a tela precisa da frota
        "operadores": [{"id": o["id"], "nome": o["nome"], "ativo": o["ativo"]} for o in fr["operadores"]],
        "veiculos": [{"id": v["id"], "placa": v["placa"], "lugares": v["lugares"], "ativo": v["ativo"],
                      "situacao": v["situacao"]} for v in fr["veiculos"]],
        "pessoas": [{"id": m["id"], "nome": m["nome"], "funcao": m["funcao"], "ativo": m["ativo"],
                     "situacao": m["situacao"]} for m in fr["motoristas"]],
    }


# --------------------------------------------------------------------------- gravacao

def salvar_contratante(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    nome = _text(payload.get("nome"), 160)
    if not nome:
        raise ValueError("Informe o nome (ex.: Prefeitura de ..., Secretaria de Educação).")
    valores = {
        "nome": nome,
        "documento": _digits(payload.get("documento"), 14),
        "contato": _text(payload.get("contato"), 160),
        "telefone": _digits(payload.get("telefone"), 13),
        "ativo": _ativo(payload.get("ativo")),
    }
    with db_store._conn() as c:
        item_id = _gravar(c, "rotas_contratantes", tenant, _text(payload.get("id"), 64), valores)
    return {"ok": True, "id": item_id}


def salvar_contrato(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    valores = {
        "contratante_id": _text(payload.get("contratante_id"), 64),
        "operador_id": _text(payload.get("operador_id"), 64),
        "numero": _text(payload.get("numero"), 60),
        "preco_km": _preco(payload.get("preco_km")),
        "inicio": _data(payload.get("inicio"), "Início"),
        "fim": _data(payload.get("fim"), "Fim"),
        "observacoes": _text(payload.get("observacoes"), 1000),
        "ativo": _ativo(payload.get("ativo")),
    }
    if not valores["contratante_id"]:
        raise ValueError("Escolha quem paga (contratante).")
    if not valores["operador_id"]:
        raise ValueError("Escolha quem roda (empresa ou frota própria).")
    if valores["inicio"] and valores["fim"] and valores["fim"] < valores["inicio"]:
        raise ValueError("O fim do contrato é antes do início.")
    with db_store._conn() as c:
        _existe(c, "rotas_contratantes", tenant, valores["contratante_id"], "Contratante não encontrado.")
        _existe(c, "rotas_operadores", tenant, valores["operador_id"], "Empresa ou frota não encontrada.")
        item_id = _gravar(c, "rotas_contratos", tenant, _text(payload.get("id"), 64), valores)
    return {"ok": True, "id": item_id}


def salvar_escola(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    nome = _text(payload.get("nome"), 160)
    if not nome:
        raise ValueError("Informe o nome da escola.")
    lat, lon = _par_coord(payload, "Localização")
    valores = {
        "nome": nome,
        "inep": _digits(payload.get("inep"), 8),
        "endereco": _text(payload.get("endereco"), 255),
        "lat": lat,
        "lon": lon,
        "ativo": _ativo(payload.get("ativo")),
    }
    with db_store._conn() as c:
        item_id = _gravar(c, "rotas_escolas", tenant, _text(payload.get("id"), 64), valores)
    return {"ok": True, "id": item_id}


def _paradas_do_payload(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Paradas: formato inválido.")
    if len(raw) > MAX_PARADAS:
        raise ValueError(f"No máximo {MAX_PARADAS} paradas por rota.")
    out = []
    for i, p in enumerate(raw, start=1):
        if not isinstance(p, dict):
            raise ValueError("Paradas: formato inválido.")
        nome = _text(p.get("nome"), 160)
        if not nome:
            raise ValueError(f"Parada {i}: informe o nome.")
        lat, lon = _par_coord(p, f"Parada {i}")
        out.append({
            "id": _text(p.get("id"), 64), "ordem": i, "nome": nome,
            "referencia": _text(p.get("referencia"), 255),
            "horario": _horario(p.get("horario"), f"Parada {i}"),
            "lat": lat, "lon": lon,
        })
    return out


def salvar_rota(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    item_id = _text(payload.get("id"), 64)
    nome = _text(payload.get("nome"), 120)
    if not nome:
        raise ValueError("Informe o nome da rota.")
    valores = {
        "contrato_id": _text(payload.get("contrato_id"), 64),
        "escola_id": _text(payload.get("escola_id"), 64),
        "nome": nome,
        "turno": _opcao(payload.get("turno") or "manha", tuple(TURNOS), "Turno"),
        "veiculo_id": _text(payload.get("veiculo_id"), 64),
        "motorista_id": _text(payload.get("motorista_id"), 64),
        "monitor_id": _text(payload.get("monitor_id"), 64),
        "km_previsto": _km(payload.get("km_previsto")),
        "tolerancia_m": _int(payload.get("tolerancia_m") or 300, 50, 5000, "Tolerância de desvio (m)"),
        "observacoes": _text(payload.get("observacoes"), 1000),
        "ativo": _ativo(payload.get("ativo")),
    }
    if not valores["contrato_id"]:
        raise ValueError("Escolha o contrato da rota.")
    paradas = _paradas_do_payload(payload.get("paradas"))
    with db_store._conn() as c:
        _existe(c, "rotas_contratos", tenant, valores["contrato_id"], "Contrato não encontrado.")
        if valores["escola_id"]:
            _existe(c, "rotas_escolas", tenant, valores["escola_id"], "Escola não encontrada.")
        if valores["veiculo_id"]:
            _existe(c, "rotas_veiculos", tenant, valores["veiculo_id"], "Veículo não encontrado.")
        for campo, funcao, rotulo in (("motorista_id", "motorista", "Motorista"), ("monitor_id", "monitor", "Monitor(a)")):
            if valores[campo]:
                p = _existe(c, "rotas_motoristas", tenant, valores[campo], f"{rotulo} não encontrado(a).")
                if p["funcao"] != funcao:
                    raise ValueError(f"{p['nome']} não está cadastrado(a) como {rotulo.lower()}.")
        item_id = _gravar(c, "rotas_rotas", tenant, item_id, valores)
        _sincronizar_paradas(c, tenant, item_id, paradas)
    return {"ok": True, "id": item_id}


def _sincronizar_paradas(c: Any, tenant: str, rota_id: str, paradas: List[Dict[str, Any]]) -> None:
    """Mantem o id das paradas que continuam (alunos apontam para elas); parada
    removida com aluno ligado nao sai."""
    existentes = {p["id"]: p for p in _rows(c, "SELECT id, nome FROM rotas_paradas WHERE tenant_slug=? AND rota_id=?",
                                             (tenant, rota_id))}
    mantidas = {p["id"] for p in paradas if p["id"]}
    desconhecidas = mantidas - set(existentes)
    if desconhecidas:
        raise ValueError("Parada não pertence a esta rota.")
    for pid in set(existentes) - mantidas:
        uso = _row(c, "SELECT COUNT(*) AS n FROM rotas_alunos WHERE tenant_slug=? AND parada_id=?", (tenant, pid))
        if int((uso or {}).get("n") or 0):
            raise ValueError(f"A parada {existentes[pid]['nome']} tem alunos. Mude os alunos de parada antes de removê-la.")
        c.execute("DELETE FROM rotas_paradas WHERE tenant_slug=? AND id=?", (tenant, pid))
    now = _now()
    for p in paradas:
        cols = ("ordem", "nome", "referencia", "horario", "lat", "lon")
        vals = tuple(p[k] for k in cols)
        if p["id"]:
            c.execute("UPDATE rotas_paradas SET ordem=?, nome=?, referencia=?, horario=?, lat=?, lon=?, updated_at=? "
                      "WHERE tenant_slug=? AND id=?", (*vals, now, tenant, p["id"]))
        else:
            c.execute("INSERT INTO rotas_paradas(id, tenant_slug, rota_id, ordem, nome, referencia, horario, lat, lon, "
                      "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex, tenant, rota_id, *vals, now, now))


def salvar_aluno(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant = _tenant()
    item_id = _text(payload.get("id"), 64)
    nome = _text(payload.get("nome"), 160)
    if not nome:
        raise ValueError("Informe o nome do aluno.")
    valores = {
        "nome": nome,
        "matricula": _text(payload.get("matricula"), 40),
        "codigo_inep": _digits(payload.get("codigo_inep"), 12),
        "serie": _text(payload.get("serie"), 40),
        "escola_id": _text(payload.get("escola_id"), 64),
        "rota_id": _text(payload.get("rota_id"), 64),
        "parada_id": _text(payload.get("parada_id"), 64),
        "responsavel": _text(payload.get("responsavel"), 160),
        "telefone": _digits(payload.get("telefone"), 13),
        "observacoes": _text(payload.get("observacoes"), 1000),
        "ativo": _ativo(payload.get("ativo")),
    }
    if valores["parada_id"] and not valores["rota_id"]:
        raise ValueError("Escolha a rota da parada.")
    with db_store._conn() as c:
        if valores["rota_id"]:
            rota = _existe(c, "rotas_rotas", tenant, valores["rota_id"], "Rota não encontrada.")
            if not valores["escola_id"]:
                valores["escola_id"] = rota["escola_id"]
        if valores["parada_id"]:
            p = _existe(c, "rotas_paradas", tenant, valores["parada_id"], "Parada não encontrada.")
            if p["rota_id"] != valores["rota_id"]:
                raise ValueError("A parada escolhida é de outra rota.")
        if valores["escola_id"]:
            _existe(c, "rotas_escolas", tenant, valores["escola_id"], "Escola não encontrada.")
        if valores["matricula"]:
            dup = _row(c, "SELECT nome FROM rotas_alunos WHERE tenant_slug=? AND matricula=? AND id<>?",
                       (tenant, valores["matricula"], item_id))
            if dup:
                raise ValueError(f"Esta matrícula já está cadastrada ({dup['nome']}).")
        item_id = _gravar(c, "rotas_alunos", tenant, item_id, valores)
    return {"ok": True, "id": item_id}
