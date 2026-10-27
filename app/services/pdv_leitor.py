"""Leitor dos arquivos do PDV (Espiao e Teclas) -- sem IA, so os dados do caixa.

Formato (ver docs do modulo PDV):
  Espiao  HH:MM:SS:EVENTO | Campo: valor | Campo: valor|
  Teclas  HH:MM:SS.mmm|K:<tecla>|A:<acao>|R:<valor>|S:<S/N>|[tela]|
Arquivos em latin-1 com CRLF, um por dia e por estacao (EspiaoDDMMAA.NNN).

Como o item entrou no caixa: o scanner "digita" pela fileira de cima
(K:48-57) a ~8 ms por tecla; a pessoa usa o teclado numerico (K:96-105) ou
digita devagar. Cada VIT do Espiao e casado com a entrada de mesmo codigo no
Teclas (Cod ou Desc2, sem zeros a esquerda) em ate 5 s.

So stdlib e compativel com Python 3.8: o coletor que roda no PDV reaproveita
este arquivo.
"""
from __future__ import annotations

import collections
import datetime as _dt
import os
import re
import statistics
from decimal import Decimal, InvalidOperation

CODIFICACAO = "latin-1"

_LINHA_ESPIAO = re.compile(r"^(\d{2}:\d{2}:\d{2}):([A-Z]+)\s*\|(.*)$")
_LINHA_TECLA = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d+)\|K:([^|]*)\|A:([^|]*)\|R:([^|]*)\|")
_NOME_ARQUIVO = re.compile(r"^(Espiao|Teclas|CM)(\d{2})(\d{2})(\d{2})\.(\d{3})$", re.I)

TECLAS_SCANNER = frozenset(str(c) for c in range(48, 58))   # '0'..'9' fileira de cima
TECLAS_NUMERICO = frozenset(str(c) for c in range(96, 106))  # teclado numerico
INTERVALO_SCANNER = 0.03   # mediana entre teclas abaixo disso = scanner
JANELA_CASAMENTO = 5       # segundos entre a tecla e o VIT
MODOS = ("scanner", "manual", "menu", "outro", "sem_tecla")


class Evento(object):
    __slots__ = ("hora", "t", "tipo", "campos", "crua")

    def __init__(self, hora, t, tipo, campos, crua):
        self.hora, self.t, self.tipo, self.campos, self.crua = hora, t, tipo, campos, crua

    def get(self, campo, padrao=""):
        return self.campos.get(campo, padrao)

    def __repr__(self):
        return "Evento(%s %s %r)" % (self.hora, self.tipo, self.campos)


class Entrada(object):
    """Um codigo que entrou pelo Teclas (Enter apos digitos, ou item escolhido no menu)."""
    __slots__ = ("t", "codigo", "modo")

    def __init__(self, t, codigo, modo):
        self.t, self.codigo, self.modo = t, codigo, modo

    def __repr__(self):
        return "Entrada(%.3f %s %s)" % (self.t, self.codigo, self.modo)


class Item(object):
    """VIT dentro de cupom, com o modo de entrada ja classificado."""
    __slots__ = ("hora", "t", "cupom", "operador", "codigo", "desc2", "descricao",
                 "quant", "valor", "modo")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __repr__(self):
        return "Item(%s %s %s R$%s %s)" % (self.hora, self.cupom, self.codigo, self.valor, self.modo)


# ---------------------------------------------------------------- utilidades

def segundos(hora):
    h, m, s = hora.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def valor(texto):
    """'12,34' / '12.34' -> Decimal. Vazio ou lixo -> 0 (como no PDV)."""
    try:
        return Decimal(str(texto).strip().replace(",", ".") or "0")
    except InvalidOperation:
        return Decimal(0)


def sem_zeros(codigo):
    return (codigo or "").strip().lstrip("0")


def info_arquivo(nome):
    """'Espiao281026.001' -> ('Espiao', date(2026,10,28), 1). None se nao for do PDV."""
    m = _NOME_ARQUIVO.match(os.path.basename(nome))
    if not m:
        return None
    tipo, dd, mm, aa, est = m.groups()
    try:
        dia = _dt.date(2000 + int(aa), int(mm), int(dd))
    except ValueError:
        return None
    tipo = "CM" if tipo.upper() == "CM" else tipo.capitalize()
    return tipo, dia, int(est)


