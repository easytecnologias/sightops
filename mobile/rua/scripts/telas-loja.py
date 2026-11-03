"""Capturas de tela do SightOps Rua para a ficha do Google Play.

Abre o app ja compilado (dist/) num navegador do tamanho de um celular, com a
API trocada por dados FICTICIOS (site "CONDOMINIO EXEMPLO", equipamentos e
nomes inventados, sem imagem de camera), e fotografa as telas. Nada vai ao
servidor de producao.

    npm run build && python scripts/telas-loja.py   -> loja/tela-*.png (1080x1920)
"""
import functools
import http.server
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
SAIDA = RAIZ / "loja"
PORTA = 8767
SITE = "CONDOMINIO EXEMPLO"
CON = "con-demo"
agora = datetime.now()


def quando(min_atras: int) -> str:
    return (agora - timedelta(minutes=min_atras)).strftime("%Y-%m-%dT%H:%M:%S")


def ent(chave, tipo, nome, status="up", det=None, mudou=600):
    return {"entity_key": chave, "entity_type": tipo, "site": SITE, "display_name": nome, "status": status,
            "last_checked_at": quando(1), "last_changed_at": quando(mudou), "connector_id": CON,
            "detail_json": json.dumps(det or {})}


OLT_IP = "10.20.0.2"
ONUS = [
    ("Portaria", -18.4, "up", ""), ("Bloco A", -19.1, "up", ""), ("Bloco B", -20.3, "up", ""),
    ("Bloco C", -27.8, "up", ""), ("Piscina", -21.0, "up", ""), ("Quadra", -19.9, "up", ""),
    ("Estacionamento", None, "down", "queda de energia"), ("Salão de festas", -22.4, "up", ""),
]
CAMS = [
    ("Portaria entrada", "10.30.0.11", "up"), ("Portaria saída", "10.30.0.12", "up"),
    ("Garagem rampa", "10.30.0.13", "up"), ("Bloco A hall", "10.30.0.14", "up"),
    ("Bloco B hall", "10.30.0.15", "up"), ("Piscina", "10.30.0.16", "up"),
    ("Estacionamento 1", "10.30.0.17", "down"), ("Quadra", "10.30.0.18", "up"),
]

entidades = {
    "connector": [ent(CON, "connector", "Conector Condomínio Exemplo")],
    "olt": [ent("olt:1", "olt", "OLT Portaria", det={"ip": OLT_IP})],
    "onu": [ent(f"onu:{i}|{OLT_IP}|1|{i}", "onu", n, s, {"onu_rx": rx, "olt_rx": (rx - 2.1) if rx else None,
                                                           "onu_tx": 2.3, "distance_km": round(0.2 + i * 0.07, 2),
                                                           "offline_reason": motivo, "serial": f"FHTT0000{i:04d}", "pon": 1},
                mudou=35 if s == "down" else 900)
            for i, (n, rx, s, motivo) in enumerate(ONUS, start=1)],
    "camera": [ent(f"camera:{ip}", "camera", n, s, {"ip": ip, "model": "DS-2CD1043G2",
                                                     "onu": {"olt_name": "OLT Portaria", "pon": "1", "onu_id": str(i)}},
                   mudou=35 if s == "down" else 900)
               for i, (n, ip, s) in enumerate(CAMS, start=1)],
    "nvr": [ent("nvr:10.30.0.2", "nvr", "NVR Portaria", det={"host": "10.30.0.2"})],
    "switch": [ent("switch:10.30.0.3", "switch", "Switch Portaria", det={"ip": "10.30.0.3"})],
    "access_device": [], "switch_provedor": [],
}

cameras_api = [
    {"ip": ip, "mac": f"44:19:B6:00:00:{i:02X}", "titulo": n, "fabricante": "Hikvision", "modelo": "DS-2CD1043G2",
     "site": SITE, "status": "online" if s == "up" else "offline", "recorder_host": "10.30.0.2", "recorder_channel": i,
     "lat": str(-9.5560 - i * 0.0004), "lon": str(-35.7610 + (i % 3) * 0.0005), "connector_id": CON,
     "pon": "1", "onu_id": str(i), "onu_name": ONUS[i - 1][0]}
    for i, (n, ip, s) in enumerate(CAMS, start=1)
]

RESPOSTAS = {
    "/api/auth/me": {"ok": True, "user": {"username": "tecnico", "full_name": "Técnico Exemplo", "tenant_name": "Exemplo"}},
    "/api/connectors": {"connectors": [{"id": CON, "name": "Conector Condomínio Exemplo", "site": SITE, "status": "online"}]},
    "/api/olt/registry": {"items": [{"id": 1, "name": "OLT Portaria", "host": OLT_IP, "vendor": "FiberHome",
                                     "model": "AN5516", "site": SITE, "active": True, "status": "online", "connector_id": CON}]},
    "/api/cameras": {"cameras": cameras_api},
    "/api/alert/summary": {"open": 2, "new": 1},
    "/api/dashboard/summary": {},
    "/api/monitoring/summary": {"events": [
        {"entity_key": "camera:10.30.0.17", "entity_type": "camera", "from_status": "up", "to_status": "down",
         "message": "Estacionamento 1 fora do ar", "created_at": quando(35)},
        {"entity_key": f"onu:7|{OLT_IP}|1|7", "entity_type": "onu", "from_status": "up", "to_status": "down",
         "message": "ONU Estacionamento: queda de energia", "created_at": quando(36)},
    ]},
    "/api/monitoring/onu-signals": {"samples": [
        {"onu_rx": round(-18.4 - (k % 5) * 0.1, 1), "olt_rx": -20.5, "captured_at": quando(k * 5), "oper_status": "up"}
        for k in range(0, 288, 4)]},
    "/api/kmz/import/layers": {"layers": []},
    "/api/olt/rows": {"rows": []},
}


def responder(route):
    url = route.request.url
    caminho = "/" + url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
    if caminho == "/api/monitoring/entities":
        tipo = url.split("entity_type=", 1)[1].split("&")[0] if "entity_type=" in url else ""
        corpo = {"entities": entidades.get(tipo, [])}
    else:
        corpo = RESPOSTAS.get(caminho)
    if corpo is None:
        route.fulfill(status=404, content_type="application/json", body='{"detail":"ficticio"}')
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))


def main():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SAIDA.mkdir(exist_ok=True)
    base = f"http://127.0.0.1:{PORTA}/index.html"
    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=3,
                              locale="pt-BR", is_mobile=True, has_touch=True)
        ctx.route("**/api/**", responder)

        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('rua.apresentacao','1')")
        pg.goto(base)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SAIDA / "tela-1-entrada.png"))
        pg.close()

        sessao = ("localStorage.setItem('rua.apresentacao','1');"
                  "localStorage.setItem('rua.token','ficticio');"
                  f"localStorage.setItem('rua.site','{SITE}');")
        onu1 = f"onu:1|{OLT_IP}|1|1"
        for nome, rota in [("tela-2-inicio", "#/"), ("tela-3-equipamentos", "#/equipamentos"),
                           ("tela-4-onu", "#/onu/" + onu1.replace("|", "%7C").replace(":", "%3A")),
                           ("tela-5-implantar", "#/implantar")]:
            pg = ctx.new_page()
            pg.add_init_script(sessao)
            pg.goto(base + rota)
            pg.wait_for_timeout(4000)
            pg.screenshot(path=str(SAIDA / f"{nome}.png"))
            pg.close()
        nav.close()
    srv.shutdown()
    print("capturas em", SAIDA)


if __name__ == "__main__":
    main()
