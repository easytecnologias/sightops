"""Deteccao de pessoa pelo CALOR numa camera termica radiometrica (HikMicro/Hikvision).

So calculo, sem rede: recebe a matriz de temperatura que a camera manda
(`/ISAPI/Thermal/channels/2/thermometry/jpegPicWithAppendData`) e devolve as
manchas com temperatura de corpo que destoam do fundo.

Por que nao "temperatura acima de X" (a regra que a propria camera oferece):
numa usina solar o chao ao sol passa de 55 °C e a pessoa aparece com 30-36 °C,
ou seja, MAIS FRIA que o fundo. A noite inverte. O que nao muda e:
  1. a mancha tem temperatura de corpo (faixa configuravel);
  2. ela destoa do fundo aprendido daquele ponto da imagem (para mais OU para menos);
  3. tem tamanho de pessoa (minimo/maximo de pontos);
  4. destoa do que esta EM VOLTA agora: chao esfriando com sombra ou nuvem foge
     do fundo aprendido, mas fica igual ao entorno (alarmes falsos de 06/11);
  5. aparece em quadros seguidos (tira pisca de reflexo);
  6. ANDA: a marca fria que a sombra do poste deixa no chao tem tamanho e
     temperatura de pessoa, mas fica no lugar (9 alarmes falsos em 20 min, 06/11).

Medido na HM-TD2628-8/QA/BR (CAM P 03, UFV-RODOANEL, 05/11/2026 12:48):
matriz 256x192 float32 little-endian; chao 32-63 °C ao meio-dia.

Coordenadas normalizadas 0..1 com origem no CANTO SUPERIOR ESQUERDO da
imagem (como a tela desenha). A camera usa 0..1000 com origem embaixo --
quem conversa com ela converte, aqui nao.
"""
from __future__ import annotations

import json
import re
from array import array
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Ponto = Tuple[float, float]
Poligono = Sequence[Ponto]


# ------------------------------------------------------------------ quadro --
@dataclass
class Quadro:
    largura: int
    altura: int
    temps: array                      # float, largura*altura, linha a linha
    jpeg_termico: bytes = b""
    jpeg_visivel: bytes = b""
    info: Dict = field(default_factory=dict)

    def t(self, x: int, y: int) -> float:
        return self.temps[y * self.largura + x]

    def resumo(self) -> Dict[str, float]:
        ts = self.temps
        return {"min": round(min(ts), 1), "max": round(max(ts), 1), "media": round(sum(ts) / len(ts), 1)}


def _partes_multipart(corpo: bytes, content_type: str) -> List[Tuple[str, bytes]]:
    m = re.search(r'boundary="?([^";]+)"?', content_type or "", re.I)
    if not m:
        raise ValueError(f"resposta sem boundary multipart (Content-Type={content_type!r})")
    marca = b"--" + m.group(1).strip().encode("latin1")
    partes: List[Tuple[str, bytes]] = []
    for bruto in corpo.split(marca):
        if not bruto.strip(b"-\r\n"):
            continue
        cab, sep, dado = bruto.partition(b"\r\n\r\n")
        if not sep:
            continue
        cab_txt = cab.decode("latin1")
        # Usa o Content-Length da parte quando existe: o dado binario pode
        # terminar em \r\n de verdade e um rstrip comeria bytes da matriz.
        tam = re.search(r"Content-Length:\s*(\d+)", cab_txt, re.I)
        if tam:
            dado = dado[: int(tam.group(1))]
        else:
            dado = dado[:-2] if dado.endswith(b"\r\n") else dado
        tipo = re.search(r"Content-Type:\s*([^\r\n;]+)", cab_txt, re.I)
        partes.append(((tipo.group(1).strip().lower() if tipo else ""), dado))
    return partes