def _linhas(origem):
    """Aceita caminho ou iteravel de linhas; devolve linhas sem CRLF."""
    if isinstance(origem, str):
        with open(origem, encoding=CODIFICACAO, errors="replace", newline="") as f:
            for raw in f:
                yield raw.strip()
    else:
        for raw in origem:
            yield raw.strip()


# ---------------------------------------------------------------- Espiao

def campos(corpo):
    out = {}
    for parte in corpo.split("|"):
        if ":" in parte:
            k, v = parte.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def ler_linha_espiao(linha):
    m = _LINHA_ESPIAO.match(linha.strip())
    if not m:
        return None
    hora = m.group(1)
    return Evento(hora, segundos(hora), m.group(2), campos(m.group(3)), linha.strip())


def ler_espiao(origem):
    for linha in _linhas(origem):
        ev = ler_linha_espiao(linha)
        if ev is not None:
            yield ev


# ---------------------------------------------------------------- Teclas

def _modo(sequencia):
    teclas = {x[1] for x in sequencia}
    intervalos = [b[0] - a[0] for a, b in zip(sequencia, sequencia[1:])]
    rapido = bool(intervalos) and statistics.median(intervalos) < INTERVALO_SCANNER
    if teclas <= TECLAS_NUMERICO:
        return "manual"
    if teclas <= TECLAS_SCANNER and rapido:
        return "scanner"
    if len(sequencia) <= 6 and not rapido:
        return "manual"
    return "outro"


def ler_teclas(origem):
    """Lista de Entrada para cada codigo fechado com CDP e cada item do menu.

    Digitos acumulam desde a ultima acao diferente de NUM. NUM com R que nao e
    um digito so (campo de senha mascarado) descarta a sequencia: nao se tenta
    decodificar.
    """
    entradas, seq = [], []
    for linha in _linhas(origem):
        m = _LINHA_TECLA.match(linha)
        if not m:
            continue
        t, k, a, r = segundos(m.group(1)), m.group(2), m.group(3), m.group(4)
        if a == "NUM":
            if len(r) == 1 and r.isdigit():
                seq.append((t, k, r))
            else:
                seq = []
            continue
        if a == "CDP" and seq:
            entradas.append(Entrada(t, sem_zeros("".join(x[2] for x in seq)), _modo(seq)))
        elif k == "MENU" and a == "VIT":
            entradas.append(Entrada(t, sem_zeros(r), "menu"))
        seq = []
    return entradas


class Casador(object):
    """Casa VIT com a entrada do Teclas de mesmo codigo, cada entrada usada uma vez."""

    def __init__(self, entradas):
        self.entradas = entradas
        self.usado = [False] * len(entradas)
        self.por_codigo = collections.defaultdict(list)
        for i, e in enumerate(entradas):
            self.por_codigo[e.codigo].append(i)

    def modo(self, t, codigo, desc2=""):
        candidatos = self.por_codigo.get(codigo, []) + (self.por_codigo.get(desc2, []) if desc2 else [])
        for i in candidatos:
            if not self.usado[i] and abs(self.entradas[i].t - t) <= JANELA_CASAMENTO:
                self.usado[i] = True
                return self.entradas[i].modo
        return "sem_tecla"


# ---------------------------------------------------------------- dia

class Dia(object):
    """Um dia de uma estacao: eventos do Espiao + itens classificados."""

    def __init__(self, data, estacao, eventos, itens, tem_teclas):
        self.data, self.estacao = data, estacao
        self.eventos, self.itens, self.tem_teclas = eventos, itens, tem_teclas


def ler_dia(espiao, teclas=None, data=None, estacao=None):
    """Le um dia. `teclas` ausente -> todos os itens saem como 'sem_tecla'.

    Cupom aberto = depois de ABRECUPOM e antes de FECHACUPOM (CCV nao fecha:
    e assim que a analise de referencia conta).
    """
    casador = Casador(ler_teclas(teclas) if teclas else [])
    eventos, itens = [], []
    cupom, operador = None, "?"
    for ev in ler_espiao(espiao):
        eventos.append(ev)
        if ev.tipo == "ABRECUPOM":
            cupom, operador = ev.get("Cod") or None, ev.get("Descricao", "?") or "?"
        elif ev.tipo == "VIT" and cupom:
            cod, d2 = sem_zeros(ev.get("Cod")), sem_zeros(ev.get("Desc2"))
            itens.append(Item(
                hora=ev.hora, t=ev.t, cupom=cupom, operador=operador, codigo=cod, desc2=d2,
                descricao=ev.get("Descricao"), quant=ev.get("Quant"), valor=valor(ev.get("VlTotal")),
                modo=casador.modo(ev.t, cod, d2)))
        elif ev.tipo == "FECHACUPOM":
            cupom = None
    return Dia(data, estacao, eventos, itens, bool(teclas))


