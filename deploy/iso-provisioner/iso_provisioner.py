#!/usr/bin/env python3
"""SightOps v3 -- provisionador de isolamento de conectores (container privilegiado).

Roda como um servico do docker-compose (network_mode: host + NET_ADMIN), NAO como
script na raiz do servidor. Reconcilia a cada ciclo: para cada conector routeros
que nasceu isolado (tem iso_index e NAO tem iso_manual), garante no host a interface
wgc<N> + peer + rotas na tabela 100N + vnat 1:1, e grava o mapa vnat que o app le.
NAO toca em conector iso_manual=True (os migrados na mao). Idempotente.

Volumes montados no container:
  /app/data/connectors.json            (rw)  -- inventario de conectores (do app)
  /app/data/connector_vnat_map.json    (rw)  -- mapa que o app consome
  /etc/wireguard/wg-sightops.conf       (ro)  -- chave privada do WG (reusada pelos wgc)
"""
import ipaddress, json, os, subprocess, sys, time

CONNECTORS = os.environ.get("CONNECTORS_PATH", "/app/data/connectors.json")
VNAT_MAP = os.environ.get("VNAT_MAP_PATH", "/app/data/connector_vnat_map.json")
LIVENESS = os.environ.get("LIVENESS_PATH", "/app/data/connector_liveness.json")
WG_CONF = os.environ.get("WG_CONF_PATH", "/etc/wireguard/wg-sightops.conf")
INTERVAL = int(os.environ.get("ISO_INTERVAL", "30"))
VIRTUAL_ROOT = ipaddress.ip_network("10.208.0.0/12")
SLICE_PREFIX = 18
# TRAVA DE SEGURANCA: teardown so mexe em wgc<N> com N >= ISO_FLOOR.
# wgc1..7 sao os conectores migrados na mao (iso_manual) -- NUNCA derrubar.
ISO_FLOOR = 8
# Portas de GESTAO do servidor, que ninguem do lado do cliente deve alcancar.
# Vazio desliga o bloqueio.
PORTAS_GESTAO = os.environ.get("ISO_BLOCK_PORTS", "9000,9443,3003,8091,10053,18600,8090").strip()
ENV = {"PATH": "/usr/sbin:/sbin:/usr/bin:/bin"}


def sh(argv, stdin=None, check=False):
    p = subprocess.run(argv, input=stdin, text=True, capture_output=True, env=ENV)
    if check and p.returncode != 0:
        raise RuntimeError("cmd falhou: %s :: %s" % (" ".join(argv), (p.stderr or "").strip()))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def wg_privkey():
    for line in open(WG_CONF):
        if line.lower().strip().startswith("privatekey"):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("PrivateKey nao encontrada em %s" % WG_CONF)


def load_connectors():
    try:
        d = json.load(open(CONNECTORS))
    except Exception:
        return []
    return d if isinstance(d, list) else d.get("connectors", [])


def virtual_slice(index):
    size = 2 ** (32 - SLICE_PREFIX)
    base = int(VIRTUAL_ROOT.network_address) + (index - 1) * size
    return ipaddress.ip_network((base, SLICE_PREFIX))


def virtual_map(index, lans):
    slice_net = virtual_slice(index)
    cursor = int(slice_net.network_address)
    out = []
    for lan in lans:
        try:
            net = ipaddress.ip_network(lan, strict=False)
        except ValueError:
            continue
        size = net.num_addresses
        cursor = (cursor + size - 1) // size * size  # alinha o inicio ao bloco (senao "host bits set")
        vnet = ipaddress.ip_network((cursor, net.prefixlen))
        if vnet.broadcast_address > slice_net.broadcast_address:
            break
        out.append((str(net), str(vnet)))
        cursor += size
    return out


def _iptc(tabela, chain, spec, insert=False):
    base = ["iptables", "-t", tabela]
    rc, _ = sh(base + ["-C", chain] + spec)
    if rc == 0:
        return
    sh(base + (["-I", chain, "1"] if insert else ["-A", chain]) + spec)