def ler_quadro(corpo: bytes, content_type: str) -> Quadro:
    """Monta o Quadro a partir da resposta crua do jpegPicWithAppendData.

    Levanta ValueError com a causa quando a camera nao mandou a matriz -- o
    caso tipico e a medicao de temperatura DESLIGADA (a camera responde 500
    ou um JSON de erro, sem multipart)."""
    if "multipart" not in (content_type or "").lower():
        trecho = corpo[:200].decode("utf-8", "replace")
        raise ValueError(f"a camera nao mandou a matriz de temperatura (medicao desligada?): {trecho}")
    info: Dict = {}
    jpegs: List[bytes] = []
    matriz = b""
    for tipo, dado in _partes_multipart(corpo, content_type):
        if "json" in tipo:
            info = json.loads(dado.decode("utf-8")).get("JpegPictureWithAppendData", {})
        elif "octet" in tipo:
            matriz = dado
        elif "jpeg" in tipo:
            jpegs.append(dado)
    largura = int(info.get("jpegPicWidth") or 0)
    altura = int(info.get("jpegPicHeight") or 0)
    if not largura or not altura:
        raise ValueError("cabecalho JSON sem jpegPicWidth/jpegPicHeight")
    if int(info.get("temperatureDataLength") or 4) != 4:
        raise ValueError(f"so sei ler temperatura em float32; a camera mandou {info.get('temperatureDataLength')} bytes por ponto")
    esperado = largura * altura * 4
    if len(matriz) < esperado:
        raise ValueError(f"matriz curta: {len(matriz)} bytes, esperado {esperado}")
    temps = array("f")
    temps.frombytes(matriz[:esperado])
    import sys
    if sys.byteorder != "little":
        temps.byteswap()
    # Ordem das imagens: a termica vem antes da visivel (jpegPicLen < visiblePicLen).
    termico = jpegs[0] if jpegs else b""
    visivel = jpegs[1] if len(jpegs) > 1 else b""
    return Quadro(largura, altura, temps, termico, visivel, info)


# ------------------------------------------------------------------- regra --
@dataclass
class Regra:
    """O que conta como pessoa numa camera. Os padroes sao o ponto de partida
    do piloto -- o ajuste fino vem dos quadros guardados em campo."""
    areas: List[Poligono] = field(default_factory=list)     # vazio = imagem inteira
    ignorar: List[Poligono] = field(default_factory=list)
    corpo_min: float = 25.0
    corpo_max: float = 40.0
    dif_min: float = 5.0          # |temperatura - fundo| minima, °C
    contraste_min: float = 3.0    # |temperatura - entorno agora| minima, °C
    movimento_min: float = 3.0    # pontos que a mancha precisa andar; 0 = aceita parada
    pontos_min: int = 12          # mancha menor que isso e ruido/bicho pequeno
    pontos_max: int = 4000        # maior que isso e sombra de nuvem/mudanca de cena
    quadros_seguidos: int = 2     # quantas leituras seguidas a mancha precisa aparecer
    intervalo_alertas_s: float = 60.0
    aprendizado: float = 0.05     # quanto o fundo segue a cena a cada quadro (0..1)


def _dentro(px: float, py: float, pol: Poligono) -> bool:
    dentro = False
    n = len(pol)
    j = n - 1
    for i in range(n):
        xi, yi = pol[i]
        xj, yj = pol[j]
        if (yi > py) != (yj > py):
            x_corte = (xj - xi) * (py - yi) / ((yj - yi) or 1e-12) + xi
            if px < x_corte:
                dentro = not dentro
        j = i
    return dentro


def mascara(largura: int, altura: int, regra: Regra) -> bytearray:
    """1 = ponto vigiado. Calculada uma vez por camera/regra."""
    m = bytearray(largura * altura)
    for y in range(altura):
        cy = (y + 0.5) / altura
        for x in range(largura):
            cx = (x + 0.5) / largura
            if regra.areas and not any(_dentro(cx, cy, p) for p in regra.areas):
                continue
            if any(_dentro(cx, cy, p) for p in regra.ignorar):
                continue
            m[y * largura + x] = 1
    return m


