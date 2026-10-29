"""CM do PDV -> linhas no formato do Espiao.

Caixa sem o Espiao ligado (opcao `est_ini_cmespiao` da estacao na retaguarda)
so grava o CM: o log de depuracao do programa do caixa. As linhas
`COMANDO ==> (...)` do CM batem uma a uma com os eventos do Espiao (conferido
com o PDV1 da VITAL, que grava os dois). Este conversor le o CM linha a linha e
devolve as linhas que o Espiao teria gravado, para o resto do sistema (leitor,
processador, telas) nao precisar saber de onde veio.

O coletor manda so as linhas do CM que interessam (MARCADORES) e corta o
INSERT do item no comeco do VALUES (ver `compactar`). O coletor roda sozinho no
caixa, entao tem uma copia disso (MARCADORES_CM / linha_cm); um teste confere
que os dois filtram igual.

So stdlib e compativel com Python 3.8.
"""
from __future__ import annotations

import re

# Linhas do CM que o conversor usa. O coletor descarta o resto.
MARCADORES = (
    "COMANDO ==> (",
    "Entrada Operador:",
    "ABRE CUPOM FISCAL: COO:",
    "ENTRADA DADOS:",
    "INSERT INTO venda",
    "ProcessaTeclaSubtotal:Inicio",
    "Pagamento Venda:Valor:",
    "AcFinal:mf",
    "FD_Desconto:",
    "Desconto SubTotal:",
    "ValidaSupervisorTecla:CodAcao",
    "digo Supervisor:",   # 'Codigo' vem com acento quebrado
    "Supervisor OK:",
    "MostraMensagemItemNaoCadastrado",
)
TAM_VALUES = 320  # do VALUES do INSERT basta o comeco (tipo, cupom, ope, dados)

_HORA = re.compile(r"^(\d{2}:\d{2}:\d{2})\.\d+:(.*)$")
_PREFIXO = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+:")
_TOTAIS = re.compile(r"TOTAIS COO:\s*(\d+)\s*\(SB:\s*([-\d.]+)\s*/\s*PG:\s*([-\d.]+)\s*/\s*DC:\s*([-\d.]+)\s*/\s*AC:\s*([-\d.]+)")
_ITEM = re.compile(r"(REGISTRA|CANCELA) ITEM:\s*(\S+)\s*\(VL:\s*([-\d.]+)\s*/\s*QT:\s*([-\d.]+)\s*/\s*TT:\s*([-\d.]+)\)")
_COMANDO = re.compile(r"COMANDO ==> \(([^)]*)\)\s*PARAMETRO\(([^)]*)\)?")
_OPERADOR = re.compile(r"Entrada Operador:Cod:\s*(\S+)\s+Nome:\s*(.*?)\|?$")
_ABRE = re.compile(r"ABRE CUPOM FISCAL: COO:\s*(\d+)")
_ENTRADA = re.compile(r"ENTRADA DADOS:\s*([^|]*)")
_VALUES = re.compile(r"INSERT INTO venda.*?VALUES \((.*)$")
_PAGAMENTO = re.compile(r"Pagamento Venda:Valor:\s*([-\d.]+)\s+Finalizadora:\s*(\d+)\s*-\s*(.*?)\|?$")
_ACFINAL = re.compile(r"AcFinal:mf(\w+),\s*(\d+),\s*\w*,\s*([-\d.]+)")
_DESC_ITEM = re.compile(r"FD_Desconto:.*DESCONTO ITEM ANTERIOR\s+([-\d.,]+)")
_DESC_SBT = re.compile(r"Desconto SubTotal:Desc Subtotal:\s*([-\d.]+)")
_SUP_COD = re.compile(r"digo Supervisor:\s*(\d+)")
_SUP_OK = re.compile(r"Supervisor OK:\s*(\d+)-(.*?)\|?$")
_SEM_CAD = re.compile(r"MostraMensagemItemNaoCadastrado:\s*cod:\s*(\S+)")