def _apply(n, cid, pubkey, lans, vmap, priv):
    """Cria/garante a interface wgc<N> + peer + rotas + vnat (idempotente).
    pubkey/lans/vmap ja resolvidos pelo chamador (migrado usa dados gravados,
    born-isolated calcula na hora)."""
    ifn = "wgc%d" % n
    port = 52000 + n
    server_ip = "10.201.0.%d" % (2 * n)
    peer_ip = "10.201.0.%d" % (2 * n + 1)
    table = 1000 + n
    fwmark = 0x5100 + n
    rule_pref = 10000 + n
    mark_pref = 20000 + n
    allowed = ",".join(["%s/32" % peer_ip] + lans)

    sh(["sysctl", "-qw", "net.ipv4.conf.all.rp_filter=2"])
    rc, _ = sh(["ip", "link", "show", ifn])
    if rc != 0:
        sh(["ip", "link", "add", "dev", ifn, "type", "wireguard"], check=True)
    sh(["wg", "set", ifn, "listen-port", str(port), "private-key", "/dev/stdin"], stdin=priv, check=True)
    sh(["wg", "set", ifn, "peer", pubkey, "allowed-ips", allowed, "persistent-keepalive", "25"], check=True)
    sh(["ip", "addr", "replace", "%s/31" % server_ip, "dev", ifn], check=True)
    sh(["ip", "link", "set", ifn, "up"])
    sh(["sysctl", "-qw", "net.ipv4.conf.%s.rp_filter=2" % ifn])
    sh(["ip", "rule", "del", "pref", str(rule_pref)])
    sh(["ip", "rule", "add", "from", server_ip, "table", str(table), "pref", str(rule_pref)])
    sh(["ip", "route", "replace", "%s/32" % peer_ip, "dev", ifn, "table", str(table)])
    for lan in lans:
        sh(["ip", "route", "replace", lan, "dev", ifn, "table", str(table)])
    _vnat_limpa_obsoletas(n, vmap)
    for real, virt in vmap:
        _iptc("mangle", "PREROUTING", ["-d", virt, "-j", "MARK", "--set-mark", hex(fwmark)])
        _iptc("nat", "PREROUTING", ["-d", virt, "-j", "NETMAP", "--to", real])
        _iptc("nat", "POSTROUTING", ["-o", ifn, "-j", "SNAT", "--to-source", server_ip], insert=True)
    _iptc("filter", "DOCKER-USER", ["-o", ifn, "-j", "ACCEPT"], insert=True)
    _iptc("filter", "DOCKER-USER", ["-i", ifn, "-j", "ACCEPT"], insert=True)
    _bloqueia_gestao(ifn)
    sh(["ip", "rule", "del", "fwmark", hex(fwmark)])
    sh(["ip", "rule", "add", "fwmark", hex(fwmark), "table", str(table), "pref", str(mark_pref)])
    return "%s: wgc%d ok (%d LAN, vnat=%d)" % (cid, n, len(lans), len(vmap))


def _iptc_topo(tabela, chain, spec):
    """Garante a regra na POSICAO 1 da chain (remove antes de inserir)."""
    base = ["iptables", "-t", tabela]
    sh(base + ["-D", chain] + spec)
    sh(base + ["-I", chain, "1"] + spec)


def _bloqueia_gestao(ifn):
    """Fecha as portas de gestao do servidor para quem entra pelo tunel.

    DOCKER-USER leva um '-i wgc<N> -j ACCEPT' amplo, para o trafego de volta dos
    equipamentos do cliente. So que ele tambem libera as portas publicadas no
    host: Portainer (9000/9443), Grafana (3003), Zabbix (8091/10053) e afins
    ficavam alcancaveis de dentro da rede de QUALQUER cliente conectado, e o
    Portainer e controle total do Docker -- ou seja, dos dados de todos os
    clientes (auditoria de 30/09/2026, INPUT com policy ACCEPT e sem regras).

    O tunel existe para o SERVIDOR alcancar o cliente; o contrario nunca e
    necessario -- o agente do MikroTik fala com a API pela internet, nao por
    aqui. Isso nao muda o acesso de quem chega pela LAN ou pelo dominio.

    Vai na posicao 1 a cada ciclo porque o ACCEPT amplo tambem e inserido no
    topo: sem reinserir, a ordem entre os dois dependeria de quem foi
    recriado por ultimo.
    """
    if not PORTAS_GESTAO:
        return
    _iptc_topo("filter", "DOCKER-USER",
               ["-i", ifn, "-p", "tcp", "-m", "multiport",
                "--dports", PORTAS_GESTAO, "-j", "DROP"])


def _lans_of(conn):
    return [c for c in ((conn.get("tunnel") or {}).get("client_lans") or []) if c]


