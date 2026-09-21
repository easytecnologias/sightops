from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, Iterable

from fastapi import WebSocket

from app.core.paths import DATA_DIR
from app.core.tenant_context import reset_current_tenant_slug, set_current_tenant_slug
from app.services.inventory_json import load_inventory_json
from app.services.ping_service import ping as ping_with_cache


MAINT_PING_CACHE_PATH = DATA_DIR / "maintenance_ping_cache.json"


class MaintenancePingHub:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._subs: dict[WebSocket, str] = {}
        self._lock = asyncio.Lock()
        self._status_by_ip: dict[str, dict[str, Any]] = {}
        self._port_hint_by_ip: dict[str, list[int]] = {}
        self._priority_until: dict[str, float] = {}
        self._cursor_by_tenant: dict[str, int] = {}
        self._last_inventory_by_tenant: dict[str, list[dict[str, Any]]] = {}
        self._last_inventory_reload_by_tenant: dict[str, float] = {}
        self._dirty_cache = False
        self._last_cache_save = 0.0

        self.inventory_reload_s = max(5.0, float(os.getenv("MAINT_PING_INVENTORY_RELOAD_S", "20")))
        self.tick_delay_s = max(0.2, float(os.getenv("MAINT_PING_TICK_DELAY_S", "1.0")))
        self.batch_size = max(20, min(int(os.getenv("MAINT_PING_BATCH_SIZE", "180")), 1000))
        self.concurrency = max(4, min(int(os.getenv("MAINT_PING_CONCURRENCY", "48")), 128))
        self.timeout_s = max(1, min(int(os.getenv("MAINT_PING_TIMEOUT_S", "1")), 10))
        self.priority_ttl_s = max(10, min(int(os.getenv("MAINT_PING_PRIORITY_TTL_S", "120")), 3600))

        self._load_cache()

    async def start(self) -> None:
        async with self._lock:
            if self._task and not self._task.done():
                return
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(self._run_loop(), name="maintenance-ping-hub")

    async def stop(self) -> None:
        async with self._lock:
            self._stop.set()
            task = self._task
            self._task = None
        if task:
            try:
                await task
            except Exception:
                pass
        self._save_cache(force=True)

    def _tenant(self, tenant_slug: str = "") -> str:
        return str(tenant_slug or "").strip().lower()

    def _key(self, tenant_slug: str, ip: str) -> str:
        return f"{self._tenant(tenant_slug)}|{str(ip or '').strip()}"

    def _row_ip(self, row: dict[str, Any]) -> str:
        return str(row.get("ip") or "").strip()

    async def subscribe(self, ws: WebSocket, tenant_slug: str = "") -> None:
        async with self._lock:
            self._subs[ws] = self._tenant(tenant_slug)

    async def unsubscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subs.pop(ws, None)

    def prioritize(self, ips: Iterable[str], ttl_s: int | None = None, tenant_slug: str = "") -> None:
        ttl = float(ttl_s or self.priority_ttl_s)
        until = time.time() + ttl
        tenant = self._tenant(tenant_slug)
        for ip in ips:
            ip_s = str(ip or "").strip()
            if ip_s:
                self._priority_until[self._key(tenant, ip_s)] = until

    def snapshot(self, limit: int = 0, tenant_slug: str = "") -> dict[str, Any]:
        tenant = self._tenant(tenant_slug)
        prefix = f"{tenant}|"
        rows = [dict(v) for k, v in self._status_by_ip.items() if k.startswith(prefix)]
        if limit and limit > 0:
            rows = rows[:limit]
        return {
            "type": "snapshot",
            "rows": rows,
            "summary": self.summary(tenant),
        }

    def summary(self, tenant_slug: str = "") -> dict[str, Any]:
        tenant = self._tenant(tenant_slug)
        inv = self._last_inventory_by_tenant.get(tenant) or []
        total = len(inv)
        online = 0
        for row in inv:
            ip = self._row_ip(row)
            st = self._status_by_ip.get(self._key(tenant, ip))
            if st and st.get("online") is True:
                online += 1
        return {
            "total": total,
            "online": online,
            "offline": max(0, total - online),
            "tracked": len([k for k in self._status_by_ip if k.startswith(f"{tenant}|")]),
            "subscribers": len([t for t in self._subs.values() if t == tenant]),
        }

    def _load_cache(self) -> None:
        try:
            raw = MAINT_PING_CACHE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        ports = data.get("port_hint_by_ip")
        if isinstance(ports, dict):
            for ip, items in ports.items():
                norm = self._norm_ports(items)
                if norm:
                    key = str(ip).strip()
                    if "|" not in key:
                        key = self._key("", key)
                    self._port_hint_by_ip[key] = norm
        status = data.get("status_by_ip")
        if isinstance(status, dict):
            for ip, row in status.items():
                if isinstance(row, dict):
                    key = str(ip).strip()
                    if "|" not in key:
                        key = self._key("", key)
                    self._status_by_ip[key] = dict(row)

    def _save_cache(self, force: bool = False) -> None:
        now = time.time()
        if not force and (not self._dirty_cache or (now - self._last_cache_save) < 5.0):
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": int(now),
                "port_hint_by_ip": self._port_hint_by_ip,
                "status_by_ip": self._status_by_ip,
            }
            MAINT_PING_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self._dirty_cache = False
            self._last_cache_save = now
        except Exception:
            pass

    def _norm_ports(self, values: Iterable[Any]) -> list[int]:
        out: list[int] = []
        for value in values or []:
            try:
                port = int(value)
            except Exception:
                continue
            if 1 <= port <= 65535 and port not in out:
                out.append(port)
        return out

    def _preferred_ports(self, row: dict[str, Any], tenant_slug: str = "") -> list[int]:
        ip = self._row_ip(row)
        ports = self._norm_ports(self._port_hint_by_ip.get(self._key(tenant_slug, ip), []))
        for key in ("http_port", "https_port", "rtsp_port", "server_port"):
            try:
                ports = self._merge_ports(ports, [int(row.get(key) or 0)])
            except Exception:
                continue
        ports = self._merge_ports(ports, row.get("open_ports") or [])
        if not ports:
            ports = [80]
        return ports[:8]

    def _merge_ports(self, base: Iterable[int], extra: Iterable[Any]) -> list[int]:
        out = self._norm_ports(base)
        for port in self._norm_ports(extra):
            if port not in out:
                out.append(port)
        return out

    async def _reload_inventory_if_needed(self, tenant_slug: str = "") -> None:
        tenant = self._tenant(tenant_slug)
        now = time.time()
        last_reload = self._last_inventory_reload_by_tenant.get(tenant, 0.0)
        if self._last_inventory_by_tenant.get(tenant) and (now - last_reload) < self.inventory_reload_s:
            return
        ctx_token = set_current_tenant_slug(tenant)
        try:
            rows = load_inventory_json() or []
        finally:
            reset_current_tenant_slug(ctx_token)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            ip = self._row_ip(row)
            if not ip or ip in seen:
                continue
            seen.add(ip)
            out.append(row)
        self._last_inventory_by_tenant[tenant] = out
        self._last_inventory_reload_by_tenant[tenant] = now

    def _select_batch(self, tenant_slug: str = "") -> list[dict[str, Any]]:
        tenant = self._tenant(tenant_slug)
        rows = self._last_inventory_by_tenant.get(tenant) or []
        if not rows:
            return []
        now = time.time()
        active_priority: list[dict[str, Any]] = []
        normal: list[dict[str, Any]] = []
        for row in rows:
            ip = self._row_ip(row)
            if not ip:
                continue
            until = float(self._priority_until.get(self._key(tenant, ip)) or 0)
            if until > now:
                active_priority.append(row)
            else:
                normal.append(row)

        active_priority.sort(key=lambda r: -float(self._priority_until.get(self._key(tenant, self._row_ip(r)), 0)))
        if normal:
            start = self._cursor_by_tenant.get(tenant, 0) % len(normal)
            rotated = normal[start:] + normal[:start]
            self._cursor_by_tenant[tenant] = (start + min(self.batch_size, len(rotated))) % len(normal)
        else:
            rotated = []
            self._cursor_by_tenant[tenant] = 0

        return (active_priority + rotated)[: self.batch_size]

    async def _run_one(self, row: dict[str, Any], semaphore: asyncio.Semaphore, tenant_slug: str = "") -> None:
        tenant = self._tenant(tenant_slug)
        ip = self._row_ip(row)
        if not ip:
            return
        async with semaphore:
            try:
                result = await ping_with_cache(
                    ip=ip,
                    timeout=self.timeout_s,
                    method="auto",
                    force=1,
                    preferred_ports=self._preferred_ports(row, tenant),
                )
            except Exception as exc:
                result = {
                    "ip": ip,
                    "online": False,
                    "method": "auto",
                    "rtt_ms": None,
                    "error": str(exc),
                    "ok": False,
                    "cached": False,
                }

        result["ip"] = ip
        result["ts"] = int(time.time() * 1000)
        key = self._key(tenant, ip)
        prev = self._status_by_ip.get(key)
        self._status_by_ip[key] = result
        if result.get("online") and isinstance(result.get("method"), str) and result["method"].startswith("tcp:"):
            try:
                port = int(str(result["method"]).split(":", 1)[1])
                self._port_hint_by_ip[key] = self._merge_ports([port], self._port_hint_by_ip.get(key, []))
                self._dirty_cache = True
            except Exception:
                pass
        if prev != result:
            self._dirty_cache = True
            await self._broadcast(tenant, {
                "type": "ping_update",
                "row": result,
                "summary": self.summary(tenant),
            })

    async def _broadcast(self, tenant_slug: str, payload: dict[str, Any]) -> None:
        tenant = self._tenant(tenant_slug)
        async with self._lock:
            subs = [ws for ws, sub_tenant in self._subs.items() if sub_tenant == tenant]
        if not subs:
            return
        text = json.dumps(payload, ensure_ascii=False)
        dead: list[WebSocket] = []
        results = await asyncio.gather(*[ws.send_text(text) for ws in subs], return_exceptions=True)
        for ws, res in zip(subs, results):
            if isinstance(res, Exception):
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._subs.pop(ws, None)

    async def _active_tenants(self) -> list[str]:
        async with self._lock:
            tenants = sorted({self._tenant(t) for t in self._subs.values()})
        return tenants or [""]

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                for tenant in await self._active_tenants():
                    await self._reload_inventory_if_needed(tenant)
                    batch = self._select_batch(tenant)
                    if batch:
                        semaphore = asyncio.Semaphore(self.concurrency)
                        await asyncio.gather(*[self._run_one(row, semaphore, tenant) for row in batch])
                    self._save_cache()
                await asyncio.sleep(self.tick_delay_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1.0)


maintenance_ping_hub = MaintenancePingHub()
