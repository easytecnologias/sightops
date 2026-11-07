"""Tempo de resposta por rota, em memoria, para a tela Saude do sistema.

Guarda agregados e nao requisicoes: um quadro por minuto (totais) e um por
10 minutos (por rota), 24 h no maximo. Com ~20 mil requisicoes por hora e ~100
rotas ativas fica em poucos MB -- o servidor tem pouca memoria.

Nao ha dado de cliente aqui: a rota e o molde (`/api/cameras/{id}`), nunca o
caminho real, e a tela e so do dono da plataforma. Zera quando a API reinicia.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

LENTA_MS = 1000
MINUTOS_GUARDADOS = 24 * 60
QUADROS_ROTA = 24 * 6
SEGUNDOS_QUADRO_ROTA = 600
MAX_ROTAS_POR_QUADRO = 300
ROTA_OUTRAS = "(outras rotas)"
SEM_ROTA = "(sem rota)"
# Limite superior de cada faixa em ms; a ultima recebe tudo o que passar de 30 s.
FAIXAS_MS: Tuple[float, ...] = (50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, float("inf"))

_trava = threading.Lock()
_minutos: "OrderedDict[int, List[Any]]" = OrderedDict()
_quadros: "OrderedDict[int, Dict[str, List[Any]]]" = OrderedDict()
_erros: Deque[Dict[str, Any]] = deque(maxlen=50)
_inicio = time.time()


def _novo() -> List[Any]:
    # n, soma_ms, max_ms, erros_5xx, lentas, faixas
    return [0, 0.0, 0.0, 0, 0, [0] * len(FAIXAS_MS)]


def _somar(alvo: List[Any], status: int, ms: float) -> None:
    alvo[0] += 1
    alvo[1] += ms
    alvo[2] = max(alvo[2], ms)
    alvo[3] += 1 if status >= 500 else 0
    alvo[4] += 1 if ms >= LENTA_MS else 0
    for i, limite in enumerate(FAIXAS_MS):
        if ms <= limite:
            alvo[5][i] += 1
            break


def _juntar(alvo: List[Any], outro: List[Any]) -> None:
    alvo[0] += outro[0]
    alvo[1] += outro[1]
    alvo[2] = max(alvo[2], outro[2])
    alvo[3] += outro[3]
    alvo[4] += outro[4]
    alvo[5] = [a + b for a, b in zip(alvo[5], outro[5])]


def _percentil(faixas: List[int], fracao: float) -> Optional[float]:
    """Limite da faixa onde cai o percentil. Sem contagem, None (nao 0)."""
    total = sum(faixas)
    if not total:
        return None
    alvo = total * fracao
    acumulado = 0
    for limite, qtd in zip(FAIXAS_MS, faixas):
        acumulado += qtd
        if acumulado >= alvo:
            return FAIXAS_MS[-2] if limite == float("inf") else limite
    return FAIXAS_MS[-2]


def nome_da_rota(escopo: Dict[str, Any]) -> str:
    """Molde da rota. Sem rota casada (404) nao ha molde, e o caminho nunca entra
    no lugar: IP de equipamento, nome digitado na URL e token do agente chegam
    aqui, inclusive sem login."""
    return getattr(escopo.get("route"), "path", "") or SEM_ROTA


def registrar(metodo: str, rota: str, status: int, ms: float, agora: Optional[float] = None) -> None:
    momento = time.time() if agora is None else agora
    minuto = int(momento // 60)
    quadro = int(momento // SEGUNDOS_QUADRO_ROTA)
    chave = f"{metodo} {rota}"
    with _trava:
        linha = _minutos.get(minuto)
        if linha is None:
            linha = _minutos[minuto] = _novo()
            while len(_minutos) > MINUTOS_GUARDADOS:
                _minutos.popitem(last=False)
        _somar(linha, status, ms)

        rotas = _quadros.get(quadro)
        if rotas is None:
            rotas = _quadros[quadro] = {}
            while len(_quadros) > QUADROS_ROTA:
                _quadros.popitem(last=False)
        if chave not in rotas and len(rotas) >= MAX_ROTAS_POR_QUADRO:
            chave = ROTA_OUTRAS
        _somar(rotas.setdefault(chave, _novo()), status, ms)

        if status >= 500:
            _erros.append({"ts": int(momento), "metodo": metodo, "rota": rota,
                           "status": status, "ms": round(ms, 1)})


def _resumo_linha(a: List[Any]) -> Dict[str, Any]:
    return {
        "requisicoes": a[0],
        "media_ms": round(a[1] / a[0], 1) if a[0] else None,
        "p50_ms": _percentil(a[5], 0.50),
        "p95_ms": _percentil(a[5], 0.95),
        "max_ms": round(a[2], 1),
        "erros_5xx": a[3],
        "lentas": a[4],
    }


def resumo(janela_min: int = 60, agora: Optional[float] = None, limite_rotas: int = 40) -> Dict[str, Any]:
    momento = time.time() if agora is None else agora
    minuto_atual = int(momento // 60)
    desde_minuto = minuto_atual - janela_min + 1
    desde_quadro = int((momento - janela_min * 60) // SEGUNDOS_QUADRO_ROTA) + 1
    total = _novo()
    por_rota: Dict[str, List[Any]] = {}
    with _trava:
        for minuto, linha in _minutos.items():
            if minuto >= desde_minuto:
                _juntar(total, linha)
        for quadro, rotas in _quadros.items():
            if quadro >= desde_quadro:
                for chave, linha in rotas.items():
                    _juntar(por_rota.setdefault(chave, _novo()), linha)
        serie = []
        for minuto in range(minuto_atual - 59, minuto_atual + 1):
            linha = _minutos.get(minuto)
            serie.append({
                "ts": minuto * 60,
                "requisicoes": linha[0] if linha else 0,
                "p95_ms": _percentil(linha[5], 0.95) if linha else None,
                "erros_5xx": linha[3] if linha else 0,
            })
        erros = [e for e in _erros if e["ts"] >= momento - janela_min * 60][::-1]

    rotas = []
    for chave, linha in por_rota.items():
        metodo, _, rota = ("", "", chave) if chave == ROTA_OUTRAS else chave.partition(" ")
        rotas.append({"metodo": metodo, "rota": rota, **_resumo_linha(linha)})
    rotas.sort(key=lambda r: (r["p95_ms"] or 0, r["requisicoes"]), reverse=True)
    return {
        "janela_min": janela_min,
        "desde": int(_inicio),
        **_resumo_linha(total),
        "serie": serie,
        "rotas": rotas[:limite_rotas],
        "rotas_total": len(rotas),
        "erros": erros[:20],
    }


def zerar() -> None:
    """So para os testes."""
    with _trava:
        _minutos.clear()
        _quadros.clear()
        _erros.clear()
