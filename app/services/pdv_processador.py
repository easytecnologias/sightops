"""Processa as linhas do PDV conforme chegam do coletor (um caixa, um dia).

O coletor manda linhas cruas numeradas do Espiao e do Teclas (ou do CM, no
caixa sem Espiao: pdv_cm converte para o formato do Espiao). Aqui elas viram
eventos, itens (com o jeito que entraram: scanner, manual, menu...) e o resumo
de cada cupom -- incrementalmente, para a tela Ao vivo.

Para dar EXATAMENTE o mesmo resultado da leitura do dia inteiro
(pdv_leitor.ler_dia, que reproduz os numeros de referencia), a linha do Espiao
espera ate o Teclas andar 5 s alem dela: o item casa com a tecla de ate 5 s
antes OU depois. Se o Teclas ficar parado (ninguem digitando), a linha sai
depois de ESPERA_MAX segundos mesmo assim.

Sem banco aqui: entra linha, sai registro. Quem grava e o pdv_store.
"""
from __future__ import annotations

import collections
import json
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.services import pdv_leitor as L
from app.services.pdv_cm import ConversorCM

ESPERA_MAX = 15.0  # s de relogio: Espiao nao espera o Teclas mais que isso
# Evento que veio do CM: seq = SEQ_CM + seq_do_cm*10 + k, numa faixa que nunca cruza
# a do Espiao (linha do arquivo) na chave (tenant, caixa, dia, seq) de pdv_eventos.
SEQ_CM = 1000000000


def centavos(valor: Any) -> int:
    v = valor if isinstance(valor, Decimal) else L.valor(valor)
    return int((v * 100).to_integral_value())


class _CasadorIncremental(object):
    """Igual ao pdv_leitor.Casador, mas recebendo as entradas aos poucos."""

    def __init__(self):
        self.entradas: List[L.Entrada] = []
        self.usado: List[bool] = []
        self.por_codigo = collections.defaultdict(list)

    def adicionar(self, e: L.Entrada) -> None:
        self.por_codigo[e.codigo].append(len(self.entradas))
        self.entradas.append(e)
        self.usado.append(False)

    def modo(self, t: float, codigo: str, desc2: str = "") -> str:
        candidatos = self.por_codigo.get(codigo, []) + (self.por_codigo.get(desc2, []) if desc2 else [])
        for i in candidatos:
            if not self.usado[i] and abs(self.entradas[i].t - t) <= L.JANELA_CASAMENTO:
                self.usado[i] = True
                return self.entradas[i].modo
        return "sem_tecla"


class _LeitorTeclas(object):
    """pdv_leitor.ler_teclas linha a linha (a sequencia de digitos atravessa lotes)."""

    def __init__(self, casador: _CasadorIncremental):
        self.casador = casador
        self.seq: list = []
        self.ultimo_t: Optional[float] = None

    def linha(self, texto: str) -> None:
        m = L._LINHA_TECLA.match(texto.strip())
        if not m:
            return
        t, k, a, r = L.segundos(m.group(1)), m.group(2), m.group(3), m.group(4)
        self.ultimo_t = t
        if a == "NUM":
            if len(r) == 1 and r.isdigit():
                self.seq.append((t, k, r))
            else:
                self.seq = []
            return
        if a == "CDP" and self.seq:
            self.casador.adicionar(L.Entrada(t, L.sem_zeros("".join(x[2] for x in self.seq)), L._modo(self.seq)))
        elif k == "MENU" and a == "VIT":
            self.casador.adicionar(L.Entrada(t, L.sem_zeros(r), "menu"))
        self.seq = []


def _cupom_novo(cupom: str, operador: str, ts: str) -> Dict[str, Any]:
    return {"cupom": cupom, "operador": operador, "aberto_em": ts, "fechado_em": "", "situacao": "aberto",
            "itens": 0, "itens_cancelados": 0, "bipados": 0, "digitados": 0, "menu": 0,
            "total_centavos": 0, "pagamento": ""}