def _in_slice(cidr, slice_net):
    try:
        return ipaddress.ip_network(cidr, strict=False).subnet_of(slice_net)
    except Exception:
        return False


def _norm_cidr(valor):
    try:
        return str(ipaddress.ip_network(str(valor), strict=False))
    except Exception:
        return str(valor)


def _tunnel_lan(n):
    """A /31 do proprio tunel do conector n: servidor .2n, MikroTik .2n+1."""
    return "10.201.0.%d/31" % (2 * n)


def _virtual_livre(n, vmap, prefixlen=31):
    """Primeira faixa livre e alinhada dentro do slice /18 do conector."""
    slice_net = virtual_slice(n)
    usados = []
    for _real, virt in vmap:
        try:
            usados.append(ipaddress.ip_network(virt, strict=False))
        except ValueError:
            pass
    size = 2 ** (32 - prefixlen)
    cursor = int(slice_net.network_address)
    while True:
        cursor = (cursor + size - 1) // size * size
        cand = ipaddress.ip_network((cursor, prefixlen))
        if cand.broadcast_address > slice_net.broadcast_address:
            return ""
        bate = next((u for u in usados if cand.overlaps(u)), None)
        if not bate:
            return str(cand)
        cursor = int(bate.broadcast_address) + 1


def _vnat_completa_tunel(n, vmap):
    """Garante a rede do TUNEL no vnat de um conector migrado (iso_manual).

    Os migrados tem o vnat congelado do dia da migracao, que levou so as LANs
    de camera. Sem a /31 do tunel o servidor nao traduz o IP do proprio
    MikroTik -- e o container, que nao tem as interfaces wgc, tenta o IP real e
    nao chega. Era por isso que o Winbox pelo tunel parava em "Logging in..."
    em 7 dos 12 conectores, e funcionava nos born-isolated, que recalculam o
    mapa a partir das client_lans (30/09/2026).

    Aditivo de proposito: nao encosta no que ja esta mapeado e funcionando.
    """
    real = _tunnel_lan(n)
    if any(_norm_cidr(r) == _norm_cidr(real) for r, _v in vmap):
        return vmap, None
    virt = _virtual_livre(n, vmap, 31)
    if not virt:
        return vmap, None
    return list(vmap) + [(real, virt)], (real, virt)


def _vnat_regra_avulsa(n, real, virt):
    """So as regras de traducao da faixa nova -- nao toca na interface viva."""
    ifn = "wgc%d" % n
    fwmark = 0x5100 + n
    server_ip = "10.201.0.%d" % (2 * n)
    _iptc("mangle", "PREROUTING", ["-d", virt, "-j", "MARK", "--set-mark", hex(fwmark)])
    _iptc("nat", "PREROUTING", ["-d", virt, "-j", "NETMAP", "--to", real])
    _iptc("nat", "POSTROUTING", ["-o", ifn, "-j", "SNAT", "--to-source", server_ip], insert=True)


def _vnat_limpa_obsoletas(n, vmap):
    """Tira do slice do conector toda regra de vnat que nao esta no mapa de agora.

    As regras sao aditivas (_iptc so insere o que falta), entao quando o conjunto
    de LANs muda -- o normal num conector recem-criado, que so descobre a LAN das
    cameras no heartbeat seguinte -- o mapa virtual e recalculado e as regras da
    rodada anterior ficam para tras. Uma faixa velha MAIOR pode cair antes na
    chain e sequestrar o IP do roteador: no CANAPI (25/09/2026)
    `10.210.192.0/23 -> 172.28.0.0/23` engolia `10.210.192.0/24 -> 10.201.0.0/24`
    e o Winbox nao alcancava o MikroTik, embora as cameras funcionassem.

    Com vmap vazio nao limpa nada de proposito: um ciclo sem LAN detectada nao
    deve derrubar um vnat que esta funcionando.
    """
    if not vmap:
        return
    slice_net = virtual_slice(n)
    virts = {_norm_cidr(virt) for _real, virt in vmap}
    pares = {(_norm_cidr(virt), _norm_cidr(real)) for real, virt in vmap}

    def _destino(r):
        return _norm_cidr(r[r.index("-d") + 1]) if "-d" in r else ""

    def _mark_obsoleta(r):
        if "MARK" not in r or "-d" not in r:
            return False
        d = _destino(r)
        return _in_slice(d, slice_net) and d not in virts

    def _netmap_obsoleta(r):
        if "NETMAP" not in r or "-d" not in r or "--to" not in r:
            return False
        d = _destino(r)
        if not _in_slice(d, slice_net):
            return False
        return (d, _norm_cidr(r[r.index("--to") + 1])) not in pares

    _ipt_delete_matching("mangle", "PREROUTING", _mark_obsoleta)
    _ipt_delete_matching("nat", "PREROUTING", _netmap_obsoleta)


