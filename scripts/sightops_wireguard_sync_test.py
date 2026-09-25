"""Testa a logica pura de scripts/sightops_wireguard_sync.py -- sem `wg`, sem
`ip route`, sem root. So as funcoes que decidem O QUE fazer; a parte que
executa comandos de sistema fica de fora (nao roda em CI, precisa do host).

Os dados de exemplo abaixo espelham o caso real que motivou o script: SIERRA
tinha 5 redes cadastradas em client_lans mas so 1 (192.168.20.0/24) aplicada
no wg-sightops -- as outras 4, incluindo a rede da camera (10.200.0.0/23),
nunca ganharam rota porque wg-quick so aplica o que estava no arquivo quando a
interface subiu.

Roda direto:  python scripts/sightops_wireguard_sync_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sightops_wireguard_sync import (
    canon_cidr,
    compute_target_state,
    find_exact_conflicts,
    parse_wg_dump,
    plan_updates,
    render_conf_with_updated_peer,
)

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


SIERRA_PUBKEY = "O1uugP6g++XiIgMck4Jdolj5W8tXeDNVeHP5xiTVji8="
PERUCABA_PUBKEY = "/8WFi42+54pUVZaIf7E02qcU++v5fzc1buuAu26YMh8="

CONNECTORS = [
    {
        "name": "PERUCABA", "site": "Matriz",
        "tunnel": {
            "enabled": True, "type": "wireguard",
            "client_public_key": PERUCABA_PUBKEY,
            "client_address": "10.250.0.2/32",
            "client_lans": [
                "10.10.8.0/21", "10.11.11.0/24", "10.80.80.0/28",
                "172.16.20.0/24", "172.16.44.0/23", "192.168.1.0/24",
                "192.168.13.0/24", "192.168.20.0/24", "192.168.22.0/23", "192.168.62.0/23",
            ],
        },
    },
    {
        "name": "SIERRA", "site": "SIERRA",
        "tunnel": {
            "enabled": True, "type": "wireguard",
            "client_public_key": SIERRA_PUBKEY,
            "client_address": "10.250.0.3/32",
            "client_lans": [
                "10.0.0.0/24", "10.200.0.0/23", "172.19.200.0/30",
                "192.168.20.0/24", "192.168.22.0/24",
            ],
        },
    },
]

# Estado real observado em producao (24/07/2026): so SIERRA tinha 2 das 6
# redes esperadas aplicadas; PERUCABA nao tinha nenhuma das suas 10 (so o /32
# do proprio tunel).
WG_DUMP_REAL = (
    "PRIVATE_KEY_OCULTA\tPUBLIC_KEY_OCULTA\t51820\toff\n"
    f"{PERUCABA_PUBKEY}\t(none)\t201.33.37.26:13231\t10.250.0.2/32\t1234567890\t100\t200\t25\n"
    f"{SIERRA_PUBKEY}\t(none)\t131.196.44.130:13231\t10.250.0.3/32,192.168.20.0/24\t1234567891\t300\t400\t25\n"
)

# Conf real do servidor (chave privada mascarada -- e o que motivou o formato
# do parser do render_conf_with_updated_peer).
CONF_REAL = """[Interface]
Address = 10.250.0.1/24
PostUp = iptables -I FORWARD -i %i -j ACCEPT
ListenPort = 51820
PrivateKey = CHAVE_PRIVADA_OCULTA

[Peer]
PublicKey = /8WFi42+54pUVZaIf7E02qcU++v5fzc1buuAu26YMh8=
AllowedIPs = 10.250.0.2/32
Endpoint = 201.33.37.26:13231
PersistentKeepalive = 25