def dias_da_pasta(pasta, estacao=1, exigir_teclas=True):
    """Gera Dia para cada Espiao da estacao, em ordem de data.

    exigir_teclas=True pula o dia sem Teclas (como a analise de referencia).
    """
    achados = []
    for nome in os.listdir(pasta):
        info = info_arquivo(nome)
        if info and info[0] == "Espiao" and info[2] == estacao:
            achados.append((info[1], nome))
    for data, nome in sorted(achados):
        tec = os.path.join(pasta, "Teclas" + nome[6:])
        if not os.path.exists(tec):
            if exigir_teclas:
                continue
            tec = None
        yield ler_dia(os.path.join(pasta, nome), tec, data=data, estacao=estacao)


# ---------------------------------------------------------------- numeros

REFEITO_EM = 30 * 60      # CCV refeito = FECHACUPOM de mesmo valor em ate 30 min
BASE_MIN_VENDAS = 20      # "normalmente bipado": >= 20 vendas no periodo...
BASE_MAX_DIGITADO = 0.10  # ... e menos de 10% digitadas/menu


def ccv_refeitos(eventos):
    """[(evento CCV, refeito: bool)] -- refeito se houve FECHACUPOM de mesmo valor depois, em ate 30 min."""
    fechas = [(e.t, valor(e.get("VlTotal"))) for e in eventos if e.tipo == "FECHACUPOM"]
    out = []
    for e in eventos:
        if e.tipo != "CCV":
            continue
        v = valor(e.get("VlTotal"))
        out.append((e, any(e.t < t <= e.t + REFEITO_EM and vf == v for t, vf in fechas)))
    return out


def numeros(dias):
    """Os numeros de referencia (secao 5 do briefing) sobre uma sequencia de Dia."""
    n = collections.Counter()
    soma = collections.defaultdict(Decimal)
    por_produto = collections.defaultdict(collections.Counter)  # codigo -> modo -> vendas
    digitados = []  # (codigo, valor) dos itens manual/menu
    for dia in dias:
        n["dias"] += 1
        for ev in dia.eventos:
            tipo = ev.tipo
            if tipo == "ABRECUPOM":
                n["cupons"] += 1
            elif tipo == "CIT":
                n["cit"] += 1
                soma["cit"] += valor(ev.get("VlTotal"))
            elif tipo in ("CCV", "CCG"):
                n["cancela_cupom"] += 1
                soma["cancela_cupom"] += valor(ev.get("VlTotal"))
            elif tipo == "DIT":
                n["dit"] += 1
            elif tipo == "ITEMSEMCAD":
                n["itemsemcad"] += 1
            elif tipo == "SGR":
                n["sgr"] += 1
        for ev, refeito in ccv_refeitos(dia.eventos):
            chave = "ccv_refeito" if refeito else "ccv_nao_refeito"
            n[chave] += 1
            soma[chave] += valor(ev.get("VlTotal"))
        for it in dia.itens:
            n["itens"] += 1
            n["item_" + it.modo] += 1
            soma["itens"] += it.valor
            por_produto[it.codigo][it.modo] += 1
            if it.modo in ("manual", "menu"):
                digitados.append((it.codigo, it.valor))

    bipados = set()
    for cod, modos in por_produto.items():
        total = sum(modos.values())
        if total >= BASE_MIN_VENDAS and (modos["manual"] + modos["menu"]) < BASE_MAX_DIGITADO * total:
            bipados.add(cod)
    fora = [v for cod, v in digitados if cod in bipados]
    n["digitado_fora_padrao"] = len(fora)
    soma["digitado_fora_padrao"] = sum(fora, Decimal(0))

    out = dict(n)
    out.update({"valor_" + k: v.quantize(Decimal("0.01")) for k, v in soma.items()})
    itens = n["itens"] or 1
    out["cit_por_mil"] = round(1000.0 * n["cit"] / itens, 2)
    out["digitado_fora_padrao_por_mil"] = round(1000.0 * n["digitado_fora_padrao"] / itens, 2)
    return out
