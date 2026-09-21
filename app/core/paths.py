from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback defensivo
    load_dotenv = None

if load_dotenv:
    load_dotenv()


# ========================
# Paths basicos do projeto
# ========================
# Refatoracao incremental (opcao 1):
# o legado tinha tudo no app/main.py; agora centralizamos aqui
# para que modulos (routers/services) possam importar sem circular.


# raiz do projeto (pasta que contem "app/")
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.getenv("DATA_DIR") or (BASE_DIR / "data"))

# output agora e alias de data para consolidar persistencia
OUTPUT_DIR = DATA_DIR

# configuracoes persistentes do app (ex.: chaves de integracoes)
APP_SETTINGS_PATH = Path(os.getenv("APP_SETTINGS_PATH") or (DATA_DIR / "app_settings.json"))

# compat: frontend usa /saida/... como alias
SAIDA_DIR = OUTPUT_DIR

# Fonte unica do inventario:
# em v2 consolidado, `saida` aponta para `data`.
INVENTORY_JSON_PATH = Path(os.getenv("INVENTORY_JSON_PATH") or (SAIDA_DIR / "cam-inventory.json"))
DVR_INVENTORY_JSON_PATH = Path(os.getenv("DVR_INVENTORY_JSON_PATH") or (DATA_DIR / "dvr-inventory.json"))
NVR_INVENTORY_JSON_PATH = Path(os.getenv("NVR_INVENTORY_JSON_PATH") or (DATA_DIR / "nvr-inventory.json"))
SIGHTOPS_DB_PATH = Path(os.getenv("SIGHTOPS_DB_PATH") or (DATA_DIR / "sightops.db"))
DVR_SNAPSHOT_DIR = Path(os.getenv("DVR_SNAPSHOT_DIR") or (DATA_DIR / "dvr_snapshot"))
NVR_SNAPSHOT_DIR = Path(os.getenv("NVR_SNAPSHOT_DIR") or (DATA_DIR / "nvr_snapshot"))

# scripts CLI (rodados via subprocess pelo backend)
TOOLS_DIR = Path(os.getenv("TOOLS_DIR") or (BASE_DIR / "app" / "cli" / "tools"))

# KMZ (import / preview / generate)
KMZ_INPUT_DIR = Path(os.getenv("KMZ_INPUT_DIR") or (DATA_DIR / "input" / "kmz"))  # pasta-base usada pelo kmz_from_inventory.py
KMZ_IMPORTED_PATH = Path(os.getenv("KMZ_IMPORTED_PATH") or (DATA_DIR / "input" / "imported.kmz"))  # copia do ultimo KMZ importado
KMZ_IMPORTED_GEOJSON_PATH = Path(os.getenv("KMZ_IMPORTED_GEOJSON_PATH") or (DATA_DIR / "input" / "imported.geojson"))  # cache para preview no mapa
KMZ_OUTPUT_DIR = Path(os.getenv("KMZ_OUTPUT_DIR") or (OUTPUT_DIR / "kmz"))  # saida do KMZ enriquecido (data/kmz)


def ensure_dirs() -> None:
    """Garante pastas essenciais no boot do app."""
    for p in (
        DATA_DIR,
        OUTPUT_DIR,
        SAIDA_DIR,
        KMZ_INPUT_DIR,
        KMZ_OUTPUT_DIR,
        DVR_SNAPSHOT_DIR,
        NVR_SNAPSHOT_DIR,
    ):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
