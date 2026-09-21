import argparse, os, sys
from rich.console import Console


def _force_safe_stdio():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    except Exception:
        pass

_force_safe_stdio()
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import SETTINGS
from .network import expand_network, tcp_check, get_mac_arp
from .device_info import probe_device, get_snapshot, get_mac_http
from .utils import save_json
from tqdm import tqdm

console = Console(legacy_windows=False, force_terminal=True, no_color=False)

def _safe_for_console(value) -> str:
    """Evita UnicodeEncodeError em terminais Windows (cp1252/charmap).

    Se o stdout nÃ£o suportar algum caractere, ele vira uma sequÃªncia escapada
    (ex.: "\\u2714") em vez de derrubar o processo.
    """
    if value is None:
        return ""
    # IMPORTANTÃSSIMO: nÃ£o confie em sys.stdout.encoding no Windows.
    # O Rich (legacy_windows_render) pode acabar escrevendo em cp1252/charmap
    # mesmo quando stdout aparenta ser utf-8. EntÃ£o aqui geramos uma string
    # *sempre* segura para qualquer console: ASCII puro com escapes.
    s = str(value)
    try:
        return s.encode("ascii", errors="backslashreplace").decode("ascii", errors="strict")
    except Exception:
        # Fallback ultra seguro
        return repr(s)

def _brand_from_model_cli(model):
    if not model:
        return None
    m = str(model).upper()
    if m.startswith(("VIP","MIB","VHD","MHD")):
        return "Intelbras"
    if m.startswith(("DHI","DH-","HFW","HDP","IPC-H","IPC-D")):
        return "Dahua"
    if m.startswith(("DS-","HWI","HWP","HK")) or "HIKVISION" in m:
        return "Hikvision"
    if "HILOOK" in m:
        return "HiLook"
    return None

