"""Regras do Ponto de venda: os "momentos para olhar" de um caixa num dia.

Sem IA e sem banco aqui: recebe os eventos, os itens e os cupons de UM caixa
num dia (como estao em pdv_eventos / pdv_itens / pdv_cupons) e devolve os
momentos suspeitos, cada um com a regra, a gravidade, a hora e o motivo em
portugues. O video do gravador e a prova; a regra so aponta onde olhar.

Os limites foram medidos nos caixas da VITAL (02 e 03/11/2026): de ~400
gavetas por dia, ~20 abrem sem venda, troco, sangria ou troca de operador.
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

# Gaveta: o que faz a abertura ser normal, e em que janela (segundos).
GAV_PAGAMENTO_ANTES_S = 60      # FIN/TRC ate 1 min antes (venda em dinheiro, troco)
GAV_FECHOU_ANTES_S = 30         # cupom fechado ate 30 s antes
GAV_SANGRIA_ANTES_S = 30        # sangria/fechamento do turno pouco antes...
GAV_SANGRIA_DEPOIS_S = 120      # ...ou ate 2 min depois (a gaveta abre antes de digitar)
GAV_TROCA_OPERADOR_S = 120      # entrada de operador (fundo de troco)
GAV_SUPERVISOR_ANTES_S = 60

CCV_REFEITO_S = 1800            # cupom cancelado: refeito se outro de valor parecido sair em 30 min
CCV_TOLERANCIA_CENTAVOS = 100   # R$ 1,00 ou 5% do valor, o que for maior
CCV_TOLERANCIA_PCT = 0.05

VALOR_ALTO_CENTAVOS = 3000      # R$ 30,00
CIT_SUPERVISOR_ANTES_S = 60

SEMCAD_DIGITADO_S = 120         # codigo sem cadastro e item digitado no mesmo cupom em ate 2 min

DIGITADO_MIN_VEZES = 10         # produto passou pelo menos 10 vezes na base...
DIGITADO_MIN_BIPADO = 0.90      # ...e foi bipado em 90% delas

PARADO_S = 120                  # 2 min sem passar item com o cupom aberto

# Para a tela: nome curto de cada regra e a ordem em que aparecem.
REGRAS = {
    "gaveta_sem_venda": "Gaveta aberta sem venda",
    "cupom_cancelado": "Cupom cancelado e não refeito",
    "item_cancelado": "Item cancelado",
    "sem_cadastro_digitado": "Sem cadastro e digitado em seguida",
    "digitado_fora_padrao": "Digitado o que costuma ser bipado",
    "cupom_parado": "Cupom parado",
}
GRAVIDADES = ("alta", "media", "baixa")

# Eventos que as regras leem (o resto do Espiao nao entra na consulta).
TIPOS_EVENTO = ("GAV", "FIN", "TRC", "FECHACUPOM", "SGR", "SOP", "RLX", "RLZ", "EOP",
                "SUPERVISOR", "CCV", "CCG", "CIT", "SBT", "ITEMSEMCAD")


def _ts(texto: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(texto)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _campos(ev: Dict[str, Any]) -> Dict[str, Any]:
    c = ev.get("campos")
    if isinstance(c, dict):
        return c
    try:
        c = json.loads(ev.get("campos_json") or "{}")
    except (TypeError, ValueError):
        c = {}
    return c if isinstance(c, dict) else {}


def _nome(texto: Any) -> str:
    """Nome comparavel: sem acento, sem espaco sobrando, minusculo."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())




def _operador(texto: Any) -> str:
    t = str(texto or "").strip()
    return "" if t == "?" else t


def _momento(regra: str, gravidade: str, ev: Dict[str, Any], titulo: str, detalhe: str,
             valor: int = 0, cupom: Optional[str] = None, ts: Optional[str] = None) -> Dict[str, Any]:
    return {"regra": regra, "gravidade": gravidade, "ts": ts or str(ev.get("ts") or ""),
            "seq": int(ev.get("seq") or 0), "cupom": str(ev.get("cupom") or "") if cupom is None else cupom,
            "operador": _operador(ev.get("operador")), "valor_centavos": int(valor or 0),
            "titulo": titulo, "detalhe": detalhe}