class ProcessadorDia(object):
    """Estado de um caixa num dia. `receber` devolve o que mudou."""

    def __init__(self, dia: str):
        self.dia = dia  # 'YYYY-MM-DD'
        self.casador = _CasadorIncremental()
        self.teclas = _LeitorTeclas(self.casador)
        self.pendentes: collections.deque = collections.deque()  # (seq, Evento, recebido_em)
        self.cupom: Optional[str] = None
        self.operador = "?"
        self.cupons: Dict[str, Dict[str, Any]] = {}
        self.ultimo_seq = {"Espiao": 0, "Teclas": 0, "CM": 0}
        # De onde vem a venda neste dia: o primeiro que gerar evento ganha o dia
        # inteiro ("espiao" ou "cm"). Assim, se ligarem o Espiao no meio do dia,
        # a venda nao conta duas vezes; o dia seguinte ja comeca pelo Espiao.
        self.fonte = ""
        self.conversor: Optional[ConversorCM] = None

    # ------------------------------------------------------------ entrada
    def receber(self, espiao=(), teclas=(), cm=(), agora: Optional[float] = None, final: bool = False) -> Dict[str, Any]:
        """espiao/teclas/cm: [(seq, linha)] em ordem. Linha ja vista (seq <= ultimo) e ignorada.

        cm: linhas do CM, para caixa sem Espiao; viram eventos de Espiao com
        seq = SEQ_CM + seq_do_cm * 10 + k."""
        agora = time.time() if agora is None else agora
        for seq, texto in teclas:
            if seq <= self.ultimo_seq["Teclas"]:
                continue
            self.ultimo_seq["Teclas"] = seq
            self.teclas.linha(texto)
        for seq, texto in espiao:
            if seq <= self.ultimo_seq["Espiao"]:
                continue
            self.ultimo_seq["Espiao"] = seq
            if self.fonte == "cm":
                continue
            ev = L.ler_linha_espiao(texto)
            if ev is not None:
                self.fonte = "espiao"
                self.pendentes.append((seq, ev, agora))
        for seq, texto in cm:
            if seq <= self.ultimo_seq["CM"]:
                continue
            self.ultimo_seq["CM"] = seq
            if self.fonte == "espiao":
                continue
            if self.conversor is None:
                self.conversor = ConversorCM()
            for k, linha in enumerate(self.conversor.linha(texto)[:10]):
                ev = L.ler_linha_espiao(linha)
                if ev is not None:
                    self.fonte = "cm"
                    self.pendentes.append((SEQ_CM + seq * 10 + k, ev, agora))
        return self._liberar(agora, final)

    def previa(self) -> Dict[str, Any]:
        """O que ja chegou e ainda espera tecla, SEM consumir nada: para o Ao vivo
        mostrar o item na hora. O modo e provisorio (casa com a tecla que ja
        existe); o definitivo sai quando a linha for liberada e gravada."""
        cupom, operador, aberto, itens, fechou = self.cupom, self.operador, "", [], False
        usados = set()
        for seq, ev, _ in self.pendentes:
            if ev.tipo == "ABRECUPOM":
                cupom, operador, aberto, itens, fechou = ev.get("Cod") or None, ev.get("Descricao", "?") or "?", \
                    "%s %s" % (self.dia, ev.hora), [], False
            elif ev.tipo == "FECHACUPOM":
                fechou = True
            elif ev.tipo == "VIT" and cupom:
                cod, d2 = L.sem_zeros(ev.get("Cod")), L.sem_zeros(ev.get("Desc2"))
                modo = "sem_tecla"
                cands = self.casador.por_codigo.get(cod, []) + (self.casador.por_codigo.get(d2, []) if d2 else [])
                for i in cands:
                    if i not in usados and not self.casador.usado[i] and abs(self.casador.entradas[i].t - ev.t) <= L.JANELA_CASAMENTO:
                        usados.add(i)
                        modo = self.casador.entradas[i].modo
                        break
                itens.append({"seq": seq, "ts": "%s %s" % (self.dia, ev.hora), "codigo": cod,
                              "descricao": ev.get("Descricao"), "quant": ev.get("Quant"),
                              "valor_centavos": centavos(ev.get("VlTotal")), "modo": modo, "provisorio": True})
        return {"cupom": cupom, "operador": operador, "aberto_em": aberto, "itens": itens, "fechou": fechou}

    def finalizar(self) -> Dict[str, Any]:
        return self._liberar(time.time(), True)

    # ------------------------------------------------------------ saida
    def _pode_sair(self, ev: L.Evento, recebido: float, agora: float) -> bool:
        if ev.tipo != "VIT":
            return True  # so o item precisa da tecla; o resto segue a ordem
        lim = self.teclas.ultimo_t
        return (lim is not None and lim >= ev.t + L.JANELA_CASAMENTO) or (agora - recebido) >= ESPERA_MAX

    def _liberar(self, agora: float, final: bool) -> Dict[str, Any]:
        out = {"eventos": [], "itens": [], "cupons": []}
        mudados = []
        # em ordem: um VIT esperando segura os eventos que vem depois dele
        while self.pendentes:
            seq, ev, recebido = self.pendentes[0]
            if not final and not self._pode_sair(ev, recebido, agora):
                break
            self.pendentes.popleft()
            self._aplicar(seq, ev, out, mudados)
        vistos = set()
        for c in mudados:
            if c not in vistos and c in self.cupons:
                vistos.add(c)
                out["cupons"].append(dict(self.cupons[c]))
        return out

    def _ts(self, ev: L.Evento) -> str:
        return "%s %s" % (self.dia, ev.hora)

    def _aplicar(self, seq: int, ev: L.Evento, out: Dict[str, list], mudados: list) -> None:
        ts, tipo, f = self._ts(ev), ev.tipo, ev.campos
        cupom_ev = self.cupom or ""
        if tipo == "ABRECUPOM":
            self.cupom = ev.get("Cod") or None
            self.operador = ev.get("Descricao", "?") or "?"
            cupom_ev = self.cupom or ""
            if self.cupom:
                self.cupons[self.cupom] = _cupom_novo(self.cupom, self.operador, ts)
                mudados.append(self.cupom)
        elif tipo in ("FECHACUPOM", "CCV", "CCG", "SBT"):
            cupom_ev = ev.get("Cod") or cupom_ev

        valor_txt = f.get("VlTotal") if f.get("VlTotal") not in (None, "") else f.get("VlUnit", "")
        out["eventos"].append({
            "seq": seq, "ts": ts, "tipo": tipo, "cupom": cupom_ev, "operador": self.operador,
            "codigo": ev.get("Cod"), "descricao": ev.get("Descricao"),
            "valor_centavos": centavos(valor_txt), "campos_json": json.dumps(f, ensure_ascii=False),
        })

        c = self.cupons.get(self.cupom) if self.cupom else None
        if tipo == "VIT" and self.cupom:
            cod, d2 = L.sem_zeros(ev.get("Cod")), L.sem_zeros(ev.get("Desc2"))
            modo = self.casador.modo(ev.t, cod, d2)
            vc = centavos(ev.get("VlTotal"))
            out["itens"].append({
                "seq": seq, "ts": ts, "cupom": self.cupom, "operador": self.operador, "codigo": cod,
                "desc2": d2, "descricao": ev.get("Descricao"), "quant": ev.get("Quant"),
                "valor_centavos": vc, "modo": modo,
            })
            if c is not None:
                c["itens"] += 1
                c["total_centavos"] += vc
                if modo == "scanner":
                    c["bipados"] += 1
                elif modo == "manual":
                    c["digitados"] += 1
                elif modo == "menu":
                    c["menu"] += 1
                mudados.append(self.cupom)
        elif tipo == "CIT" and c is not None:
            c["itens_cancelados"] += 1
            c["total_centavos"] -= centavos(ev.get("VlTotal"))
            mudados.append(self.cupom)
        elif tipo == "FIN" and c is not None:
            forma = ev.get("Descricao")
            if forma and forma not in c["pagamento"].split(", "):
                c["pagamento"] = (c["pagamento"] + ", " + forma).strip(", ")
            mudados.append(self.cupom)
        elif tipo == "FECHACUPOM":
            alvo = self.cupons.get(ev.get("Cod") or "") or c
            if alvo is not None:
                alvo["fechado_em"] = ts
                if alvo["situacao"] != "cancelado":
                    alvo["situacao"] = "fechado"
                alvo["total_centavos"] = centavos(ev.get("VlTotal"))
                mudados.append(alvo["cupom"])
            self.cupom = None
        elif tipo in ("CCV", "CCG"):
            alvo = self.cupons.get(ev.get("Cod") or "")
            if alvo is not None:
                alvo["situacao"] = "cancelado"
                alvo["fechado_em"] = alvo["fechado_em"] or ts
                mudados.append(alvo["cupom"])
