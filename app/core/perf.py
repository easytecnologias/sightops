from __future__ import annotations

import time
from contextlib import contextmanager
import logging

logger = logging.getLogger("cam-snapshot")

@contextmanager
def perf_step(name: str):
    """Medidor simples de tempo (compatível com o legado)."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000.0
        logger.debug(f"[perf] {name}: {dt:.1f}ms")