def _ipt_delete_matching(tabela, chain, pred):
    """Apaga da chain toda regra (linha -A) cujo spec casa com pred(list_de_tokens)."""
    rc, out = sh(["iptables", "-t", tabela, "-S", chain])
    if rc != 0:
        return
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("-A "):
            continue
        toks = line.split()[1:]  # tira o '-A'; toks[0] = nome da chain
        rulespec = toks[1:]
        try:
            if pred(rulespec):
                sh(["iptables", "-t", tabela, "-D", chain] + rulespec)
        except Exception:
            continue


def teardown(n):
    """Remove wgc<N> orfao (conector deletado). So chamado para N >= ISO_FLOOR."""
    if n < ISO_FLOOR:
        return "wgc%d: RECUSADO teardown (indice manual/reservado)" % n
    ifn = "wgc%d" % n
    slice_net = virtual_slice(n)
    sh(["ip", "link", "del", ifn])  # leva addr + rotas scope-link da interface
    sh(["ip", "rule", "del", "pref", str(10000 + n)])
    sh(["ip", "rule", "del", "pref", str(20000 + n)])

    def _has_d_in_slice(r):
        if "-d" not in r:
            return False
        return _in_slice(r[r.index("-d") + 1], slice_net)

    _ipt_delete_matching("mangle", "PREROUTING", lambda r: "MARK" in r and _has_d_in_slice(r))
    _ipt_delete_matching("nat", "PREROUTING", lambda r: "NETMAP" in r and _has_d_in_slice(r))
    _ipt_delete_matching("nat", "POSTROUTING", lambda r: "-o" in r and r[r.index("-o") + 1] == ifn)
    _ipt_delete_matching("filter", "DOCKER-USER", lambda r: ifn in r)
    return "wgc%d: teardown (orfao removido)" % n


def existing_wgc_indices():
    rc, out = sh(["wg", "show", "interfaces"])
    idx = []
    if rc == 0:
        for w in out.split():
            if w.startswith("wgc"):
                try:
                    idx.append(int(w[3:]))
                except ValueError:
                    pass
    return idx


def write_vnat_map(active_entries, orphan_slices):
    """Grava o mapa: mantem os manuais, atualiza os born-isolated ativos,
    e remove entradas cujo virtual caiu num slice de conector deletado."""
    cur = {}
    try:
        cur = json.load(open(VNAT_MAP))
    except Exception:
        cur = {}
    if not isinstance(cur, dict):
        cur = {}
    # remove entradas orfas (virtual dentro de um slice que foi derrubado)
    for cid in list(cur.keys()):
        rows = cur.get(cid) or []
        if rows and any(any(_in_slice(r.get("virtual_cidr", ""), sl) for sl in orphan_slices) for r in rows):
            cur.pop(cid, None)
    cur.update(active_entries)
    tmp = VNAT_MAP + ".tmp"
    json.dump(cur, open(tmp, "w"), indent=2)
    os.replace(tmp, VNAT_MAP)