# ------------------------------------------------------------------- fundo --
class Fundo:
    """Temperatura de referencia de cada ponto, seguindo a cena devagar
    (sol subindo, nuvem, noite). Pontos dentro de uma mancha detectada NAO
    entram no aprendizado: senao a pessoa parada vira fundo em poucos quadros."""

    def __init__(self, quadro: Quadro):
        self.largura = quadro.largura
        self.altura = quadro.altura
        self.valores = array("f", quadro.temps)
        self.quadros = 1

    def atualizar(self, quadro: Quadro, alpha: float, congelar: Iterable[int] = ()) -> None:
        if quadro.largura != self.largura or quadro.altura != self.altura:
            self.__init__(quadro)
            return
        fixos = set(congelar)
        v = self.valores
        t = quadro.temps
        for i in range(len(v)):
            if i not in fixos:
                v[i] += (t[i] - v[i]) * alpha
        self.quadros += 1


# ----------------------------------------------------------------- deteccao --
@dataclass
class Mancha:
    pontos: int
    caixa: Tuple[float, float, float, float]    # x, y, largura, altura normalizados
    temp_media: float
    temp_max: float
    temp_min: float
    fundo_medio: float
    contraste: float = 0.0        # diferenca para o entorno, °C
    indices: List[int] = field(default_factory=list, repr=False)

    @property
    def dif(self) -> float:
        return round(self.temp_media - self.fundo_medio, 1)

    def como_dict(self) -> Dict:
        return {
            "pontos": self.pontos,
            "caixa": [round(v, 4) for v in self.caixa],
            "temp_media": round(self.temp_media, 1),
            "temp_max": round(self.temp_max, 1),
            "temp_min": round(self.temp_min, 1),
            "fundo_medio": round(self.fundo_medio, 1),
            "dif": self.dif,
            "contraste": round(self.contraste, 1),
        }


