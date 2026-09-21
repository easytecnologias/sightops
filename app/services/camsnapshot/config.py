
from dotenv import load_dotenv
import os

load_dotenv()

SETTINGS = {
    "DEFAULT_USER": os.getenv("DEFAULT_USER", "admin"),
    "DEFAULT_PASS": os.getenv("DEFAULT_PASS", "global1234"),
    "SNAPSHOT_DIR": os.getenv("SNAPSHOT_DIR", "output/snapshot"),
    "TIMEOUT": float(os.getenv("TIMEOUT", "6")),
    "RETRIES": int(os.getenv("RETRIES", "2")),
}