def reconcile_once():
    priv = wg_privkey()
    conns = load_connectors()
    existing = set(existing_wgc_indices())
    logs, vnat_entries = [], {}
    try:
        mapa_atual = json.load(open(VNAT_MAP))
        mapa_atual = mapa_atual if isinstance(mapa_atual, dict) else {}
    except Exception:
        mapa_atual = {}
    active_all = set()  # todo indice com conector presente (manual OU born) -- protege do teardown
    for c in conns:
        if str(c.get("type") or "routeros") != "routeros":
            continue
        if not c.get("iso_index"):
            continue
        n = int(c["iso_index"])
        active_all.add(n)
        try:
            if c.get("iso_manual"):
                # MIGRADO: no servidor atual JA existe -> NAO toca no vivo.
                # Ainda assim completa o vnat com a rede do tunel, que a
                # migracao nao levou (ver _vnat_completa_tunel): so acrescenta
                # regra, nunca mexe na interface nem no que ja esta mapeado.
                # Num servidor novo (wgc<N> faltando) recria da config gravada.
                if n in existing:
                    _bloqueia_gestao("wgc%d" % n)
                    # Parte do mapa que ESTA valendo, nao do iso_vnat congelado
                    # na migracao: senao a entrada do tunel e recalculada a cada
                    # ciclo e o log repete para sempre.
                    gravado = mapa_atual.get(str(c.get("id"))) or []
                    vm = [(e.get("real_cidr"), e.get("virtual_cidr"))
                          for e in (gravado or c.get("iso_vnat") or [])
                          if e.get("real_cidr") and e.get("virtual_cidr")]
                    vm, adicionada = _vnat_completa_tunel(n, vm)
                    if adicionada:
                        _vnat_regra_avulsa(n, adicionada[0], adicionada[1])
                        logs.append("%s: vnat do tunel %s -> %s" % (
                            c.get("id"), adicionada[0], adicionada[1]))
                    if vm:
                        vnat_entries[str(c.get("id"))] = [
                            {"real_cidr": r, "virtual_cidr": v} for r, v in vm]
                    continue
                pub = (c.get("iso_peer_pubkey") or "").strip()
                if not pub:
                    logs.append("%s: iso_manual sem iso_peer_pubkey (nao recria)" % c.get("id"))
                    continue
                vm = [(e.get("real_cidr"), e.get("virtual_cidr")) for e in (c.get("iso_vnat") or []) if e.get("real_cidr") and e.get("virtual_cidr")]
                vm, _nova = _vnat_completa_tunel(n, vm)
                logs.append("[recria migrado] " + _apply(n, c.get("id"), pub, _lans_of(c), vm, priv))
                if vm:
                    vnat_entries[str(c.get("id"))] = [{"real_cidr": r, "virtual_cidr": v} for r, v in vm]
            else:
                # BORN-ISOLATED: reconcilia sempre (evolui quando as LANs chegam).
                pub = ((c.get("tunnel") or {}).get("client_public_key") or "").strip()
                if not pub:
                    logs.append("%s: aguardando install (sem client_public_key)" % c.get("id"))
                    continue
                lans = _lans_of(c)
                vm = virtual_map(n, lans)
                logs.append(_apply(n, c.get("id"), pub, lans, vm, priv))
                if vm:
                    vnat_entries[str(c.get("id"))] = [{"real_cidr": r, "virtual_cidr": v} for r, v in vm]
        except Exception as e:
            logs.append("%s: ERRO %s" % (c.get("id"), e))
    # TEARDOWN: wgc<N> com N>=ISO_FLOOR que existe no host mas nao tem mais conector.
    # Trava dura: nunca derruba wgc1..7 (migrados), mesmo que sumam do connectors.json.
    orphan_slices = []
    for n in existing:
        if n >= ISO_FLOOR and n not in active_all:
            logs.append(teardown(n))
            orphan_slices.append(virtual_slice(n))
    if vnat_entries or orphan_slices:
        write_vnat_map(vnat_entries, orphan_slices)
    return logs


def write_liveness(conns):
    """Grava {connector_id: epoch_ultimo_handshake} lendo o wgc<N> de cada conector.
    O app (bridge, sem netns) le isso pra saber que o tunel esta VIVO mesmo quando
    o agente do MikroTik bate heartbeat no prod (nao no v3)."""
    out = {}
    for c in conns:
        n = c.get("iso_index")
        cid = str(c.get("id") or "")
        if not n or not cid:
            continue
        rc, txt = sh(["wg", "show", "wgc%d" % int(n), "latest-handshakes"])
        if rc != 0:
            continue
        best = 0
        for line in txt.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].isdigit():
                best = max(best, int(parts[-1]))
        if best > 0:
            out[cid] = best
    tmp = LIVENESS + ".tmp"
    json.dump(out, open(tmp, "w"), indent=2)
    os.replace(tmp, LIVENESS)


def main():
    once = "--once" in sys.argv
    while True:
        try:
            logs = reconcile_once()
            if logs:
                print("[iso] " + " | ".join(logs), flush=True)
            try:
                write_liveness(load_connectors())
            except Exception as e:
                print("[iso] ERRO liveness: %s" % e, flush=True)
        except Exception as e:
            print("[iso] ERRO reconcile: %s" % e, flush=True)
        if once:
            break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