def _gavetas(evs: List[Dict[str, Any]], tss: List[Optional[datetime]]) -> List[Dict[str, Any]]:
    out = []
    for i, ev in enumerate(evs):
        if ev["tipo"] != "GAV" or tss[i] is None:
            continue
        t0 = tss[i]
        normal, supervisor = False, ""
        j = i - 1
        while j >= 0 and not normal:
            if tss[j] is not None:
                d = (t0 - tss[j]).total_seconds()
                if d > max(GAV_PAGAMENTO_ANTES_S, GAV_TROCA_OPERADOR_S):
                    break
                tp = evs[j]["tipo"]
                if tp in ("FIN", "TRC") and d <= GAV_PAGAMENTO_ANTES_S:
                    normal = True
                elif tp == "FECHACUPOM" and d <= GAV_FECHOU_ANTES_S:
                    normal = True
                elif tp in ("SGR", "SOP", "RLX", "RLZ") and d <= GAV_SANGRIA_ANTES_S:
                    normal = True
                elif tp == "EOP" and d <= GAV_TROCA_OPERADOR_S:
                    normal = True
                elif tp == "SUPERVISOR" and d <= GAV_SUPERVISOR_ANTES_S and not supervisor:
                    supervisor = str(_campos(evs[j]).get("Descricao") or "").strip() or "supervisor"
            j -= 1
        j = i + 1
        while j < len(evs) and not normal:
            if tss[j] is not None:
                d = (tss[j] - t0).total_seconds()
                if d > max(GAV_SANGRIA_DEPOIS_S, GAV_TROCA_OPERADOR_S):
                    break
                tp = evs[j]["tipo"]
                if tp in ("SGR", "SOP", "RLX", "RLZ") and d <= GAV_SANGRIA_DEPOIS_S:
                    normal = True
                elif tp == "EOP" and d <= GAV_TROCA_OPERADOR_S:
                    normal = True
            j += 1
        if normal:
            continue
        if supervisor:
            out.append(_momento("gaveta_sem_venda", "media", ev, "Gaveta aberta pelo supervisor sem sangria",
                                "Liberada por %s; sem venda, troco ou sangria perto." % supervisor))
        else:
            out.append(_momento("gaveta_sem_venda", "alta", ev, "Gaveta aberta sem venda",
                                "Sem pagamento ou troco 1 min antes e sem sangria até 2 min depois."))
    return out


