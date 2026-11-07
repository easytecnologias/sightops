"""Saude do sistema para o Painel do Dono.

Fotografia do que a API consegue ver de dentro do container. /proc e global
(carga, memoria, swap e discos sao da maquina, nao do container). Cada leitura
que falha vem marcada como indisponivel: valor faltando nunca vira "tudo bem".
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core import metricas_http

logger = logging.getLogger("app.saude")

INTERVALO_S = 0.5
_RE_DISCO = re.compile(r"^(sd[a-z]+|vd[a-z]+|nvme\d+n\d+)$")
# Nome no docker-compose e porta interna. Se o nome nao resolver a linha acusa.
SERVICOS: Tuple[Tuple[str, str, int], ...] = (
    ("Banco do SightOps", "sightops-v3-postgres", 5432),
    ("Banco do Zabbix", "zabbix-v3-postgres", 5432),
    ("Zabbix", "zabbix-v3-server", 10051),
    ("Zabbix web", "zabbix-v3-web", 8080),
    ("Vídeo (go2rtc)", "sightops-v3-go2rtc", 1984),
    ("Nginx", "sightops-v3-nginx", 80),
)


def _ler(caminho: str) -> str:
    return Path(caminho).read_text(encoding="ascii", errors="replace")


def _memoria(texto: str) -> Dict[str, Any]:
    valores = {}
    for linha in texto.splitlines():
        nome, _, resto = linha.partition(":")
        partes = resto.split()
        if partes:
            valores[nome] = int(partes[0]) * 1024
    total = valores.get("MemTotal", 0)
    disponivel = valores.get("MemAvailable", 0)
    swap_total = valores.get("SwapTotal", 0)
    swap_usado = swap_total - valores.get("SwapFree", 0)
    return {
        "total": total,
        "disponivel": disponivel,
        "disponivel_pct": round(100 * disponivel / total, 1) if total else None,
        "swap_total": swap_total,
        "swap_usado": swap_usado,
        "swap_pct": round(100 * swap_usado / swap_total, 1) if swap_total else 0.0,
    }


def _contadores_disco(texto: str) -> Dict[str, Tuple[int, int, int, int, int]]:
    discos = {}
    for linha in texto.splitlines():
        c = linha.split()
        if len(c) >= 13 and _RE_DISCO.match(c[2]):
            # leituras, ms lendo, escritas, ms escrevendo, ms ocupado
            discos[c[2]] = (int(c[3]), int(c[6]), int(c[7]), int(c[10]), int(c[12]))
    return discos


def _taxa_discos(antes: Dict[str, Any], depois: Dict[str, Any], segundos: float) -> List[Dict[str, Any]]:
    linhas = []
    for nome in sorted(depois):
        if nome not in antes:
            continue
        leituras, ms_l, escritas, ms_e, ocupado = (b - a for a, b in zip(antes[nome], depois[nome]))
        linhas.append({
            "nome": nome,
            "uso_pct": round(min(100.0, ocupado / (segundos * 10)), 1),
            "leituras_s": round(leituras / segundos, 1),
            "escritas_s": round(escritas / segundos, 1),
            "espera_leitura_ms": round(ms_l / leituras, 1) if leituras else 0.0,
            "espera_escrita_ms": round(ms_e / escritas, 1) if escritas else 0.0,
        })
    return linhas


def _paginas_swap(texto: str) -> int:
    for linha in texto.splitlines():
        if linha.startswith("pswpin "):
            return int(linha.split()[1])
    return 0


def _pressao_disco(texto: str) -> Optional[float]:
    for linha in texto.splitlines():
        if linha.startswith("full "):
            return float(linha.split("avg60=")[1].split()[0])
    return None


def _maquina() -> Dict[str, Any]:
    nucleos = os.cpu_count() or 1
    carga = [float(v) for v in _ler("/proc/loadavg").split()[:3]]
    antes = _contadores_disco(_ler("/proc/diskstats"))
    swap_antes = _paginas_swap(_ler("/proc/vmstat"))
    inicio = time.monotonic()
    time.sleep(INTERVALO_S)
    segundos = time.monotonic() - inicio
    depois = _contadores_disco(_ler("/proc/diskstats"))
    swap_depois = _paginas_swap(_ler("/proc/vmstat"))
    return {
        "nucleos": nucleos,
        "carga": carga,
        "memoria": _memoria(_ler("/proc/meminfo")),
        "swap_in_s": round((swap_depois - swap_antes) / segundos, 1),
        "discos": _taxa_discos(antes, depois, segundos),
        "ativa_desde_s": int(float(_ler("/proc/uptime").split()[0])),
        "espera_disco_pct": _pressao_disco(_ler("/proc/pressure/io")),
    }


def _espacos() -> List[Dict[str, Any]]:
    from app.services.db_store import DATA_DIR

    saida = []
    vistos = set()
    for nome, caminho in (("Sistema", "/"), ("Dados dos clientes", str(DATA_DIR))):
        uso = shutil.disk_usage(caminho)
        # Hoje os dois moram no mesmo disco: a segunda linha so repetiria o numero.
        if (uso.total, uso.used) in vistos:
            continue
        vistos.add((uso.total, uso.used))
        saida.append({"nome": nome, "total": uso.total, "usado": uso.used,
                      "usado_pct": round(100 * uso.used / uso.total, 1)})
    return saida


def _banco() -> Dict[str, Any]:
    from app.services import db_store

    if db_store._db_backend() != "postgres":
        return {"ok": True, "tipo": "sqlite"}
    inicio = time.perf_counter()
    with db_store._conn() as c:
        linha = c.execute(
            "SELECT pg_database_size(current_database()) AS tamanho,"
            " (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()) AS conexoes,"
            " (SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            "   AND state <> 'idle' AND pid <> pg_backend_pid()) AS ativas,"
            " current_setting('max_connections')::int AS limite,"
            " COALESCE((SELECT EXTRACT(EPOCH FROM max(now() - query_start)) FROM pg_stat_activity"
            "   WHERE datname = current_database() AND state = 'active'"
            "   AND pid <> pg_backend_pid()), 0) AS consulta_mais_longa_s"
        ).fetchone()
    return {
        "ok": True,
        "tipo": "postgres",
        "tamanho": int(linha["tamanho"]),
        "conexoes": int(linha["conexoes"]),
        "ativas": int(linha["ativas"]),
        "limite": int(linha["limite"]),
        # query_start pode vir depois do now() da consulta: nunca mostrar negativo.
        "consulta_mais_longa_s": max(0.0, round(float(linha["consulta_mais_longa_s"]), 1)),
        "resposta_ms": round((time.perf_counter() - inicio) * 1000, 1),
    }


def _servico(nome: str, host: str, porta: int) -> Dict[str, Any]:
    inicio = time.perf_counter()
    try:
        with socket.create_connection((host, porta), timeout=2):
            return {"nome": nome, "ok": True, "ms": round((time.perf_counter() - inicio) * 1000, 1)}
    except OSError as exc:
        return {"nome": nome, "ok": False, "erro": exc.__class__.__name__}


def _tentar(funcao: Any) -> Any:
    try:
        return funcao()
    except Exception as exc:
        logger.warning("saude: %s falhou: %s", getattr(funcao, "__name__", funcao), exc)
        return {"ok": False, "erro": str(exc)[:200]}


def avaliar(foto: Dict[str, Any]) -> Dict[str, Any]:
    """Situacao geral. Quem nao pode ser lido conta como problema, nao como ok."""
    criticos: List[str] = []
    atencao: List[str] = []

    maquina = foto.get("maquina") or {}
    if maquina.get("ok") is False:
        criticos.append("Não consegui ler os dados da máquina")
    else:
        nucleos = maquina.get("nucleos") or 1
        carga = (maquina.get("carga") or [0])[0]
        if carga >= nucleos * 2:
            criticos.append(f"Carga {carga:.1f} em {nucleos} núcleos")
        elif carga >= nucleos:
            atencao.append(f"Carga {carga:.1f} em {nucleos} núcleos")

        memoria = maquina.get("memoria") or {}
        livre = memoria.get("disponivel_pct")
        if livre is not None and livre < 10:
            criticos.append(f"Só {livre:.0f}% de memória disponível")
        elif livre is not None and livre < 20:
            atencao.append(f"Só {livre:.0f}% de memória disponível")
        if (memoria.get("swap_pct") or 0) >= 50:
            atencao.append(f"Swap em {memoria['swap_pct']:.0f}%")
        if (maquina.get("swap_in_s") or 0) >= 100:
            atencao.append("Máquina lendo muito do swap")

        espera = maquina.get("espera_disco_pct")
        if espera is not None and espera >= 30:
            criticos.append(f"Sistema parado esperando disco {espera:.0f}% do tempo")
        elif espera is not None and espera >= 15:
            atencao.append(f"Sistema parado esperando disco {espera:.0f}% do tempo")
        for disco in maquina.get("discos") or []:
            if disco["uso_pct"] >= 80:
                atencao.append(f"Disco {disco['nome']} em {disco['uso_pct']:.0f}% de uso")

    espacos = foto.get("espacos")
    if isinstance(espacos, dict):
        atencao.append("Não consegui ler o espaço em disco")
    else:
        for espaco in espacos or []:
            if espaco["usado_pct"] >= 90:
                criticos.append(f"{espaco['nome']}: {espaco['usado_pct']:.0f}% do disco cheio")
            elif espaco["usado_pct"] >= 80:
                atencao.append(f"{espaco['nome']}: {espaco['usado_pct']:.0f}% do disco cheio")

    banco = foto.get("banco") or {}
    if not banco.get("ok"):
        criticos.append("Banco do SightOps sem resposta")
    elif banco.get("limite") and banco["conexoes"] >= banco["limite"] * 0.8:
        atencao.append(f"Banco com {banco['conexoes']} de {banco['limite']} conexões")
    if (banco.get("consulta_mais_longa_s") or 0) >= 30:
        atencao.append(f"Consulta rodando há {banco['consulta_mais_longa_s']:.0f} s")

    for servico in foto.get("servicos") or []:
        if not servico.get("ok"):
            criticos.append(f"{servico['nome']} sem resposta")

    http = foto.get("http") or {}
    requisicoes = http.get("requisicoes") or 0
    if requisicoes >= 20:
        taxa = 100 * (http.get("erros_5xx") or 0) / requisicoes
        if taxa >= 5:
            criticos.append(f"{taxa:.1f}% das requisições com erro")
        elif taxa >= 1:
            atencao.append(f"{taxa:.1f}% das requisições com erro")
        p95 = http.get("p95_ms") or 0
        if p95 >= 5000:
            criticos.append(f"Respostas lentas: 95% em até {p95 / 1000:.1f} s")
        elif p95 >= 2500:
            atencao.append(f"Respostas lentas: 95% em até {p95 / 1000:.1f} s")

    nivel = "critico" if criticos else ("atencao" if atencao else "ok")
    return {"nivel": nivel, "motivos": criticos + atencao}


def fotografia(janela_min: int = 60) -> Dict[str, Any]:
    foto: Dict[str, Any] = {
        "gerado_em": int(time.time()),
        "maquina": _tentar(_maquina),
        "espacos": _tentar(_espacos),
        "banco": _tentar(_banco),
        "servicos": [_servico(*s) for s in SERVICOS],
        "http": metricas_http.resumo(janela_min),
    }
    foto["situacao"] = avaliar(foto)
    return foto