[Peer]
PublicKey = O1uugP6g++XiIgMck4Jdolj5W8tXeDNVeHP5xiTVji8=
AllowedIPs = 10.250.0.3/32, 192.168.20.0/24
PersistentKeepalive = 25
"""


def main() -> None:
    # --- canon_cidr ---
    check(canon_cidr("10.200.0.0/23") == "10.200.0.0/23", "CIDR ja normalizado deveria passar direto")
    check(canon_cidr("10.200.0.3") == "10.200.0.3/32", "host sem prefixo deveria virar /32")
    check(canon_cidr("10.200.0.5/23") == "10.200.0.0/23", "endereco com bits de host deveria normalizar pra rede")
    check(canon_cidr("") is None, "vazio deveria ser invalido")
    check(canon_cidr("nao-e-ip") is None, "lixo deveria ser invalido")
    check(canon_cidr("  10.0.0.0/24  ") == "10.0.0.0/24", "espacos deveriam ser removidos")

    # --- compute_target_state ---
    target = compute_target_state(CONNECTORS)
    check(set(target.keys()) == {SIERRA_PUBKEY, PERUCABA_PUBKEY}, f"deveria ter os 2 peers: {target.keys()}")
    check("10.200.0.0/23" in target[SIERRA_PUBKEY]["allowed"], "rede da camera deveria estar no alvo da SIERRA")
    check("10.250.0.3/32" in target[SIERRA_PUBKEY]["allowed"], "client_address da SIERRA deveria estar no alvo")
    check(len(target[PERUCABA_PUBKEY]["allowed"]) == 11, f"PERUCABA: client_address + 10 lans = 11: {target[PERUCABA_PUBKEY]['allowed']}")

    desligado = compute_target_state([{"name": "X", "tunnel": {"enabled": False, "type": "wireguard", "client_public_key": "k", "client_lans": ["1.2.3.0/24"]}}])
    check(desligado == {}, "conector com tunel desabilitado nao deveria entrar no alvo")

    # --- find_exact_conflicts ---
    # Achado real nos dados de producao: 192.168.20.0/24 esta cadastrado, EXATO,
    # tanto na SIERRA quanto na PERUCABA -- duas redes de clientes diferentes
    # reivindicando o mesmo endereco privado. O script precisa recusar aplicar
    # essa rede pros dois em vez de adivinhar de quem e (e e por isso que ela
    # ja esta presa no peer da SIERRA desde o boot -- se a PERUCABA um dia
    # precisar dela, o trafego iria pro lugar errado).
    #
    # 192.168.22.0/24 (SIERRA) e 192.168.22.0/23 (PERUCABA) sao prefixos
    # DIFERENTES -- isso o kernel resolve sozinho por longest-prefix-match,
    # entao nao deveria aparecer aqui.
    conflitos = find_exact_conflicts(target)
    check(len(conflitos) == 1 and "192.168.20.0/24" in conflitos, f"192.168.20.0/24 deveria ser o unico conflito exato: {conflitos}")
    check(
        set(conflitos.get("192.168.20.0/24", [])) == {"PERUCABA", "SIERRA"},
        f"o conflito deveria envolver SIERRA e PERUCABA: {conflitos}",
    )

    fake_conflict = {
        "a": {"name": "A", "allowed": {"10.5.5.0/24"}},
        "b": {"name": "B", "allowed": {"10.5.5.0/24"}},
    }
    conf2 = find_exact_conflicts(fake_conflict)
    check(conf2 == {"10.5.5.0/24": ["A", "B"]}, f"mesmo CIDR exato em 2 conectores deveria ser flagrado: {conf2}")

    # --- parse_wg_dump ---
    dump = parse_wg_dump(WG_DUMP_REAL)
    check(dump[SIERRA_PUBKEY] == {"10.250.0.3/32", "192.168.20.0/24"}, f"dump da SIERRA errado: {dump.get(SIERRA_PUBKEY)}")
    check(dump[PERUCABA_PUBKEY] == {"10.250.0.2/32"}, f"dump da PERUCABA errado: {dump.get(PERUCABA_PUBKEY)}")
    check(len(dump) == 2, f"deveria ter 2 peers no dump (a 1a linha e a interface, nao peer): {dump}")

    # --- plan_updates (o caso real que motivou o script) ---
    plano = plan_updates(target, dump, conflitos)
    sierra_plan = plano[SIERRA_PUBKEY]
    check(sierra_plan["peer_exists"] is True, "peer da SIERRA existe no wg-sightops")
    check(
        sierra_plan["missing"] == {"10.0.0.0/24", "10.200.0.0/23", "172.19.200.0/30", "192.168.22.0/24"},
        f"SIERRA deveria faltar exatamente as 4 redes nunca aplicadas: {sierra_plan['missing']}",
    )
    check(
        sierra_plan["full_set"] == {"10.250.0.3/32", "192.168.20.0/24", "10.0.0.0/24", "10.200.0.0/23", "172.19.200.0/30", "192.168.22.0/24"},
        f"full_set da SIERRA deveria unir atual + faltante: {sierra_plan['full_set']}",
    )
    perucaba_plan = plano[PERUCABA_PUBKEY]
    # 10 lans cadastradas, mas 192.168.20.0/24 fica de fora por conflito exato
    # com a SIERRA -- entao faltam 9, nao 10.
    check(
        perucaba_plan["missing"] == {
            "10.10.8.0/21", "10.11.11.0/24", "10.80.80.0/28", "172.16.20.0/24",
            "172.16.44.0/23", "192.168.1.0/24", "192.168.13.0/24", "192.168.22.0/23", "192.168.62.0/23",
        },
        f"PERUCABA deveria faltar as 9 lans que nao estao em conflito: {perucaba_plan['missing']}",
    )
    check("192.168.20.0/24" not in perucaba_plan["missing"], "a rede em conflito nao deveria entrar no plano da PERUCABA")

    # peer que nunca instalou a VPN: nao existe no dump -> nada e planejado
    sem_vpn = {"nunca-instalou-pubkey": {"name": "SEM VPN", "allowed": {"10.9.9.0/24"}}}
    plano_sem_vpn = plan_updates(sem_vpn, dump, {})
    check(plano_sem_vpn["nunca-instalou-pubkey"]["peer_exists"] is False, "peer inexistente no wg deveria ser marcado peer_exists=False")
    check(plano_sem_vpn["nunca-instalou-pubkey"]["missing"] == set(), "peer inexistente nao deveria gerar plano de aplicacao")

    # rede em conflito exato nunca aparece como 'missing' pra nenhum dos dois lados
    plano_conflito = plan_updates(fake_conflict, {"a": set(), "b": set()}, conf2)
    check(plano_conflito["a"]["missing"] == set(), "CIDR em conflito nao deveria ser aplicado no conector A")
    check(plano_conflito["b"]["missing"] == set(), "CIDR em conflito nao deveria ser aplicado no conector B")

    # --- render_conf_with_updated_peer ---
    novo_conf = render_conf_with_updated_peer(CONF_REAL, SIERRA_PUBKEY, sierra_plan["full_set"])
    check("AllowedIPs = 10.250.0.2/32" in novo_conf, "bloco da PERUCABA nao deveria mudar")
    check("10.200.0.0/23" in novo_conf, "a rede da camera deveria aparecer no arquivo apos a atualizacao")
    check("172.19.200.0/30" in novo_conf, "as outras redes que faltavam tambem deveriam aparecer")
    check(novo_conf.count("PublicKey = " + SIERRA_PUBKEY) == 1, "nao deveria duplicar o bloco do peer")
    check(novo_conf.count("[Peer]") == 2, "deveria continuar com exatamente 2 blocos de peer")

    # idempotencia: aplicar de novo o MESMO conjunto nao muda mais nada
    novo_conf_2 = render_conf_with_updated_peer(novo_conf, SIERRA_PUBKEY, sierra_plan["full_set"])
    check(novo_conf_2 == novo_conf, "rodar de novo com o mesmo alvo nao deveria alterar o arquivo (idempotente)")

    # chave que nao existe no arquivo: devolve o texto original, sem inventar bloco
    sem_mudanca = render_conf_with_updated_peer(CONF_REAL, "chave-que-nao-existe", {"1.2.3.0/24"})
    check(sem_mudanca == CONF_REAL, "chave inexistente no arquivo nao deveria alterar nada")

    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print("  -", f)
        raise SystemExit(1)
    print("OK sincronizacao WireGuard: alvo calculado certo, conflito exato detectado, plano fecha a conta, arquivo .conf atualizado so no peer certo e de forma idempotente")


if __name__ == "__main__":
    main()