def _cupons_cancelados(evs: List[Dict[str, Any]], tss: List[Optional[datetime]],
                       cupons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fechados = [(_ts(k.get("aberto_em")), int(k.get("total_centavos") or 0), str(k.get("cupom") or ""))
                for k in cupons if k.get("situacao") == "fechado"]
    out = []
    for i, ev in enumerate(evs):
        if ev["tipo"] not in ("CCV", "CCG") or tss[i] is None:
            continue
        v = int(ev.get("valor_centavos") or 0)
        tol = max(CCV_TOLERANCIA_CENTAVOS, int(v * CCV_TOLERANCIA_PCT))
        refeito = any(t is not None and 0 <= (t - tss[i]).total_seconds() <= CCV_REFEITO_S
                      and abs(total - v) <= tol and numero != ev.get("cupom")
                      for t, total, numero in fechados)
        if refeito:
            continue
        cupom = str(ev.get("cupom") or "")
        dinheiro = any(e["tipo"] == "FIN" and str(e.get("cupom") or "") == cupom and int(e.get("seq") or 0) < int(ev.get("seq") or 0)
                       and ("DINHEIRO" in str(_campos(e).get("Descricao") or "").upper() or str(_campos(e).get("Cod")) == "1")
                       for e in evs)
        detalhe = "Nenhum cupom de valor parecido nos 30 min seguintes."
        if dinheiro:
            detalhe += " Já tinha pagamento em dinheiro."
        out.append(_momento("cupom_cancelado", "alta", ev, "Cupom cancelado e não refeito", detalhe, v))
    return out


def _itens_cancelados(evs: List[Dict[str, Any]], tss: List[Optional[datetime]]) -> List[Dict[str, Any]]:
    out = []
    subtotal = set()  # cupons que ja passaram pelo subtotal
    for i, ev in enumerate(evs):
        cupom = str(ev.get("cupom") or "")
        if ev["tipo"] == "SBT" and cupom:
            subtotal.add(cupom)
            continue
        if ev["tipo"] != "CIT":
            continue
        v = int(ev.get("valor_centavos") or 0)
        pos_sbt, alto = cupom in subtotal, v >= VALOR_ALTO_CENTAVOS
        sup = ""
        j = i - 1
        while j >= 0 and tss[i] is not None and tss[j] is not None and (tss[i] - tss[j]).total_seconds() <= CIT_SUPERVISOR_ANTES_S:
            if evs[j]["tipo"] == "SUPERVISOR":
                sup = str(_campos(evs[j]).get("Descricao") or "").strip()
                break
            j -= 1
        operador = _operador(ev.get("operador"))
        auto = bool(sup and operador and _nome(sup) == _nome(operador))
        # depois do subtotal sozinho e comum aqui (o caixa aperta SBT varias vezes): baixa
        if auto or (pos_sbt and alto):
            grav = "alta"
        elif alto:
            grav = "media"
        elif pos_sbt:
            grav = "baixa"
        else:
            continue
        produto = str(_campos(ev).get("Descricao") or ev.get("descricao") or "item").strip()
        if auto:
            titulo = "Cancelamento liberado pelo próprio operador"
        elif pos_sbt:
            titulo = "Item cancelado depois do subtotal"
        else:
            titulo = "Item de valor alto cancelado"
        partes = [produto]
        if pos_sbt and titulo != "Item cancelado depois do subtotal":
            partes.append("depois do subtotal")
        if sup and not auto:
            partes.append("liberado por %s" % sup)
        out.append(_momento("item_cancelado", grav, ev, titulo, " · ".join(partes) + ".", v))
    return out


def _sem_cadastro(evs: List[Dict[str, Any]], tss: List[Optional[datetime]],
                  itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    por_cupom: Dict[str, List[Dict[str, Any]]] = {}
    for it in itens:
        por_cupom.setdefault(str(it.get("cupom") or ""), []).append(it)
    out = []
    for i, ev in enumerate(evs):
        cupom = str(ev.get("cupom") or "")
        if ev["tipo"] != "ITEMSEMCAD" or not cupom or tss[i] is None:
            continue
        seq = int(ev.get("seq") or 0)
        # o primeiro item que passou depois do codigo recusado
        it = next((x for x in sorted(por_cupom.get(cupom, ()), key=lambda x: int(x.get("seq") or 0))
                   if int(x.get("seq") or 0) > seq), None)
        t = _ts(it.get("ts")) if it else None
        if it is None or t is None or (t - tss[i]).total_seconds() > SEMCAD_DIGITADO_S:
            continue
        if it.get("modo") not in ("manual", "menu"):
            continue  # bipou de novo: leitura ruim, nao digitacao
        lido = str(ev.get("codigo") or _campos(ev).get("Cod") or "").strip()
        digitado = str(it.get("codigo") or "").strip()
        valor = int(it.get("valor_centavos") or 0)
        produto = str(it.get("descricao") or "produto").strip()
        etiqueta = preco_etiqueta(lido)
        if etiqueta is not None:
            # etiqueta da balanca com o preco impresso: so acusa se digitou bem menos
            if valor >= etiqueta * (1 - ETIQUETA_TOLERANCIA_PCT):
                continue
            m = _momento("sem_cadastro_digitado", "alta", ev, "Etiqueta da balança trocada por item mais barato",
                         "Etiqueta de %s; digitado %s." % (_reais(etiqueta), produto), valor)
        elif _parecidos(lido, digitado):
            continue  # o codigo lido errado e o produto certo digitado
        else:
            m = _momento("sem_cadastro_digitado", "media", ev, "Código sem cadastro e outro produto digitado",
                         "Código %s recusado; %s digitado logo depois." % (lido or "?", produto), valor)
        m["item_seq"] = int(it.get("seq") or 0)
        out.append(m)
    return out


ETIQUETA_TOLERANCIA_PCT = 0.10


def preco_etiqueta(codigo: str) -> Optional[int]:
    """Etiqueta de balanca (EAN que comeca com 2): preco em centavos nos 5
    digitos antes do verificador. Ex.: 0200383010322 -> produto 383, R$ 10,32."""
    d = str(codigo or "").strip().lstrip("0")
    if not d.isdigit() or len(d) not in (12, 13) or not d.startswith("2"):
        return None
    preco = int(d[-6:-1])
    return preco or None


def _parecidos(a: str, b: str) -> bool:
    """Codigo lido errado x codigo digitado: um dentro do outro ou quase iguais."""
    a, b = a.lstrip("0"), b.lstrip("0")
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.7


def _reais(centavos: int) -> str:
    return ("R$ %.2f" % (int(centavos) / 100.0)).replace(".", ",")


def _digitados(itens: List[Dict[str, Any]], base: Dict[str, Counter], ja: set) -> List[Dict[str, Any]]:
    out = []
    for it in itens:
        if it.get("modo") != "manual" or int(it.get("seq") or 0) in ja:
            continue
        k = base.get(str(it.get("codigo") or "")) or Counter()
        n = sum(k.values())
        if n < DIGITADO_MIN_VEZES or not k.get("scanner") or k["scanner"] / n < DIGITADO_MIN_BIPADO:
            continue
        v = int(it.get("valor_centavos") or 0)
        out.append(_momento("digitado_fora_padrao", "alta" if v >= VALOR_ALTO_CENTAVOS else "media", it,
                            "Digitado o que costuma ser bipado",
                            "%s · bipado em %d%% das %d vezes." % (str(it.get("descricao") or "produto").strip(),
                                                                   round(100.0 * k["scanner"] / n), n), v))
    return out


def _parados(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    por_cupom: Dict[str, List[Dict[str, Any]]] = {}
    for it in itens:
        if it.get("cupom"):
            por_cupom.setdefault(str(it["cupom"]), []).append(it)
    out = []
    for lista in por_cupom.values():
        lista.sort(key=lambda x: int(x.get("seq") or 0))
        for a, b in zip(lista, lista[1:]):
            ta, tb = _ts(a.get("ts")), _ts(b.get("ts"))
            if ta is None or tb is None:
                continue
            gap = (tb - ta).total_seconds()
            if gap >= PARADO_S:
                out.append(_momento("cupom_parado", "baixa", a, "Cupom parado %d min" % int(gap // 60),
                                    "Nada passou entre %s e %s." % (str(a.get("descricao") or "um item").strip(),
                                                                    str(b.get("descricao") or "o seguinte").strip())))
    return out


def avaliar(eventos: Iterable[Dict[str, Any]], itens: Iterable[Dict[str, Any]],
            cupons: Iterable[Dict[str, Any]], base_codigo: Optional[Dict[str, Counter]] = None) -> List[Dict[str, Any]]:
    """Momentos de UM caixa num dia, do mais recente para o mais antigo.

    eventos: linhas de pdv_eventos (tipo, seq, ts, cupom, operador, codigo,
    descricao, valor_centavos, campos_json ou campos). itens: pdv_itens.
    cupons: pdv_cupons. base_codigo: codigo -> Counter(modo -> vezes) dos
    ultimos dias (de onde sai o "costuma ser bipado")."""
    evs = sorted((e for e in eventos if e.get("tipo")), key=lambda e: int(e.get("seq") or 0))
    its = sorted(itens, key=lambda e: int(e.get("seq") or 0))
    cps = list(cupons)
    tss = [_ts(e.get("ts")) for e in evs]
    out = _gavetas(evs, tss) + _cupons_cancelados(evs, tss, cps) + _itens_cancelados(evs, tss)
    semcad = _sem_cadastro(evs, tss, its)
    out += semcad + _digitados(its, base_codigo or {}, {m["item_seq"] for m in semcad}) + _parados(its)
    for m in out:
        m.pop("item_seq", None)
    out.sort(key=lambda m: (m["ts"], m["seq"]), reverse=True)
    return out


def fora_da_media(momentos: Iterable[Dict[str, Any]], cupons_por_operador: Dict[tuple, int],
                  min_cupons: int = 30, min_momentos: int = 3, vezes: float = 2.0) -> List[Dict[str, Any]]:
    """Operadores com momentos (alta ou media) por cupom bem acima da loja.

    momentos: com "loja" e "operador". cupons_por_operador: (loja, operador) -> cupons.
    Sai quem tem pelo menos `vezes` a taxa da loja, com volume minimo."""
    n: Counter = Counter()
    por_regra: Dict[tuple, Counter] = {}
    for m in momentos:
        if m.get("gravidade") not in ("alta", "media") or not m.get("operador"):
            continue
        ch = (m.get("loja") or "", m["operador"])
        n[ch] += 1
        por_regra.setdefault(ch, Counter())[m["regra"]] += 1
    loja_m: Counter = Counter()
    loja_c: Counter = Counter()
    for (loja, _op), q in n.items():
        loja_m[loja] += q
    for (loja, _op), q in cupons_por_operador.items():
        loja_c[loja] += int(q or 0)
    out = []
    for (loja, op), q in n.items():
        cup = int(cupons_por_operador.get((loja, op)) or 0)
        if cup < min_cupons or q < min_momentos or not loja_c[loja] or not loja_m[loja]:
            continue
        taxa, taxa_loja = q / cup, loja_m[loja] / loja_c[loja]
        if taxa_loja and taxa / taxa_loja >= vezes:
            principal = por_regra[(loja, op)].most_common(1)[0][0]
            out.append({"loja": loja, "operador": op, "momentos": q, "cupons": cup,
                        "por_100_cupons": round(100 * taxa, 1), "loja_por_100_cupons": round(100 * taxa_loja, 1),
                        "vezes": round(taxa / taxa_loja, 1), "regra_principal": principal,
                        "regras": dict(por_regra[(loja, op)])})
    out.sort(key=lambda x: (-x["vezes"], -x["momentos"]))
    return out
