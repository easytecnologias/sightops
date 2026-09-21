from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Dict

from PIL import Image, ImageOps

from app.core.tenant_context import tenant_data_dir
from app.services.access_control_store import update_person_face_photo

MAX_FACE_PHOTO_BYTES = 3 * 1024 * 1024
FACE_PHOTO_SIZE = (360, 480)


def _normalize_face_photo(raw: bytes) -> bytes:
    if not raw:
        raise ValueError("Envie uma foto facial.")
    if len(raw) > MAX_FACE_PHOTO_BYTES:
        raise ValueError("Foto facial muito grande. Envie uma imagem de ate 3 MB.")
    try:
        with Image.open(BytesIO(raw)) as img:
            photo = ImageOps.exif_transpose(img).convert("RGB")
            photo = ImageOps.fit(photo, FACE_PHOTO_SIZE, method=Image.Resampling.LANCZOS)
            out = BytesIO()
            photo.save(out, format="JPEG", quality=86, optimize=True)
            return out.getvalue()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Arquivo de foto facial invalido.") from exc


def save_person_face_photo(person_id: str, raw: bytes) -> Dict[str, Any]:
    clean_id = str(person_id or "").strip()
    if not clean_id:
        raise ValueError("Pessoa invalida.")
    jpg = _normalize_face_photo(raw)
    rel_path = f"access-control/faces/{clean_id}.jpg"
    target = tenant_data_dir() / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(f"{target}.tmp")
    tmp.write_bytes(jpg)
    tmp.replace(target)
    person = update_person_face_photo(clean_id, rel_path)
    return {"person": person, "face_photo_path": rel_path, "bytes": len(jpg)}


def load_person_face_photo(person: Dict[str, Any]) -> bytes | None:
    rel_path = str(person.get("face_photo_path") or "").strip()
    if not rel_path:
        return None
    target = tenant_data_dir() / rel_path
    try:
        return target.read_bytes()
    except OSError:
        return None
