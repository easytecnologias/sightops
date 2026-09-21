from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.core.paths import DATA_DIR

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_VIDEO_MODEL = os.getenv("GEMINI_VIDEO_MODEL", "gemini-2.5-flash")
GEMINI_SEARCH_TIMEOUT_SEC = int(os.getenv("GEMINI_SEARCH_TIMEOUT_SEC", "60"))
GEMINI_FILE_POLL_SEC = float(os.getenv("GEMINI_FILE_POLL_SEC", "2"))
GEMINI_MAX_CALLS_PER_MINUTE = int(os.getenv("GEMINI_MAX_CALLS_PER_MINUTE", "8"))
GEMINI_MAX_CALLS_PER_HOUR = int(os.getenv("GEMINI_MAX_CALLS_PER_HOUR", "120"))

_RATE_DIR = DATA_DIR / "nvr_ai"
_REQUESTS_PATH = _RATE_DIR / "gemini_calls.json"
_COOLDOWN_PATH = _RATE_DIR / "gemini_cooldown.json"

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "timestamp_offset_sec": {"type": ["number", "null"]},
        "description": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["found", "description", "confidence"],
}

_PROMPT_TEMPLATE = (
    "Voce esta revisando um trecho curto de video de CCTV. "
    "O trecho cobre o periodo de {start} ate {end} (duracao aproximada de {duration}s), "
    "no fuso horario local da camera. "
    'Determine se o seguinte evento ou objeto aparece no video: "{query}". '
    "Responda apenas com JSON no formato pedido. "
    "Se encontrar, timestamp_offset_sec e o numero de segundos a partir do INICIO do "
    "video (nao um horario do relogio) onde o evento/objeto aparece de forma mais clara. "
    "Se nao encontrar, use found=false e timestamp_offset_sec=null. "
    "Seja conservador: so marque found=true se estiver razoavelmente confiante de que o "
    "que foi descrito realmente aparece no video. confidence vai de 0 a 1."
)


class GeminiNotConfiguredError(Exception):
    """GEMINI_API_KEY nao configurada."""


class GeminiRateLimitedError(Exception):
    """Limite local de chamadas atingido; contem quantos segundos esperar."""

    def __init__(self, wait_sec: int, reason: str) -> None:
        super().__init__(f"Limite de chamadas Gemini atingido ({reason}), aguarde {wait_sec}s.")
        self.wait_sec = wait_sec
        self.reason = reason


@dataclass
class GeminiSearchResult:
    found: bool
    description: str
    confidence: float
    timestamp_offset_sec: Optional[float] = None
    hit_at: Optional[datetime] = None
    raw: Optional[dict] = None


_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is not None:
        return _client
    if not GEMINI_API_KEY:
        raise GeminiNotConfiguredError("GEMINI_API_KEY nao configurada no ambiente.")
    from google import genai  # import tardio: evita custo de import se a feature nao for usada

    _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def cooldown_remaining_sec() -> float:
    data = _load_json(_COOLDOWN_PATH, {})
    try:
        return max(float(data.get("until", 0)) - time.time(), 0)
    except Exception:
        return 0


def _save_cooldown(wait_sec: float) -> None:
    _save_json_atomic(_COOLDOWN_PATH, {"until": time.time() + max(float(wait_sec), 1)})


def reserve_call_slot() -> None:
    """Reserva uma chamada dentro do limite local (janela deslizante em arquivo).

    Levanta GeminiRateLimitedError se o limite por minuto/hora ou o cooldown
    (definido apos um 429 da API) ainda nao tiverem liberado.
    """
    remaining = cooldown_remaining_sec()
    if remaining > 0:
        raise GeminiRateLimitedError(int(remaining) + 1, "COOLDOWN_API")

    now = time.time()
    data = _load_json(_REQUESTS_PATH, {"timestamps": []})
    timestamps = [float(v) for v in data.get("timestamps", []) if now - float(v) < 3600]

    last_minute = [v for v in timestamps if now - v < 60]
    if len(last_minute) >= GEMINI_MAX_CALLS_PER_MINUTE:
        wait = max(int(60 - (now - min(last_minute))) + 1, 1)
        raise GeminiRateLimitedError(wait, "LIMITE_POR_MINUTO")
    if len(timestamps) >= GEMINI_MAX_CALLS_PER_HOUR:
        wait = max(int(3600 - (now - min(timestamps))) + 1, 1)
        raise GeminiRateLimitedError(wait, "LIMITE_POR_HORA")

    timestamps.append(now)
    _save_json_atomic(_REQUESTS_PATH, {"timestamps": timestamps})


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "resource exhausted" in text or "quota" in text


def search_clip_for_query(
    clip_path: Path,
    query: str,
    *,
    clip_start_dt: datetime,
    clip_end_dt: datetime,
    timeout_sec: int = GEMINI_SEARCH_TIMEOUT_SEC,
) -> GeminiSearchResult:
    """Sobe um trecho de video e pergunta ao Gemini se/quando o evento descrito aparece.

    Levanta GeminiNotConfiguredError, GeminiRateLimitedError, ou deixa propagar
    qualquer erro de rede/SDK do google-genai (o chamador decide como tratar).
    """
    from google.genai import types  # import tardio, mesmo motivo do client

    reserve_call_slot()
    client = _get_client()

    uploaded = client.files.upload(file=str(clip_path))
    try:
        deadline = time.time() + timeout_sec
        while getattr(getattr(uploaded, "state", None), "name", "ACTIVE") not in ("ACTIVE",):
            if time.time() > deadline:
                raise TimeoutError("Tempo esgotado esperando o Gemini processar o video.")
            time.sleep(GEMINI_FILE_POLL_SEC)
            uploaded = client.files.get(name=uploaded.name)

        duration_sec = int((clip_end_dt - clip_start_dt).total_seconds())
        prompt = _PROMPT_TEMPLATE.format(
            start=clip_start_dt.strftime("%Y-%m-%d %H:%M:%S"),
            end=clip_end_dt.strftime("%Y-%m-%d %H:%M:%S"),
            duration=duration_sec,
            query=query,
        )

        try:
            response = client.models.generate_content(
                model=GEMINI_VIDEO_MODEL,
                contents=[prompt, uploaded],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=_RESPONSE_SCHEMA,
                ),
            )
        except Exception as exc:
            if _is_rate_limit_error(exc):
                _save_cooldown(30)
            raise

        payload = json.loads(response.text)
        offset = payload.get("timestamp_offset_sec")
        hit_at = None
        if payload.get("found") and offset is not None:
            hit_at = clip_start_dt + timedelta(seconds=float(offset))

        return GeminiSearchResult(
            found=bool(payload.get("found")),
            description=str(payload.get("description") or ""),
            confidence=float(payload.get("confidence") or 0.0),
            timestamp_offset_sec=offset,
            hit_at=hit_at,
            raw=payload,
        )
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