def util(linha):
    """A linha do CM interessa ao conversor?"""
    return any(m in linha for m in MARCADORES)


def compactar(linha):
    """INSERT do item tem ~2,2 mil caracteres (a lista de colunas sozinha passa
    de mil). Fica 'HH:MM:SS.mmm:INSERT INTO venda VALUES (<comeco>'."""
    i = linha.find("INSERT INTO venda")
    if i < 0:
        return linha
    j = linha.find(" VALUES (", i)
    if j < 0:
        return linha
    m = _PREFIXO.match(linha)
    prefixo = m.group(0) if m else ""
    return prefixo + "INSERT INTO venda VALUES (" + linha[j + 9:j + 9 + TAM_VALUES]


def _sql_valores(texto):
    """Valores de um VALUES (...) cortado: ['VIT', 'P', ...]. Para no que nao fechou."""
    out, atual, aspas, i = [], [], False, 0
    while i < len(texto):
        ch = texto[i]
        if aspas:
            if ch == "'":
                if i + 1 < len(texto) and texto[i + 1] == "'":
                    atual.append("'")
                    i += 1
                else:
                    aspas = False
            else:
                atual.append(ch)
        elif ch == "'":
            aspas = True
        elif ch == ",":
            out.append("".join(atual).strip())
            atual = []
        elif ch == ")":
            break
        else:
            atual.append(ch)
        i += 1
    if not aspas:
        out.append("".join(atual).strip())
    return out


def _num(texto):
    """'13.00' -> '13', '0.778' -> '0.778' (como o Espiao escreve)."""
    t = str(texto or "").strip()
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t or "0"


def _dif(a, b):
    try:
        return _num("%.2f" % (float(a) - float(b)))
    except ValueError:
        return "0"


def _linha(hora, tipo, campos=()):
    """'07:04:40:ABRECUPOM | Cod: 266397 | Descricao: Fulano|' (campo None fica de fora)."""
    partes = ["%s: %s" % (k, v) for k, v in campos if v is not None]
    if not partes:
        return "%s:%s|" % (hora, tipo)
    return "%s:%s | %s|" % (hora, tipo, " | ".join(partes))


