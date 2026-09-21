import os, sys
required = ["IMGBB_API_KEY"]
optional = ["TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID","IMGBB_TIMEOUT","IMGBB_THREADS","IMGBB_RATE","IMGBB_BACKOFF","THUMB_WIDTH","MAKE_THUMBS"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    print("Faltando variáveis obrigatórias:", ", ".join(missing))
    print("Crie .env a partir de .env.example e tente novamente.")
    sys.exit(1)
print("OK: Variáveis obrigatórias presentes.")
for k in optional:
    v=os.getenv(k)
    if v is not None: print(f"{k}={v}")
