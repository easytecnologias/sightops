from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import platform
import socket
import subprocess
import time
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/network", tags=["network-tools"])


def _text(value: Any) -> str:
    return str(value or "").strip()


def _split_targets(raw: Any) -> List[str]:
    if isinstance(raw, list):
        parts = [_text(item) for item in raw]
    else:
        parts = [item.strip() for item in _text(raw).replace("\n", ",").replace(";", ",").split(",")]
    return [item for item in parts if item]


def _expand_range(item: str) -> Iterable[str]:
    if "-" not in item or "/" in item:
        yield item
        return
    left, right = item.split("-", 1)
    left = left.strip()
    right = right.strip()
    try:
        start = ipaddress.ip_address(left)
        if "." in right and ":" not in right:
            end = ipaddress.ip_address(right)
        else:
            octets = left.split(".")
            octets[-1] = right
            end = ipaddress.ip_address(".".join(octets))
        if start.version != end.version or int(end) < int(start):
            yield item
            return
        for value in range(int(start), int(end) + 1):
            yield str(ipaddress.ip_address(value))
    except Exception:
        yield item


def _expand_targets(raw: Any, limit: int = 256) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for part in _split_targets(raw):
        expanded: Iterable[str]
        if "/" in part:
            try:
                expanded = (str(ip) for ip in ipaddress.ip_network(part, strict=False).hosts())
            except Exception:
                expanded = [part]
        else:
            expanded = _expand_range(part)
        for item in expanded:
            target = _text(item)
            if not target or target in seen:
                continue
            seen.add(target)
            out.append(target)
            if len(out) >= limit:
                return out
    return out


def _ports(raw: Any) -> List[int]:
    values: List[int] = []
    for part in _split_targets(raw):
        try:
            port = int(part)
            if 1 <= port <= 65535 and port not in values:
                values.append(port)
        except Exception:
            continue
    return values or [80]


async def _tcp_check(host: str, port: int, timeout: float) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        with contextlib.suppress(Exception):  # type: ignore[name-defined]
            await writer.wait_closed()
        return {"target": host, "port": port, "open": True, "rtt_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return {"target": host, "port": port, "open": False, "error": str(exc), "rtt_ms": None}


async def _tcp_check_safe(host: str, port: int, timeout: float) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {"target": host, "port": port, "open": True, "rtt_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return {"target": host, "port": port, "open": False, "error": str(exc), "rtt_ms": None}


def _run_command(args: List[str], timeout: int = 8) -> Dict[str, Any]:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "stdout": "", "stderr": ""}


async def _run_ping(targets: List[str], timeout: int, concurrency: int, fallback_ports: List[int] | None = None) -> Dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    is_windows = platform.system().lower().startswith("win")
    ports = list(fallback_ports or [])

    async def one(target: str) -> Dict[str, Any]:
        async with sem:
            args = ["ping", "-n", "2", "-w", str(timeout * 1000), target] if is_windows else ["ping", "-c", "2", "-W", str(timeout), target]
            started = time.perf_counter()
            result = await asyncio.to_thread(_run_command, args, timeout + 4)
            if result.get("ok"):
                return {
                    "target": target,
                    "online": True,
                    "method": "icmp",
                    "rtt_ms": round((time.perf_counter() - started) * 1000, 1),
                    "stdout": result.get("stdout", ""),
                    "stderr": result.get("stderr", ""),
                }
            tcp_results: List[Dict[str, Any]] = []
            for port in ports[:12]:
                tcp = await _tcp_check_safe(target, port, timeout)
                tcp_results.append(tcp)
                if tcp.get("open"):
                    return {
                        "target": target,
                        "online": True,
                        "method": "tcp-fallback",
                        "port": port,
                        "rtt_ms": tcp.get("rtt_ms"),
                        "stdout": result.get("stdout", ""),
                        "stderr": result.get("stderr", ""),
                        "error": result.get("error", ""),
                        "tcp_results": tcp_results,
                    }
            return {
                "target": target,
                "online": False,
                "method": "icmp",
                "rtt_ms": None,
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "error": result.get("error", ""),
                "tcp_results": tcp_results,
            }

    return {"items": await asyncio.gather(*(one(target) for target in targets))}


async def _run_tcp(targets: List[str], ports: List[int], timeout: int, concurrency: int) -> Dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)

    async def one(host: str, port: int) -> Dict[str, Any]:
        async with sem:
            return await _tcp_check_safe(host, port, timeout)

    checks = [one(target, port) for target in targets for port in ports]
    return {"items": await asyncio.gather(*checks)}


async def _run_http(targets: List[str], port: int, timeout: int) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
        for target in targets[:50]:
            raw = target if target.startswith(("http://", "https://")) else f"http://{target}:{port}"
            started = time.perf_counter()
            try:
                resp = await client.get(raw)
                items.append({
                    "target": target,
                    "url": str(resp.url),
                    "ok": True,
                    "status_code": resp.status_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "server": resp.headers.get("server", ""),
                    "location": resp.headers.get("location", ""),
                })
            except Exception as exc:
                items.append({"target": target, "url": raw, "ok": False, "error": str(exc)})
    return {"items": items}


def _run_dns(targets: List[str]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for target in targets[:100]:
        try:
            infos = socket.getaddrinfo(target, None)
            addrs = sorted({item[4][0] for item in infos if item and item[4]})
            items.append({"target": target, "ok": True, "addresses": addrs})
        except Exception as exc:
            items.append({"target": target, "ok": False, "error": str(exc), "addresses": []})
    return {"items": items}


def _run_traceroute(target: str, timeout: int) -> Dict[str, Any]:
    is_windows = platform.system().lower().startswith("win")
    args = ["tracert", "-d", "-h", "20", target] if is_windows else ["traceroute", "-n", "-m", "20", target]
    result = _run_command(args, max(timeout, 8) + 12)
    if not result.get("ok") and not is_windows:
        result = _run_command(["tracepath", "-n", target], max(timeout, 8) + 12)
    return {"target": target, **result}


@router.post("/tools/run")
async def api_network_tools_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload invalido")
    test = _text(payload.get("test")).lower() or "ping"
    timeout = max(1, min(int(payload.get("timeout") or 3), 20))
    concurrency = max(1, min(int(payload.get("concurrency") or 64), 128))
    limit = 1024 if test in {"ping", "tcp", "port_scan"} else 100
    targets = _expand_targets(payload.get("targets"), limit=limit)
    if not targets:
        raise HTTPException(status_code=400, detail="informe ao menos um alvo")

    if test == "ping":
        result = await _run_ping(targets, timeout, concurrency, _ports(payload.get("ports") or payload.get("port") or "80,443,554,37777,8000,8080,8291"))
    elif test in {"tcp", "port_scan"}:
        result = await _run_tcp(targets, _ports(payload.get("ports") or payload.get("port")), timeout, concurrency)
    elif test == "http":
        ports = _ports(payload.get("port") or payload.get("ports") or 80)
        result = await _run_http(targets, ports[0], timeout)
    elif test == "dns":
        result = _run_dns(targets)
    elif test == "traceroute":
        result = _run_traceroute(targets[0], timeout)
    else:
        raise HTTPException(status_code=400, detail="teste invalido")

    return {"ok": True, "test": test, "count": len(targets), "targets": targets, "result": result}