def _entorno(quadro: Quadro, x0: int, y0: int, x1: int, y1: int, folga: int = 2, largura: int = 4) -> Optional[float]:
    """Mediana da faixa em volta da caixa (x1, y1 inclusos). A folga deixa de
    fora a borda da propria mancha. None se quase nao houver faixa na imagem."""
    w, h = quadro.largura, quadro.altura
    fora = folga + largura
    vals = []
    for y in range(max(0, y0 - fora), min(h, y1 + fora + 1)):
        for x in range(max(0, x0 - fora), min(w, x1 + fora + 1)):
            if not (x0 - folga <= x <= x1 + folga and y0 - folga <= y <= y1 + folga):
                vals.append(quadro.t(x, y))
    if len(vals) < 8:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def detectar(quadro: Quadro, fundo: Fundo, regra: Regra, vigiado: Optional[bytearray] = None) -> List[Mancha]:
    w, h = quadro.largura, quadro.altura
    if vigiado is None:
        vigiado = mascara(w, h, regra)
    t = quadro.temps
    f = fundo.valores
    cand = bytearray(w * h)
    for i in range(w * h):
        if vigiado[i] and regra.corpo_min <= t[i] <= regra.corpo_max and abs(t[i] - f[i]) >= regra.dif_min:
            cand[i] = 1

    manchas: List[Mancha] = []
    visto = bytearray(w * h)
    for inicio in range(w * h):
        if not cand[inicio] or visto[inicio]:
            continue
        pilha = [inicio]
        visto[inicio] = 1
        idx: List[int] = []
        while pilha:
            i = pilha.pop()
            idx.append(i)
            x, y = i % w, i // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if cand[j] and not visto[j]:
                        visto[j] = 1
                        pilha.append(j)
        if not (regra.pontos_min <= len(idx) <= regra.pontos_max):
            continue
        xs = [i % w for i in idx]
        ys = [i // w for i in idx]
        vals = [t[i] for i in idx]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        media = sum(vals) / len(vals)
        volta = _entorno(quadro, x0, y0, x1, y1)
        contraste = abs(media - volta) if volta is not None else regra.contraste_min
        if contraste < regra.contraste_min:
            continue
        manchas.append(Mancha(
            pontos=len(idx),
            caixa=(x0 / w, y0 / h, (x1 - x0 + 1) / w, (y1 - y0 + 1) / h),
            temp_media=media,
            temp_max=max(vals),
            temp_min=min(vals),
            fundo_medio=sum(f[i] for i in idx) / len(idx),
            contraste=contraste,
            indices=idx,
        ))
    manchas.sort(key=lambda m: m.pontos, reverse=True)
    return manchas


JANELA_MOVIMENTO = 6     # leituras comparadas (armada le a cada 2 s: 12 s)
FORA_MIN = 0.35          # parte da mancha que precisa ter saido de onde estava
ABSORVER_LEITURAS = 30   # mancha parada ha mais que isso (1 min) entra no fundo


# ---------------------------------------------------------- pessoa simulada --
TAMANHOS_SIMULADOS = (("pequena", 3, 6), ("média", 6, 14), ("grande", 8, 20))


def simular_pessoa(quadro: Quadro, fundo: Fundo, regra: Regra, vigiado: Optional[bytearray] = None,
                   temp: float = 34.0, passo: int = 12) -> Dict:
    """Desenha uma pessoa em cada ponto da cena real e passa pelo detector.
    Responde "onde esta regra enxerga uma pessoa hoje, com este chao". A pessoa
    e uniforme e o tamanho e em pontos da matriz: mostra a logica e os pontos
    cegos, nao substitui uma pessoa de verdade andando na frente da camera."""
    w, h = quadro.largura, quadro.altura
    if vigiado is None:
        vigiado = mascara(w, h, regra)
    margem = 9
    tamanhos, cegos = [], []
    for nome, pl, pa in TAMANHOS_SIMULADOS:
        total = achou = 0
        for y0 in range(0, h - pa + 1, passo):
            for x0 in range(0, w - pl + 1, passo):
                if not vigiado[(y0 + pa // 2) * w + x0 + pl // 2]:
                    continue
                total += 1
                cx0, cy0 = max(0, x0 - margem), max(0, y0 - margem)
                cx1, cy1 = min(w, x0 + pl + margem), min(h, y0 + pa + margem)
                cw, ch = cx1 - cx0, cy1 - cy0
                # Recorte: a cena inteira levaria segundos em cada ponto.
                temps, base, masc = array("f"), array("f"), bytearray()
                for y in range(cy0, cy1):
                    a, b = y * w + cx0, y * w + cx1
                    temps.extend(quadro.temps[a:b])
                    base.extend(fundo.valores[a:b])
                    masc += vigiado[a:b]
                for y in range(y0 - cy0, y0 - cy0 + pa):
                    for x in range(x0 - cx0, x0 - cx0 + pl):
                        temps[y * cw + x] = temp
                f = Fundo(Quadro(cw, ch, base))
                caixa = ((x0 - cx0) / cw, (y0 - cy0) / ch, pl / cw, pa / ch)
                if any(_sobrepoe(m.caixa, caixa, 0.0) for m in detectar(Quadro(cw, ch, temps), f, regra, masc)):
                    achou += 1
                elif nome == "média":
                    cegos.append([round(x0 / w, 4), round(y0 / h, 4), round(passo / w, 4), round(passo / h, 4)])
        tamanhos.append({"nome": nome, "pontos": pl * pa, "posicoes": total, "detectadas": achou,
                         "pct": round(100 * achou / total) if total else 0})
    return {"temp": temp, "tamanhos": tamanhos, "cegos": cegos, "cena": quadro.resumo()}


# ----------------------------------------------------------------- vigia ---
def _sobrepoe(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], folga: float = 0.05) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + folga < bx or bx + bw + folga < ax or ay + ah + folga < by or by + bh + folga < ay)


def _centro(m: Mancha, largura: int) -> Tuple[float, float]:
    xs = [i % largura for i in m.indices]
    ys = [i // largura for i in m.indices]
    return sum(xs) / len(xs), sum(ys) / len(ys)


@dataclass
class _Rastro:
    """Uma mancha acompanhada entre leituras."""
    caixa: Tuple[float, float, float, float]
    n: int
    passado: List[Tuple[float, float, set]]     # centro e pontos das ultimas leituras
    andou: bool = False


@dataclass
class Disparo:
    mancha: Mancha
    quadros: int


def _andou(m: Mancha, largura: int, passado: List[Tuple[float, float, set]], minimo: float) -> bool:
    """A borda de uma marca parada tremula e o centro oscila, mas ela fica dentro
    do lugar que ja ocupou. Quem anda sai dele. Pede 3 leituras: entre 2, um
    pedaco da borda sozinho ja parece ter pulado."""
    if minimo <= 0:
        return True
    if len(passado) < 2:
        return False
    # So a metade mais antiga da janela: quem vem de frente anda pouco por leitura
    # e so se descola do comeco do caminho, nao da leitura anterior.
    velhos = passado[:max(1, len(passado) // 2)]
    ocupado = set().union(*(p[2] for p in velhos))
    fora = sum(1 for i in m.indices if i not in ocupado) / len(m.indices)
    cx, cy = _centro(m, largura)
    return fora >= FORA_MIN and ((cx - velhos[0][0]) ** 2 + (cy - velhos[0][1]) ** 2) ** 0.5 >= minimo


class Vigia:
    """Estado de UMA camera entre leituras: fundo aprendido, manchas que
    estao aparecendo e o ultimo alerta (para respeitar o intervalo)."""

    def __init__(self, regra: Regra):
        self.regra = regra
        self.fundo: Optional[Fundo] = None
        self._vigiado: Optional[bytearray] = None
        self._rastros: List[_Rastro] = []
        self.ultimo_alerta: float = -1e18
        self.ultimo_quadro: Optional[Quadro] = None

    def processar(self, quadro: Quadro, agora: float) -> Tuple[List[Mancha], Optional[Disparo]]:
        """Devolve (manchas deste quadro, disparo ou None). O primeiro quadro
        so ensina o fundo e nunca dispara."""
        self.ultimo_quadro = quadro
        if self.fundo is None or self.fundo.largura != quadro.largura or self.fundo.altura != quadro.altura:
            self.fundo = Fundo(quadro)
            self._vigiado = mascara(quadro.largura, quadro.altura, self.regra)
            self._rastros = []
            return [], None

        manchas = detectar(quadro, self.fundo, self.regra, self._vigiado)

        novos: List[_Rastro] = []
        melhor: Optional[Disparo] = None
        congelar: List[int] = []
        for m in manchas:
            # O rastro de quem esta em cima: duas manchas vizinhas nao trocam de historia.
            pontos = set(m.indices)
            antes = max((r for r in self._rastros if _sobrepoe(r.caixa, m.caixa)),
                        key=lambda r: (len(pontos & r.passado[-1][2]), r.n), default=None)
            passado = antes.passado if antes else []
            n = (antes.n if antes else 0) + 1
            andou = bool(antes and antes.andou) or _andou(m, quadro.largura, passado, self.regra.movimento_min)
            cx, cy = _centro(m, quadro.largura)
            novos.append(_Rastro(m.caixa, n, (passado + [(cx, cy, pontos)])[-JANELA_MOVIMENTO:], andou))
            if n <= ABSORVER_LEITURAS or andou:
                congelar.extend(m.indices)
            if n >= self.regra.quadros_seguidos and andou and (melhor is None or m.pontos > melhor.mancha.pontos):
                melhor = Disparo(m, n)
        self._rastros = novos

        self.fundo.atualizar(quadro, self.regra.aprendizado, congelar)

        if melhor and agora - self.ultimo_alerta >= self.regra.intervalo_alertas_s:
            self.ultimo_alerta = agora
            return manchas, melhor
        return manchas, None
