"""Speed seguir o alarme: de um ponto da imagem termica para a posicao da speed.

So calculo, sem rede. Na calibracao o usuario marca 4 pontos: onde o marco esta
na imagem termica (x, y de 0 a 1) e a posicao da speed olhando para ele
(azimute e elevacao em decimos de grau, como a camera informa).

Com 4 pares sai uma homografia, a conta que leva um plano ao outro. Serve bem
para o chao da usina, e a pontaria e aproximada: o mapa nao sabe a altura do
terreno, por isso a calibracao guarda um zoom aberto o bastante para a pessoa
caber na imagem mesmo com erro.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

GIRO = 3600     # decimos de grau


def _resolver(m: List[List[float]]) -> List[float]:
    n = len(m)
    for col in range(n):
        pivo = max(range(col, n), key=lambda i: abs(m[i][col]))
        if abs(m[pivo][col]) < 1e-9:
            raise ValueError("Os 4 pontos não podem ficar em linha: espalhe pela imagem.")
        m[col], m[pivo] = m[pivo], m[col]
        for i in range(n):
            if i != col:
                k = m[i][col] / m[col][col]
                for j in range(col, n + 1):
                    m[i][j] -= k * m[col][j]
    return [m[i][n] / m[i][i] for i in range(n)]


def _desdobrar(azimutes: Sequence[float]) -> List[float]:
    """Azimute da volta: 3590 e 10 estao a 2 graus, nao a 358."""
    base = azimutes[0]
    return [base + ((a - base + GIRO / 2) % GIRO) - GIRO / 2 for a in azimutes]


def _area(p: Sequence[Dict[str, Any]]) -> float:
    pts = sorted(((float(q["x"]), float(q["y"])) for q in p))
    # Maior triangulo entre os pontos: quadrilatero espremido nao calibra.
    maior = 0.0
    for i in range(4):
        for j in range(i + 1, 4):
            for k in range(j + 1, 4):
                (a, b), (c, d), (e, f) = pts[i], pts[j], pts[k]
                maior = max(maior, abs((c - a) * (f - b) - (e - a) * (d - b)) / 2)
    return maior


def validar(pontos: Any) -> List[Dict[str, float]]:
    if not isinstance(pontos, list) or len(pontos) != 4:
        raise ValueError("A calibração precisa de 4 pontos.")
    saida = []
    for p in pontos:
        try:
            q = {"x": float(p["x"]), "y": float(p["y"]), "az": float(p["az"]), "el": float(p["el"])}
        except (KeyError, TypeError, ValueError):
            raise ValueError("Ponto de calibração inválido.")
        if not (0 <= q["x"] <= 1 and 0 <= q["y"] <= 1 and 0 <= q["az"] <= GIRO and -900 <= q["el"] <= 2700):
            raise ValueError("Ponto de calibração fora da faixa.")
        saida.append(q)
    if _area(saida) < 0.02:
        raise ValueError("Os 4 pontos estão muito juntos: espalhe pela imagem.")
    _matrizes(saida)
    return saida


def _matrizes(p: Sequence[Dict[str, float]]) -> Tuple[List[float], List[float]]:
    az = _desdobrar([q["az"] for q in p])
    linhas: List[List[float]] = []
    for q, a in zip(p, az):
        x, y = q["x"], q["y"]
        # a = (h0 x + h1 y + h2) / (h6 x + h7 y + 1), mesma conta para a elevacao
        linhas.append([x, y, 1, 0, 0, 0, -x * a, -y * a, a])
    for q in p:
        x, y, e = q["x"], q["y"], q["el"]
        linhas.append([0, 0, 0, x, y, 1, -x * e, -y * e, e])
    h = _resolver(linhas)
    return h, az


def apontar(pontos: Sequence[Dict[str, float]], x: float, y: float) -> Tuple[int, int]:
    """(azimute, elevacao) para olhar o ponto (x, y) da imagem termica."""
    h, _ = _matrizes(pontos)
    d = h[6] * x + h[7] * y + 1
    if abs(d) < 1e-6:
        raise ValueError("Ponto fora da área calibrada.")
    az = (h[0] * x + h[1] * y + h[2]) / d
    el = (h[3] * x + h[4] * y + h[5]) / d
    return int(round(az)) % GIRO, max(-900, min(2700, int(round(el))))
