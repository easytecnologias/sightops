"""Testa a decisao entre scan local direto e scan via MikroTik (ping_many).

Ate aqui, "conector com VPN + modo OLT" sempre forcava o caminho lento via
MikroTik (so descoberta, nunca snapshot), mesmo quando o servidor JA tinha
rota real ate a LAN do cliente -- foi assim que funcionou pra Incoforte
(scan local direto, com snapshot) e como a SIERRA passou a funcionar depois
que a rota WireGuard foi corrigida (ver scripts/sightops_wireguard_sync.py).

Agora a decisao e dinamica: so cai pro caminho lento quando uma sondagem
rapida (poucos segundos) prova que a rede nao responde. Este teste NUNCA abre
socket de verdade -- o "probe_fn" e trocado por uma funcao falsa, e o teste
prova que ele so e chamado quando genuinamente precisa.

Roda direto:  python scripts/sightops_scan_reachability_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ws_scan_service import _connector_has_tunnel, _decide_remote_only, _pick_probe_targets

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


def _poison(*_a, **_kw):
    """Probe que estoura se for chamado -- prova que o codigo nao devia ter
    tentado abrir socket neste caso."""
    raise AssertionError("probe_fn chamado quando nao deveria")


def main() -> None:
    base = dict(
        scan_origin="connector",
        connector_id="conn-1",
        connector_has_tunnel=True,
        inventory_mode="olt",
        remote_only_requested=False,
        probe_targets=["10.200.0.3", "10.200.0.1"],
    )

    # --- o caso que motivou a mudanca: rede responde -> caminho local direto ---
    ok = _decide_remote_only(**{**base, "probe_fn": lambda targets: True})
    check(ok is False, "rede alcancavel deveria usar o caminho local (como funcionou pra Incoforte)")

    # --- rede nao responde -> cai pro MikroTik, sem quebrar o scan ---
    ok = _decide_remote_only(**{**base, "probe_fn": lambda targets: False})
    check(ok is True, "rede inalcancavel deveria cair pro caminho MikroTik")

    # --- sem tunel nenhum: sempre MikroTik, NUNCA sonda (nao ha o que testar) ---
    sem_tunel = {**base, "connector_has_tunnel": False, "probe_fn": _poison}
    ok = _decide_remote_only(**sem_tunel)
    check(ok is True, "sem tunel deveria forcar MikroTik sem chamar o probe")

    # --- remote_only pedido explicitamente: MikroTik sempre, mesmo que a rede responda ---
    explicito = {**base, "remote_only_requested": True, "probe_fn": lambda targets: True}
    ok = _decide_remote_only(**explicito)
    check(ok is True, "remote_only explicito deveria ser respeitado mesmo com rede alcancavel")

    # --- modo diferente de OLT (basico/switch): nao e o caso que motivou isso, nao sonda ---
    outro_modo = {**base, "inventory_mode": "basico", "probe_fn": _poison}
    ok = _decide_remote_only(**outro_modo)
    check(ok is False, "modo basico/switch nao deveria acionar a sondagem nem forcar remote_only")

    # --- sem conector: scan local comum, nao sonda ---
    sem_conector = {**base, "connector_id": "", "scan_origin": "", "probe_fn": _poison}
    ok = _decide_remote_only(**sem_conector)
    check(ok is False, "scan sem conector nao deveria acionar a sondagem")

    # --- sem alvos pra sondar (alvo vazio/invalido): nao sonda, nao quebra ---
    sem_alvos = {**base, "probe_targets": [], "probe_fn": _poison}
    ok = _decide_remote_only(**sem_alvos)
    check(ok is False, "sem alvos pra sondar nao deveria chamar o probe nem forcar remote_only")

    # --- _pick_probe_targets: pega uma amostra pequena, nao a faixa inteira ---
    amostra = _pick_probe_targets("10.200.0.1-10.200.1.254")  # faixa de 510 IPs
    check(len(amostra) <= 3, f"amostra deveria ser pequena (ate 3), veio {len(amostra)}")
    check(amostra[0] == "10.200.0.1", f"deveria comecar pelo primeiro IP da faixa: {amostra}")

    # --- _connector_has_tunnel: Ruijie nao tem agente reportando
    # tunnel/vpn/wireguard.enabled -- o sinal e ter vpn_config salvo. Bug
    # real: sem isso, todo scan via conector Ruijie caia pro caminho de fila
    # do MikroTik (que nao existe pra Ruijie) e ficava "preso" ate estourar
    # o timeout de 150s por lote.
    check(
        _connector_has_tunnel({"type": "ruijie", "vpn_config": "dev tun\n..."}) is True,
        "conector Ruijie com vpn_config deveria contar como tunel disponivel",
    )
    check(
        _connector_has_tunnel({"type": "ruijie", "vpn_config": ""}) is False,
        "conector Ruijie sem vpn_config nao deveria contar como tunel disponivel",
    )
    check(
        _connector_has_tunnel({"type": "routeros", "vpn_config": "isso nao deveria importar"}) is False,
        "vpn_config nao e o sinal certo pro MikroTik -- so tunnel/vpn/wireguard.enabled contam",
    )
    check(
        _connector_has_tunnel({"type": "routeros", "wireguard": {"enabled": True}}) is True,
        "MikroTik continua reconhecendo wireguard.enabled normalmente",
    )
    check(_connector_has_tunnel(None) is False, "conector ausente nunca tem tunel")

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print("  -", f)
        raise SystemExit(1)
    print("OK decisao de scan: usa caminho local quando a rede responde, MikroTik quando nao, nunca sonda a toa")


if __name__ == "__main__":
    main()