def main():
    parser = argparse.ArgumentParser(description="Scanner de CÃ¢meras IP â€” v1.7.4 (ranges/listas + MAC + snapshot)")
    parser.add_argument("--alvo", required=True, help="CIDR, range (A-B), lista separada por vÃ­rgula ou IP Ãºnico")
    parser.add_argument("--saida", required=True)
    parser.add_argument("--usuario", default=SETTINGS["DEFAULT_USER"])
    parser.add_argument("--senha", default=SETTINGS["DEFAULT_PASS"])
    parser.add_argument("--snapshot", action="store_true", help="Captura snapshot das cÃ¢meras")
    parser.add_argument("--fast", action="store_true", help="Modo rÃ¡pido: timeouts curtos e 1 retry")
    parser.add_argument(
        "--workers",
        type=int,
        default=int(SETTINGS.get("WORKERS", 30)),
        help="NÃºmero de workers (threads) para varredura. Em /23 ou maior, use 60-200.",
    )
    parser.add_argument(
        "--precheck-ports",
        default=str(SETTINGS.get("PRECHECK_PORTS", "80,8080,554,8000,37777")),
        help="Portas TCP para prÃ©-checagem (se nenhuma abrir, IP Ã© marcado offline). Ex: 80,554,8000",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Modo descoberta: sÃ³ faz prÃ©-checagem de portas e ARP. NÃ£o tenta identificar modelo/tÃ­tulo via HTTP.",
    )
    parser.add_argument("--timeout", type=float, default=float(SETTINGS.get("TIMEOUT", 6)))
    parser.add_argument("--retries", type=int, default=int(SETTINGS.get("RETRIES", 2)))
    parser.add_argument(
        "--auth-guard",
        dest="auth_guard",
        action="store_true",
        default=True,
        help="Valida credencial em poucos IPs antes do scan completo para evitar lockout.",
    )
    parser.add_argument(
        "--no-auth-guard",
        dest="auth_guard",
        action="store_false",
        help="Desativa validacao rapida de credencial.",
    )
    parser.add_argument(
        "--auth-probe-hosts",
        type=int,
        default=3,
        help="Quantidade de IPs da amostra para validacao inicial de credencial.",
    )
    args = parser.parse_args()

    ips = expand_network(args.alvo)

    # Ajustes automÃ¡ticos para grandes blocos (produÃ§Ã£o: /23, /22...)
    # Ideia: melhor errar para "rÃ¡pido" do que travar 40+ minutos em 500+ IPs.
    if args.fast:
        # timeout curto por padrÃ£o no fast
        args.timeout = min(args.timeout, 1.2 if len(ips) >= 256 else 3.0)
        # retries em fast: 0 ou 1. (retry alto em varredura grande explode o tempo)
        if len(ips) >= 256:
            args.retries = 0
        else:
            args.retries = min(args.retries, 1)
        # mais workers em blocos maiores
        if len(ips) >= 256 and args.workers < 120:
            args.workers = 120

    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    if args.snapshot:
        os.makedirs(SETTINGS.get("SNAPSHOT_DIR", "output/snapshot"), exist_ok=True)

    console.print(f"[cyan]IPs alvo: {len(ips)}[/cyan]")
    console.print(f"[cyan]Escaneando (fast={args.fast}, timeout={args.timeout}, retries={args.retries})[/cyan]")

    resultados = []
    auth_failed_list: list[dict] = []

    # precheck (mÃºltiplas portas) â€” essencial pra varredura grande ficar rÃ¡pida.
    # Se nenhuma porta abrir em timeout curto, nÃ£o vale gastar tempo em HTTP.
    try:
        ports = [int(p.strip()) for p in str(args.precheck_ports).split(",") if p.strip()]
    except Exception:
        ports = [80, 8080, 554, 8000, 37777]

    def _precheck_any_port(ip: str) -> bool:
        to = 0.4 if args.fast else 1.2
        for port in ports:
            if tcp_check(ip, port, timeout=to):
                return True
        return False

    precheck: dict[str, bool] = {}
    pre_workers = min(max(args.workers, 30), 300)
    with ThreadPoolExecutor(max_workers=pre_workers) as executor:
        futs = {executor.submit(_precheck_any_port, ip): ip for ip in ips}
        for fut in as_completed(futs):
            ip = futs[fut]
            try:
                precheck[ip] = bool(fut.result())
            except Exception:
                precheck[ip] = False

    # Probe/identificaÃ§Ã£o (mais caro). Em discover=True, nÃ£o faz.
    # Auth guard: evita bater credencial errada em todas as cameras.
    if args.auth_guard and (not args.discover) and args.usuario and args.senha:
        online_candidates = [ip for ip in ips if precheck.get(ip)]
        sample_n = max(1, min(int(args.auth_probe_hosts or 3), 5))
        sample_ips = online_candidates[:sample_n]
        tested = 0
        auth_failed = 0

        for ip in sample_ips:
            tested += 1
            try:
                info = probe_device(
                    ip,
                    args.usuario,
                    args.senha,
                    timeout=(0.5 if args.fast else 0.8, 1.5 if args.fast else min(args.timeout, 2.0)),
                    retries=0,
                )
            except Exception:
                info = {}
            if isinstance(info, dict) and str(info.get("status") or "").strip().lower() == "auth_failed":
                auth_failed += 1

        if tested >= 2 and auth_failed == tested:
            console.print(
                f"[red][AUTH_GUARD] Credencial rejeitada na amostra ({auth_failed}/{tested}). "
                f"Scan interrompido para evitar bloqueio de cameras.[/red]"
            )
            resultados_guard = []
            for ip in ips:
                if precheck.get(ip):
                    resultados_guard.append({
                        "ip": ip,
                        "mac": get_mac_arp(ip),
                        "modelo": None,
                        "fabricante": None,
                        "titulo": None,
                        "snapshot_path": None,
                        "status": "auth_failed",
                        "error": "senha_rejeitada_auth_guard",
                    })
                else:
                    resultados_guard.append({
                        "ip": ip,
                        "mac": get_mac_arp(ip),
                        "modelo": None,
                        "fabricante": None,
                        "titulo": None,
                        "snapshot_path": None,
                        "status": "offline",
                    })
            save_json(args.saida, resultados_guard)
            return
    probe_workers = min(max(int(args.workers * 0.6), 20), 200)
    with ThreadPoolExecutor(max_workers=probe_workers) as executor:
        futs = {}
        for ip in ips:
            if precheck.get(ip):
                if not args.discover:
                    futs[executor.submit(
                        probe_device, ip, args.usuario, args.senha,
                        timeout=(0.6 if args.fast else 1.2, args.timeout),
                        retries=args.retries
                    )] = ip
                else:
                    # Descoberta: marca como online e coleta MAC por ARP, sem gastar HTTP.
                    resultados.append({
                        "ip": ip,
                        "mac": get_mac_arp(ip),
                        "modelo": None,
                        "fabricante": None,
                        "titulo": None,
                        "snapshot_path": None,
                        "status": "online",
                    })
            else:
                # OFFLINE: jÃ¡ cria registro com 'fabricante' presente
                resultados.append({
                    "ip": ip,
                    "mac": get_mac_arp(ip),
                    "modelo": None,
                    "fabricante": None,   # <- chave garantida
                    "titulo": None,
                    "snapshot_path": None,
                    "status": "offline",
                })

        for fut in as_completed(futs):
            ip = futs[fut]
            data = {
                "ip": ip,
                "mac": None,
                "modelo": None,
                "fabricante": None,     # <- chave garantida
                "titulo": None,
                "snapshot_path": None,
                "status": "online",
            }
            try:
                info = fut.result()
                # probe_device pode sinalizar auth_failed com razÃ£o/cÃ³digo
                if isinstance(info, dict) and (info.get("status") == "auth_failed"):
                    data["status"] = "auth_failed"
                    data["auth_code"] = info.get("auth_code")
                    data["auth_url"] = info.get("auth_url")
                    data["modelo"] = info.get("modelo")
                    data["titulo"] = info.get("titulo")
                    data["fabricante"] = info.get("fabricante") or _brand_from_model_cli(info.get("modelo"))

                    auth_failed_list.append({
                        "ip": ip,
                        "fabricante": data.get("fabricante") or "",
                        "modelo": data.get("modelo") or "",
                        "titulo": data.get("titulo") or "",
                        "auth_code": data.get("auth_code") or "",
                        "auth_url": data.get("auth_url") or "",
                    })
                else:
                    data["modelo"] = info.get("modelo") if isinstance(info, dict) else None
                    data["titulo"] = info.get("titulo") if isinstance(info, dict) else None
                    data["fabricante"] = (info.get("fabricante") if isinstance(info, dict) else None) or _brand_from_model_cli(info.get("modelo") if isinstance(info, dict) else None)
            except Exception:
                data["status"] = "erro"

            # Se credencial foi rejeitada, evita chamada HTTP de MAC (normalmente tambem bloqueia)
            if data.get("status") == "auth_failed":
                mac = get_mac_arp(ip)
            else:
                # Reutiliza MAC que ja veio do probe_device para reduzir latencia.
                mac = None
                if isinstance(info, dict):
                    mac = info.get("mac")
                if not mac:
                    mac = get_mac_http(
                        ip, args.usuario, args.senha,
                        timeout=(0.6 if args.fast else 1.2, args.timeout),
                        retries=args.retries
                    )
                mac = mac or get_mac_arp(ip)
            data["mac"] = mac

            # IMPORTANTE: em Windows, alguns dispositivos retornam caracteres
            # fora do encoding do terminal (cp1252/charmap), o que derrubava o scan.
            modelo_s = _safe_for_console(data.get('modelo'))
            titulo_s = _safe_for_console(data.get('titulo'))
            mac_s = _safe_for_console(data.get('mac'))
            status_s = _safe_for_console(data.get('status'))
            console.print(f"[yellow]{ip}[/yellow] -> {modelo_s} | {titulo_s} | {mac_s} | {status_s}")
            if not data.get("fabricante"):
                data["fabricante"] = _brand_from_model_cli(data.get("modelo"))

            resultados.append(data)

    # Salva lista de IPs com falha de autenticaÃ§Ã£o (para o frontend / auditoria)
    if auth_failed_list:
        try:
            out_dir = os.path.dirname(args.saida) or "."
            auth_path = os.path.join(out_dir, "auth_failed_ips.json")
            save_json(auth_failed_list, auth_path)
            console.print(f"[magenta][AUTH] {len(auth_failed_list)} IP(s) rejeitaram credenciais. Lista: {auth_path}[/magenta]")
        except Exception as e:
            console.print(f"[magenta][AUTH][WARN] Falha ao salvar auth_failed_ips.json: {e}[/magenta]")


    # Filtro: apenas avisa sobre entradas online/erro completamente vazias (modelo/tÃ­tulo/MAC)
    incompletos = 0
    for d in resultados:
        modelo = (d.get("modelo") or "").strip()
        titulo = (d.get("titulo") or "").strip()
        mac = (d.get("mac") or "").strip()
        status = (d.get("status") or "").lower()
        if status in ("online", "erro") and not (modelo or titulo or mac):
            console.print(f"[magenta][WARN] {d.get('ip')} retornou online/erro mas sem modelo/tÃ­tulo/MAC.[/magenta]")
            incompletos += 1
    if incompletos:
        console.print(f"[magenta][WARN] {incompletos} registro(s) com dados totalmente vazios (online/erro).[/magenta]")



    if args.snapshot:
        console.print("[cyan]Capturando snapshot...[/cyan]")
        with ThreadPoolExecutor(max_workers=12) as executor:
            fut_map = {executor.submit(
                get_snapshot, r["ip"], args.usuario, args.senha,
                SETTINGS.get("SNAPSHOT_DIR", "output/snapshot"),
                timeout=(0.8 if args.fast else 1.2, args.timeout),
                retries=args.retries
            ): r for r in resultados if r["status"] == "online"}
            for fut in tqdm(as_completed(fut_map), total=len(fut_map)):
                row = fut_map[fut]
                try:
                    row["snapshot_path"] = fut.result()
                except Exception:
                    row["snapshot_path"] = None

    # NormalizaÃ§Ã£o final: TODO registro sai com 'fabricante'
    for d in resultados:
        if "fabricante" not in d or d["fabricante"] in (None, ""):
            d["fabricante"] = _brand_from_model_cli(d.get("modelo")) or ""

    save_json(args.saida, resultados)

if __name__ == "__main__":
    main()

