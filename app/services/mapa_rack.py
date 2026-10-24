"""Rack no mapa (rede neutra): ponto do KMZ com os equipamentos dentro, as
portas de cada um, as ligacoes porta-a-porta e os provedores que entram.

Fica no meta da camada, ao lado de caixas/ctos/cdos: meta["racks"][id].
Este modulo so valida e monta o registro; quem le/grava o meta (com o lock
das caixas) e o endpoint da camada em tools.py.

Exemplo real (Jardins Perucaba): DIO dos provedores -> CRS317 (cada provedor
numa sfp, com as VLANs dele) -> OLT / CCR de borda / tronco para outro rack.
O usuario monta e liga ponto a ponto; o monitoramento dos links (porta,
trafego, potencia do SFP) vem depois e le daqui qual porta e de qual provedor.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

TIPOS_EQUIPAMENTO = {
    "dio": "DIO",
    "olt": "OLT",
    "borda": "Borda (roteador)",
    "switch": "Switch",
    "nvr": "Gravador (NVR)",
    "dvr": "DVR",
    "servidor": "Servidor",
    "computador": "Computador",
    "outro": "Outro",
}
TIPOS_LIGACAO = {"patch": "Cordão óptico", "dac": "Cabo DAC", "utp": "Cabo de rede", "fibra": "Fibra"}
MAX_RACKS = 300
MAX_EQUIPAMENTOS = 60
MAX_PORTAS = 160
MAX_LIGACOES = 600
MAX_PROVEDORES = 120


class RackErro(ValueError):
    """Dado do rack invalido: o endpoint devolve 400 com a mensagem."""


def _txt(valor: Any, limite: int) -> str:
    return str(valor or "").strip()[:limite]


def _id(valor: Any, prefixo: str) -> str:
    v = re.sub(r"[^A-Za-z0-9_-]", "", str(valor or ""))[:24]
    return v or f"{prefixo}{uuid.uuid4().hex[:10]}"


def _coord(valor: Any, limite: float, campo: str) -> Optional[float]:
    if valor in (None, ""):
        return None
    try:
        out = float(valor)
    except (TypeError, ValueError):
        raise RackErro(f"{campo} inválida.")
    if abs(out) > limite:
        raise RackErro(f"{campo} fora do mapa.")
    return round(out, 7)


def _vlans(valor: Any) -> List[int]:
    """'3030, 3031' ou [3030, 3031] -> [3030, 3031]; faixa '2500-2502' vale."""
    partes = valor if isinstance(valor, list) else re.split(r"[,\s;]+", str(valor or ""))
    out: List[int] = []
    for p in partes:
        p = str(p).strip()
        if not p:
            continue
        m = re.fullmatch(r"(\d{1,4})\s*-\s*(\d{1,4})", p)
        nums = range(int(m.group(1)), int(m.group(2)) + 1) if m else ([int(p)] if p.isdigit() else None)
        if nums is None:
            raise RackErro(f"VLAN inválida: {p}")
        for n in nums:
            if not 1 <= n <= 4094:
                raise RackErro(f"VLAN fora da faixa (1 a 4094): {n}")
            if n not in out:
                out.append(n)
        if len(out) > 256:
            raise RackErro("Muitas VLANs para um provedor (máximo 256).")
    return sorted(out)


def _portas(raw: Any, nome_eq: str) -> List[Dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise RackErro(f"{nome_eq}: informe as portas.")
    if len(raw) > MAX_PORTAS:
        raise RackErro(f"{nome_eq}: no máximo {MAX_PORTAS} portas.")
    out, vistos = [], set()
    for p in raw:
        p = p if isinstance(p, dict) else {"id": p}
        pid = _txt(p.get("id"), 40)
        if not pid:
            raise RackErro(f"{nome_eq}: porta sem nome.")
        if pid.lower() in vistos:
            raise RackErro(f"{nome_eq}: porta repetida ({pid}).")
        vistos.add(pid.lower())
        out.append({"id": pid, "rotulo": _txt(p.get("rotulo"), 120)})
    return out


def _equipamentos(raw: Any) -> List[Dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise RackErro("Equipamentos: formato inválido.")
    if len(raw) > MAX_EQUIPAMENTOS:
        raise RackErro(f"No máximo {MAX_EQUIPAMENTOS} equipamentos por rack.")
    out, ids = [], set()
    for i, e in enumerate(raw, start=1):
        if not isinstance(e, dict):
            raise RackErro("Equipamentos: formato inválido.")
        nome = _txt(e.get("nome"), 80)
        if not nome:
            raise RackErro(f"Equipamento {i}: informe o nome.")
        tipo = _txt(e.get("tipo") or "outro", 20)
        if tipo not in TIPOS_EQUIPAMENTO:
            raise RackErro(f"{nome}: tipo inválido.")
        eid = _id(e.get("id"), "eq")
        if eid in ids:
            raise RackErro(f"{nome}: identificador repetido.")
        ids.add(eid)
        item = {
            "id": eid, "tipo": tipo, "nome": nome,
            "modelo": _txt(e.get("modelo"), 60),
            # vinculo opcional com o que o SightOps ja monitora (ex.: "olt:..." / "connector:...")
            "entidade": _txt(e.get("entidade"), 200),
            "portas": _portas(e.get("portas"), nome),
            "obs": _txt(e.get("obs"), 300),
        }
        if tipo in ("switch", "borda") and e.get("switch_id"):
            # switch cadastrada em Switch Provedores: dela vem a leitura dos links
            item["switch_id"] = re.sub(r"[^A-Za-z0-9_-]", "", str(e.get("switch_id")))[:40]
        out.append(item)
    return out


def _ponta(raw: Any, eqs: Dict[str, Dict[str, Any]], rotulo: str) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise RackErro(f"{rotulo}: escolha equipamento e porta.")
    eq = eqs.get(_txt(raw.get("eq"), 24))
    if not eq:
        raise RackErro(f"{rotulo}: equipamento não está neste rack.")
    porta = _txt(raw.get("porta"), 40)
    if porta.lower() not in {p["id"].lower() for p in eq["portas"]}:
        raise RackErro(f"{rotulo}: {eq['nome']} não tem a porta {porta or '(vazia)'}.")
    real = next(p["id"] for p in eq["portas"] if p["id"].lower() == porta.lower())
    return {"eq": eq["id"], "porta": real}


def _ligacoes(raw: Any, eqs: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise RackErro("Ligações: formato inválido.")
    if len(raw) > MAX_LIGACOES:
        raise RackErro(f"No máximo {MAX_LIGACOES} ligações por rack.")
    out, ocupadas = [], {}
    for i, lg in enumerate(raw, start=1):
        if not isinstance(lg, dict):
            raise RackErro("Ligações: formato inválido.")
        a = _ponta(lg.get("a"), eqs, f"Ligação {i} (ponta A)")
        b = _ponta(lg.get("b"), eqs, f"Ligação {i} (ponta B)")
        if a == b:
            raise RackErro(f"Ligação {i}: as duas pontas são a mesma porta.")
        for p in (a, b):
            chave = (p["eq"], p["porta"].lower())
            if chave in ocupadas:
                raise RackErro(f"{eqs[p['eq']]['nome']} {p['porta']} já está ligada (ligação {ocupadas[chave]}).")
            ocupadas[chave] = i
        tipo = _txt(lg.get("tipo") or "patch", 10)
        if tipo not in TIPOS_LIGACAO:
            raise RackErro(f"Ligação {i}: tipo inválido.")
        out.append({"id": _id(lg.get("id"), "lg"), "a": a, "b": b, "tipo": tipo, "obs": _txt(lg.get("obs"), 200)})
    return out


def _provedores(raw: Any, eqs: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise RackErro("Provedores: formato inválido.")
    if len(raw) > MAX_PROVEDORES:
        raise RackErro(f"No máximo {MAX_PROVEDORES} provedores por rack.")
    out, portas = [], {}
    for i, pv in enumerate(raw, start=1):
        if not isinstance(pv, dict):
            raise RackErro("Provedores: formato inválido.")
        nome = _txt(pv.get("nome"), 80)
        if not nome:
            raise RackErro(f"Provedor {i}: informe o nome.")
        entrada = _ponta(pv.get("entrada"), eqs, nome)
        chave = (entrada["eq"], entrada["porta"].lower())
        if chave in portas:
            raise RackErro(f"{nome}: a porta {entrada['porta']} já é de {portas[chave]}.")
        portas[chave] = nome
        try:
            banda = int(pv.get("banda_mbps") or 0)
        except (TypeError, ValueError):
            raise RackErro(f"{nome}: banda inválida.")
        if not 0 <= banda <= 400000:
            raise RackErro(f"{nome}: banda fora do esperado.")
        out.append({
            "id": _id(pv.get("id"), "pv"), "nome": nome, "entrada": entrada,
            "vlans": _vlans(pv.get("vlans")), "banda_mbps": banda,
            "contato": _txt(pv.get("contato"), 120), "obs": _txt(pv.get("obs"), 300),
        })
    return out


def salvar_rack(meta: Dict[str, Any], dados: Dict[str, Any], por: str = "") -> Dict[str, Any]:
    """Cria/atualiza/exclui um rack no meta (muda o dict). Devolve o rack (ou {} ao excluir).
    Quem chama segura o lock da camada e grava o meta."""
    racks = meta.get("racks") if isinstance(meta.get("racks"), dict) else {}
    rid = _txt(dados.get("id"), 24)
    atual = racks.get(rid) if rid else None
    if rid and not atual:
        raise LookupError("Rack não encontrado.")
    if dados.get("excluir"):
        racks.pop(rid, None)
        meta["racks"] = racks
        return {}
    ponto = _txt(dados.get("ponto") or (atual or {}).get("ponto"), 160)
    if not ponto:
        raise RackErro("Informe o ponto do mapa que é o rack.")
    lat = _coord(dados.get("lat"), 90, "Latitude")
    lng = _coord(dados.get("lng"), 180, "Longitude")
    if lat is None or lng is None:
        lat, lng = (atual or {}).get("lat"), (atual or {}).get("lng")
    if lat is not None and any(r.get("id") != rid and r.get("lat") is not None
                               and abs(float(r["lat"]) - lat) < 3e-5 and abs(float(r["lng"]) - lng) < 3e-5
                               for r in racks.values()):
        raise RackErro("Já existe um rack neste lugar do mapa.")
    if not atual and len(racks) >= MAX_RACKS:
        raise RackErro("Limite de racks na camada.")
    # sem a lista no pedido, mantem a que ja existe (editar so o nome nao apaga o rack por dentro)
    eqs_lista = _equipamentos(dados["equipamentos"]) if "equipamentos" in dados else (atual or {}).get("equipamentos", [])
    eqs = {e["id"]: e for e in eqs_lista}
    ligs = _ligacoes(dados["ligacoes"], eqs) if "ligacoes" in dados else _ligacoes((atual or {}).get("ligacoes", []), eqs)
    provs = _provedores(dados["provedores"], eqs) if "provedores" in dados else _provedores((atual or {}).get("provedores", []), eqs)
    agora = datetime.now().isoformat(timespec="seconds")
    rid = rid or f"rk{uuid.uuid4().hex[:10]}"
    racks[rid] = {
        "id": rid, "ponto": ponto, "nome": _txt(dados.get("nome"), 80) or (atual or {}).get("nome") or ponto,
        "lat": lat, "lng": lng, "obs": _txt(dados.get("obs") if "obs" in dados else (atual or {}).get("obs"), 300),
        "equipamentos": eqs_lista, "ligacoes": ligs, "provedores": provs,
        "criado_em": (atual or {}).get("criado_em") or agora, "criado_por": (atual or {}).get("criado_por") or por,
        "atualizado_em": agora, "atualizado_por": por,
    }
    meta["racks"] = racks
    return racks[rid]


def caminho_da_porta(rack: Dict[str, Any], eq_id: str, porta: str) -> List[Dict[str, str]]:
    """Segue as ligacoes a partir de uma porta: [{eq, porta, nome}] na ordem.
    Ex.: DIO P3 -> CRS sfp-sfpplus4. Para nas portas sem ligacao (fim do caminho)."""
    eqs = {e["id"]: e for e in rack.get("equipamentos", [])}
    lig = {}
    for lg in rack.get("ligacoes", []):
        a, b = (lg["a"]["eq"], lg["a"]["porta"].lower()), (lg["b"]["eq"], lg["b"]["porta"].lower())
        lig[a], lig[b] = lg["b"], lg["a"]
    out, atual, vistos = [], {"eq": eq_id, "porta": porta}, set()
    while atual and (atual["eq"], atual["porta"].lower()) not in vistos:
        vistos.add((atual["eq"], atual["porta"].lower()))
        out.append({**atual, "nome": eqs.get(atual["eq"], {}).get("nome", "?")})
        atual = lig.get((atual["eq"], atual["porta"].lower()))
    return out