class ConversorCM(object):
    """Estado de um dia de CM. `linha(texto)` devolve as linhas de Espiao que ela gera."""

    def __init__(self):
        self.operador = ""
        self.cod_operador = ""
        self.cupom = None
        self.sb = "0"
        self.pago = 0.0
        self.item = None        # dados do ultimo INSERT de VIT, esperando o REGISTRA ITEM
        self.entrada = ""       # ultimo codigo entrado (ENTRADA DADOS)
        self.ultimo_vit = None  # (cod, desc, und) do ultimo item vendido (DESCONTO ITEM ANTERIOR)
        self.vits = {}          # cod -> (desc, und), para o cancelamento de item
        self.formas = {}        # cod da finalizadora -> nome
        self.supervisores = {}  # cod -> nome
        self.subtotal = False   # tecla de subtotal apertada, esperando o LE-SUB-TOTAL
        self.tef = None         # (cod, nome, devido): cartao/PIX esperando a aprovacao (AcFinal:mfVenda)

    def linha(self, texto):
        m = _HORA.match(texto.strip())
        if not m:
            return []
        hora, corpo = m.groups()
        try:
            return self._linha(hora, corpo)
        except (ValueError, IndexError):
            return []  # linha cortada ou estranha: nunca derruba o dia

    def _abre(self, hora, cupom):
        self.cupom, self.sb, self.pago, self.subtotal, self.tef = cupom, "0", 0.0, False, None
        op = self.operador or None
        return [_linha(hora, "VENDACF", (("Descricao", op),)),
                _linha(hora, "ABRECUPOM", (("Cod", cupom), ("Descricao", op)))]

    def _linha(self, hora, corpo):
        out = []
        tot = _TOTAIS.search(corpo)
        if tot:
            self.sb = tot.group(2)
        cmd = _COMANDO.search(corpo)
        if cmd:
            nome, param = cmd.group(1).strip(), (cmd.group(2) or "").strip()
            if nome == "REGISTRA ITEM":
                it = _ITEM.search(corpo)
                if not it or not tot:
                    return out
                cupom = tot.group(1)
                if cupom != self.cupom:  # CM comecou no meio do cupom
                    out += self._abre(hora, cupom)
                cod, vl, qt, tt = it.group(2), it.group(3), it.group(4), it.group(5)
                desc, und = "", ""
                if self.item and self.item[0].lstrip("0") == cod.lstrip("0"):
                    desc, und = self.item[1], self.item[2]
                self.item = None
                und = und or ("Kg" if "." in _num(qt) else "Un")
                d2 = self.entrada if self.entrada and self.entrada.lstrip("0") != cod.lstrip("0") else None
                self.vits[cod.lstrip("0")] = (desc, und)
                self.ultimo_vit = (cod, desc, und)
                out.append(_linha(hora, "VIT", (("Cod", cod), ("Descricao", desc), ("Quant", _num(qt)), ("Und", und),
                                                ("VlUnit", _num(vl)), ("VlTotal", _num(tt)), ("Desc2", d2))))
            elif nome == "CANCELA ITEM":
                it = _ITEM.search(corpo)
                if it:
                    cod = it.group(2)
                    desc, und = self.vits.get(cod.lstrip("0"), ("", "Un"))
                    out.append(_linha(hora, "CIT", (("Cod", cod), ("Descricao", desc), ("Quant", _num(it.group(4))),
                                                    ("Und", und), ("VlUnit", _num(it.group(3))),
                                                    ("VlTotal", _num(it.group(5))))))
            elif nome == "LE-SUB-TOTAL" and self.subtotal and tot:
                self.subtotal = False
                out.append(_linha(hora, "SBT", (("Cod", tot.group(1)), ("Descricao", self.operador or None),
                                                ("VlTotal", _num(tot.group(2))))))
            elif nome == "FECHA CUPOM FISCAL" and tot:
                total = _num(tot.group(2))  # o Espiao fecha com o subtotal (antes do desconto)
                out.append(_linha(hora, "FECHACUPOM", (("Cod", tot.group(1)), ("Descricao", self.operador or None),
                                                       ("VlTotal", total))))
                self.cupom = None
            elif nome == "CANCELA CUPOM" and tot:
                tipo = "CCV" if tot.group(1) == self.cupom else "CCG"
                out.append(_linha(hora, tipo, (("Cod", tot.group(1)), ("Descricao", self.operador or None),
                                               ("VlTotal", _num(tot.group(2))))))
                if tipo == "CCV":
                    self.cupom = None
            elif nome == "GAVETA":
                out.append(_linha(hora, "GAV"))
            elif nome == "RL-X":
                out.append(_linha(hora, "RLX"))
            elif nome == "REDUCAO Z" or nome == "RL-Z":
                out.append(_linha(hora, "RLZ"))
            elif nome == "OPERADOR" and not param:
                out.append(_linha(hora, "SOP", (("Cod", self.cod_operador or None), ("Descricao", self.operador or None))))
                self.operador, self.cod_operador = "", ""
            return out

        if "INSERT INTO venda" in corpo:
            v = _VALUES.search(corpo)
            if v:
                vals = _sql_valores(v.group(1))
                if vals and vals[0] == "VIT" and len(vals) > 7:
                    dados = vals[7].split("|")
                    if len(dados) > 2:
                        und = ("Kg" if dados[9] == "S" else "Un") if len(dados) > 9 else ""
                        self.item = (dados[1], dados[2], und)
            return out
        m = _ENTRADA.search(corpo)
        if m:
            self.entrada = m.group(1).strip()
            return [_linha(hora, "CDP", (("Cod", self.entrada),))] if self.entrada else [_linha(hora, "CDP")]
        m = _ABRE.search(corpo)
        if m:
            return self._abre(hora, m.group(1)) if m.group(1) != self.cupom else []
        m = _OPERADOR.search(corpo)
        if m:
            self.cod_operador, self.operador = m.group(1).strip(), m.group(2).strip()
            return [_linha(hora, "EOP", (("Cod", self.cod_operador), ("Descricao", self.operador)))]
        if "ProcessaTeclaSubtotal:Inicio" in corpo:
            self.subtotal = True
            return out
        m = _PAGAMENTO.search(corpo)
        if m:
            # tecla da finalizadora: so guarda o nome e quanto faltava. O pagamento
            # vale na confirmacao (AcFinal:mfVenda); cartao recusado nao chega la.
            cod, nome = m.group(2).lstrip("0") or "0", m.group(3).strip()
            self.formas[cod] = nome
            self.tef = (cod, _dif(self.sb, self.pago))
            return out
        m = _ACFINAL.search(corpo)
        if m:
            tipo, cod, valor = m.groups()
            forma = self.formas.get(cod.lstrip("0") or "0", "Dinheiro")
            if tipo == "Troco":
                return [_linha(hora, "TRC", (("Cod", cod), ("Descricao", forma.upper()), ("VlTotal", _num(valor))))]
            if tipo == "Venda":
                cod = cod.lstrip("0") or "0"
                devido = self.tef[1] if self.tef and self.tef[0] == cod else _dif(self.sb, self.pago)
                self.tef = None
                self.pago += float(valor)
                # como o Espiao grava: dinheiro = Cod 1 'DINHEIRO'; o resto (cartao,
                # PIX, POS) = Cod 99 com o nome da finalizadora como esta
                cod_fi, nome = (cod, forma.upper()) if forma.lower() == "dinheiro" else ("99", forma)
                return [_linha(hora, "FIN", (("Cod", cod_fi), ("Descricao", nome), ("VlUnit", devido),
                                             ("VlTotal", _num(valor))))]
            if tipo == "Sangria":
                return [_linha(hora, "SGR", (("Cod", self.cod_operador or None), ("Descricao", forma),
                                             ("VlTotal", _num(valor))))]
            return out
        m = _DESC_ITEM.search(corpo)
        if m and self.ultimo_vit:
            cod, desc, und = self.ultimo_vit
            return [_linha(hora, "DIT", (("Cod", cod), ("Descricao", desc), ("Und", und),
                                         ("VlUnit", _num(m.group(1).replace(",", ".")))))]
        m = _DESC_SBT.search(corpo)
        if m:
            return [_linha(hora, "DST", (("Cod", self.cupom), ("Descricao", self.operador or None),
                                         ("VlUnit", _num(m.group(1))), ("VlTotal", _num(self.sb))))]
        if "ValidaSupervisorTecla:CodAcao" in corpo:
            return [_linha(hora, "SUP")]
        m = _SUP_OK.search(corpo)
        if m:
            self.supervisores[m.group(1)] = m.group(2).strip()
            return out
        m = _SUP_COD.search(corpo)
        if m:
            cod = m.group(1)
            return [_linha(hora, "SUPERVISOR", (("Cod", cod), ("Descricao", self.supervisores.get(cod)),))]
        m = _SEM_CAD.search(corpo)
        if m:
            return [_linha(hora, "ITEMSEMCAD", (("Cod", m.group(1)),))]
        return out


def converter(linhas):
    """[(seq, texto_cm)] -> [(seq_espiao, texto_espiao)]. seq_espiao = seq*10 + k
    (uma linha do CM pode gerar ate dez eventos), em ordem."""
    cv = ConversorCM()
    out = []
    for seq, texto in linhas:
        for k, l in enumerate(cv.linha(texto)[:10]):
            out.append((seq * 10 + k, l))
    return out
