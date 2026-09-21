import os, requests, sys
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

k = os.getenv("IMGBB_API_KEY")
print("KEY_PREFIX:", (k or "")[:6])
if not k:
    print("ERRO: sem IMGBB_API_KEY no ambiente (.env)"); sys.exit(1)

img = Path(r".\saida\snapshot\10.10.9.20.jpg")
if not img.exists():
    print("ERRO: snapshot não encontrado:", img); sys.exit(1)

with open(img, "rb") as f:
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        params={"key": k},
        files={"image": (img.name, f, "application/octet-stream")},
        data={"name": "10.10.9.20", "description": "IP: 10.10.9.20 | ALBUM: RESERVA PERUCABA"},
        timeout=30
    )

print("status:", r.status_code)
print(r.text[:800])
