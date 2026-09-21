from __future__ import annotations

from typing import Any, Dict, Iterable
import asyncio
import os
import socket
import subprocess
import threading
import time
import platform


PING_CACHE_TTL = int(os.getenv("PING_CACHE_TTL", "600"))  # segundos (10min)
PING_WAIT_INFLIGHT = float(os.getenv("PING_WAIT_INFLIGHT", "1.5"))  # quanto tempo esperar outro ping terminar

# Cache por chave (ip|method|timeout).
_ping_cache: dict[str, dict] = {}
_ping_lock = threading.Lock()


def _ping_cache_key(ip: str, method: str, timeout: int) -> str:
    return f"{ip}|{method}|{timeout}"


def _ping_get_cached(key: str):
    now = time.time()
    with _ping_lock:
        item = _ping_cache.get(key)
        if not item:
            return None
        ts = float(item.get("ts") or 0)
        if (now - ts) <= PING_CACHE_TTL:
            out = dict(item.get("result") or {})
            out["cached"] = True
            return out
        # expirou
        _ping_cache.pop(key, None)
        return None


def _ping_set_inflight(key: str) -> threading.Event:
    ev = threading.Event()
    with _ping_lock:
        item = _ping_cache.get(key) or {}
        item["inflight"] = ev
        _ping_cache[key] = item
    return ev


def _ping_clear_inflight(key: str, ev: threading.Event):
    with _ping_lock:
        item = _ping_cache.get(key)
        if item and item.get("inflight") is ev:
            item["inflight"] = None
            _ping_cache[key] = item


def _ping_store_result(key: str, result: dict):
    with _ping_lock:
        item = _ping_cache.get(key) or {}
        item["ts"] = time.time()
        item["result"] = dict(result or {})
        item["inflight"] = None
        _ping_cache[key] = item


def _ping_wait_if_inflight(key: str):
    with _ping_lock:
        item = _ping_cache.get(key)
        ev = item.get("inflight") if item else None
    if isinstance(ev, threading.Event):
        ev.wait(timeout=PING_WAIT_INFLIGHT)


def _normalize_ports(preferred_ports: Iterable[int] | None) -> tuple[int, ...]:
    out: list[int] = []
    for p in (preferred_ports or ()):
        try:
            pi = int(p)
        except Exception:
            continue
        if 1 <= pi <= 65535 and pi not in out:
            out.append(pi)
    return tuple(out)


def _do_ping_sync(
    target_sync: str,
    timeout_s: int,
    method_sync: str,
    preferred_ports: Iterable[int] | None = None,
) -> Dict[str, Any]:
    host = target_sync
    port = None

    # Se tiver porta explícita (ex: 45.164.52.138:81), faz TCP nessa porta
    if ":" in target_sync and target_sync.count(":") == 1:
        h, p = target_sync.split(":", 1)
        if p.isdigit():
            host, port = h, int(p)

    res: Dict[str, Any] = {
        "ip": target_sync,
        "online": False,
        "method": method_sync,
        "rtt_ms": None,
        "error": None,
    }

    def _tcp_ping(h: str, tport: int, timeout_override: float | None = None):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(float(timeout_override if timeout_override is not None else timeout_s))
        try:
            t0 = time.perf_counter()
            s.connect((h, int(tport)))
            dt = (time.perf_counter() - t0) * 1000.0
            res.update({"online": True, "method": f"tcp:{tport}", "rtt_ms": round(dt, 2), "error": None})
        except Exception as e:
            res.update({"online": False, "method": f"tcp:{tport}", "error": str(e)})
        finally:
            try:
                s.close()
            except Exception:
                pass

    def _tcp_ping_auto_ports(h: str, ports_hint: Iterable[int] | None = None) -> bool:
        # Em muitas câmeras (ex.: speed dome), 80 pode estar fechado/filtrado,
        # mas RTSP/serviço ainda responde. Isso reduz falso OFFLINE.
        ports = _normalize_ports(ports_hint) or (80, 554, 8000, 8080, 37777, 8554)
        per_try_timeout = min(max(float(timeout_s), 0.4), 1.0)
        last_err = None
        for p in ports:
            _tcp_ping(h, p, timeout_override=per_try_timeout)
            if bool(res.get("online")):
                return True
            last_err = res.get("error")
        if last_err:
            res["error"] = last_err
        return False

    # Se porta veio explícita, força TCP
    if port is not None:
        _tcp_ping(host, port)
        res.setdefault("ok", bool(res.get("online", False)))
        return res

    # Decide método
    if method_sync == "tcp":
        _tcp_ping(host, 80)
        res.setdefault("ok", bool(res.get("online", False)))
        return res

    # ICMP
    is_windows = platform.system().lower().startswith("win")
    try:
        if is_windows:
            cmd = ["ping", "-n", "1", "-w", str(int(float(timeout_s) * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(float(timeout_s))), host]

        t0 = time.perf_counter()
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        dt = (time.perf_counter() - t0) * 1000.0

        if proc.returncode == 0:
            res.update({"online": True, "method": "icmp", "rtt_ms": round(dt, 2), "error": None})
            res.setdefault("ok", True)
            return res

        # Se ICMP falhar e for auto, tenta TCP em portas comuns de câmera
        if method_sync == "auto":
            _tcp_ping_auto_ports(host, preferred_ports)
            res.setdefault("ok", bool(res.get("online", False)))
            return res

        res.update({"online": False, "method": "icmp", "error": (proc.stderr or proc.stdout).strip()})
        res.setdefault("ok", False)
        return res

    except Exception as e:
        # Se falhar ICMP e for auto, tenta TCP em portas comuns de câmera
        if method_sync == "auto":
            _tcp_ping_auto_ports(host, preferred_ports)
            res.setdefault("ok", bool(res.get("online", False)))
            return res

        res.update({"online": False, "method": "icmp", "error": str(e)})
        res.setdefault("ok", False)
        return res


async def ping(
    ip: str,
    timeout: int = 3,
    method: str = "auto",
    force: int = 0,
    preferred_ports: Iterable[int] | None = None,
) -> Dict[str, Any]:
    target = (ip or "").strip()
    method_n = (method or "auto").lower().strip()

    try:
        timeout_i = int(timeout)
    except Exception:
        timeout_i = 3
    timeout_i = max(1, min(timeout_i, 30))

    key = _ping_cache_key(target, method_n, timeout_i)

    if not force:
        cached = _ping_get_cached(key)
        if cached is not None:
            cached["ok"] = bool(cached.get("online"))
            return cached

        _ping_wait_if_inflight(key)
        cached = _ping_get_cached(key)
        if cached is not None:
            cached["ok"] = bool(cached.get("online"))
            return cached

    ev = _ping_set_inflight(key)

    try:
        result = await asyncio.to_thread(_do_ping_sync, target, timeout_i, method_n, preferred_ports)
    finally:
        _ping_clear_inflight(key, ev)
        try:
            ev.set()
        except Exception:
            pass

    _ping_store_result(key, result)
    result.setdefault("cached", False)
    result["ok"] = bool(result.get("online"))
    return result
