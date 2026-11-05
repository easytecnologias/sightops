#!/usr/bin/env python3
"""Piloto do Alerta Termico: le uma camera termica a cada N segundos, roda a
deteccao e guarda os quadros que dispararam (e uma amostra dos outros) para
ajustar a regra com dado de campo.

So LEITURA na camera. Nada vai para banco, Zabbix nem notificacao ainda.

Rodar dentro do container da API, sem publicar nada: copie este arquivo e os
dois de app/services (termico_deteccao.py, termico_camera.py) para a mesma
pasta e rode com PYTHONPATH=/app -- os modulos que ainda nao existirem no
container sao carregados da pasta deste arquivo.

    python termico_piloto.py --tenant mega-alarmes --ip 10.0.0.81 \
        --mac a4:4c:62:30:18:a6 --site UFV-RODOANEL --connector 4fef0f33b137a51e \
        --minutos 15 --area "0.55,0;1,0;1,1;0.55,1"

    # so capturar quadros crus (fixture de teste):
    python termico_piloto.py ... --capturar 3 --saida /tmp/fixture
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path


def _garantir_modulo(nome: str):
    completo = f"app.services.{nome}"
    try:
        return importlib.import_module(completo)
    except ModuleNotFoundError:
        arq = Path(__file__).with_name(f"{nome}.py")
        spec = importlib.util.spec_from_file_location(completo, arq)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[completo] = mod
        spec.loader.exec_module(mod)
        return mod


def _poligono(txt: str):
    pts = []
    for par in (txt or "").split(";"):
        if par.strip():
            x, y = par.split(",")
            pts.append((float(x), float(y)))
    if len(pts) < 3:
        raise argparse.ArgumentTypeError(f"poligono precisa de 3 pontos ou mais: {txt!r}")
    return pts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--ip", required=True)
    ap.add_argument("--mac", default="")
    ap.add_argument("--site", default="")
    ap.add_argument("--connector", default="")
    ap.add_argument("--porta", type=int, default=80)
    ap.add_argument("--canal", type=int, default=2)
    ap.add_argument("--intervalo", type=float, default=2.0, help="segundos entre leituras")
    ap.add_argument("--minutos", type=float, default=10.0)
    ap.add_argument("--saida", default="", help="pasta dos quadros (padrao: pasta do cliente/termico_piloto)")
    ap.add_argument("--guardar-cada", type=int, default=30, help="guarda 1 quadro a cada N mesmo sem disparo (0 = nunca)")
    ap.add_argument("--capturar", type=int, default=0, help="so salva N quadros crus e sai")
    ap.add_argument("--area", action="append", type=_poligono, default=[])
    ap.add_argument("--ignorar", action="append", type=_poligono, default=[])
    ap.add_argument("--dif", type=float, default=None)
    ap.add_argument("--corpo-min", type=float, default=None)
    ap.add_argument("--corpo-max", type=float, default=None)
    ap.add_argument("--pontos-min", type=int, default=None)
    ap.add_argument("--seguidos", type=int, default=None)
    a = ap.parse_args(argv)

    from app.core.tenant_context import set_current_tenant_slug, tenant_scoped_path
    set_current_tenant_slug(a.tenant)
    from app.services.camera_credentials import resolve_camera_credential

    det = _garantir_modulo("termico_deteccao")
    cam = _garantir_modulo("termico_camera")

    cred = resolve_camera_credential(a.mac, a.site)
    if not cred:
        print("sem credencial salva para essa camera/site", file=sys.stderr)
        return 2
    base = cam.base_da_camera(a.ip, a.porta, a.connector)

    saida = Path(a.saida) if a.saida else tenant_scoped_path("termico_piloto", a.tenant) / datetime.now().strftime("%Y%m%d-%H%M%S")
    saida.mkdir(parents=True, exist_ok=True)
    print(f"camera {a.ip} via {base} -> {saida}", flush=True)

    if a.capturar:
        import requests
        from requests.auth import HTTPDigestAuth
        url = base + cam.CAMINHO_MATRIZ.format(canal=a.canal)
        for n in range(a.capturar):
            r = requests.get(url, auth=HTTPDigestAuth(cred["username"], cred["password"]), timeout=20, verify=False)
            q = det.ler_quadro(r.content, r.headers.get("Content-Type", ""))
            pref = saida / f"quadro{n + 1}"
            pref.with_suffix(".temps.bin").write_bytes(q.temps.tobytes())
            pref.with_suffix(".termico.jpg").write_bytes(q.jpeg_termico)
            pref.with_suffix(".json").write_text(json.dumps({"info": q.info, "resumo": q.resumo(), "capturado": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False, indent=1))
            print(f"quadro {n + 1}: {q.largura}x{q.altura} {q.resumo()}", flush=True)
            time.sleep(a.intervalo)
        return 0

    regra = det.Regra(areas=a.area, ignorar=a.ignorar)
    for campo, valor in (("dif_min", a.dif), ("corpo_min", a.corpo_min), ("corpo_max", a.corpo_max),
                         ("pontos_min", a.pontos_min), ("quadros_seguidos", a.seguidos)):
        if valor is not None:
            setattr(regra, campo, valor)
    (saida / "regra.json").write_text(json.dumps(regra.__dict__, ensure_ascii=False, indent=1, default=list))
    vigia = det.Vigia(regra)

    fim = time.time() + a.minutos * 60
    n = disparos = erros = 0
    while time.time() < fim:
        inicio = time.time()
        n += 1
        hora = datetime.now().strftime("%H:%M:%S")
        try:
            q = cam.buscar_quadro(base, cred["username"], cred["password"], a.canal)
        except Exception as exc:  # rede/camera: registra e segue
            erros += 1
            print(f"{hora} #{n} ERRO {exc}", flush=True)
            time.sleep(max(0.0, a.intervalo - (time.time() - inicio)))
            continue
        manchas, disparo = vigia.processar(q, time.time())
        r = q.resumo()
        txt = " ".join(f"[{m.pontos}p {m.temp_media:.1f}°C dif {m.dif:+.1f}]" for m in manchas[:4]) or "-"
        print(f"{hora} #{n} cena {r['min']}/{r['media']}/{r['max']} °C  manchas {txt}" + ("  >>> DISPARO" if disparo else ""), flush=True)

        guardar = disparo is not None or (a.guardar_cada and n % a.guardar_cada == 0)
        if guardar:
            pref = saida / f"{datetime.now().strftime('%H%M%S')}_{'disparo' if disparo else 'amostra'}"
            pref.with_suffix(".temps.bin").write_bytes(q.temps.tobytes())
            pref.with_suffix(".termico.jpg").write_bytes(q.jpeg_termico)
            if disparo:
                disparos += 1
                pref.with_suffix(".visivel.jpg").write_bytes(q.jpeg_visivel)
            pref.with_suffix(".json").write_text(json.dumps({
                "hora": hora, "resumo": r, "manchas": [m.como_dict() for m in manchas],
                "disparo": disparo.mancha.como_dict() if disparo else None,
            }, ensure_ascii=False, indent=1))
        time.sleep(max(0.0, a.intervalo - (time.time() - inicio)))

    print(f"fim: {n} leituras, {disparos} disparos, {erros} erros -> {saida}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
