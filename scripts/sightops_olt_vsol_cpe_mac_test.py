"""Testa a coleta de MAC do CPE no driver VSOL EPON.

Cobre o que quebrava o inventario de Japaratinga: `collect_macs_vsol` devolvia
`cpe_mac` vazio, a trava de `olt_service` nao achava nenhum MAC do conector e
abortava a coleta inteira.

Sem OLT: a sessao e simulada por um canal falso que responde comando a comando.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.cli.tools.olt_vsol_epon as vsol


AUTH_INFO = """show onu auth-info
ONU-ID      LLID   Status    MAC  Address         RTT(TQ) Description
EPON0/1:1   2      online    98:2a:0a:a0:26:19   446     N/A
EPON0/1:7   -1     offline   98:2a:0a:a0:26:27   0       N/A
epon-olt(config-pon-0/1)#"""

BASIC_INFO = """show onu basic-info
ONU-ID      VendorID  Model  ID            hwVer     SwVer       Type  Interface Type
EPON0/1:1   ITBS      R1v2   982A0AA02619  ONUR1_v2  1.3-220719  SFU   1GE
epon-olt(config-pon-0/1)#"""

# Saida REAL, capturada na OLT de Japaratinga em 20/08/2026 (ONU 1 da PON 0/1).
MAC_TABLE_REAL = """show onu 1 mac-address-table

 Mac Address Table
----------------------------------------------------------
Index   VLAN   MAC  Address         PON       ONU    Aging(s)
1       1000   54:6c:ac:25:e6:cf    EPON0/1   1      255
2       1000   54:6c:ac:25:e8:1a    EPON0/1   1      255
3       1000   98:2a:0a:4b:a5:71    EPON0/1   1      255
4       1000   54:6c:ac:25:e8:1c    EPON0/1   1      255

 ----------------------------------------------------------

 Total Addresses Found in System :4
epon-olt(config-pon-0/1)# """

# Mesmo formato, mas com o MAC da propria ONU aprendido na tabela -- acontece
# quando o CPE faz bridge do proprio MAC. Ele nao pode virar linha de CPE.
MAC_TABLE_COM_MAC_DA_ONU = """show onu 1 mac-address-table

 Mac Address Table
----------------------------------------------------------
Index   VLAN   MAC  Address         PON       ONU    Aging(s)
1       1000   98:2a:0a:a0:26:19    EPON0/1   1      255
2       1000   54:6c:ac:25:e6:cf    EPON0/1   1      255

 Total Addresses Found in System :2
epon-olt(config-pon-0/1)# """

MAC_TABLE_SEM_COLUNA = """show onu 1 mac-address-table
------------------------------------
 1   ac-cc-8e-11-22-33
 2   ac-cc-8e-44-55-66
epon-olt(config-pon-0/1)#"""

MAC_TABLE_VAZIA = """show onu 1 mac-address-table
epon-olt(config-pon-0/1)#"""


class CanalFalso:
    """Responde a cada comando com a saida gravada, como a OLT responderia."""

    def __init__(self, mac_table: str) -> None:
        self.mac_table = mac_table
        self.comandos: list[str] = []

    def resposta(self, cmd: str) -> str:
        self.comandos.append(cmd)
        if cmd.startswith("interface epon 0/1"):
            return "epon-olt(config-pon-0/1)#"
        if cmd.startswith("interface epon"):
            return "epon-olt(config)#"          # PON inexistente: contexto nao muda
        if cmd == "configure terminal":
            return "epon-olt(config)#"
        if cmd.endswith("mac-address-table"):
            return self.mac_table
        if cmd == "show onu auth-info":
            return AUTH_INFO
        if cmd == "show onu basic-info":
            return BASIC_INFO
        return "epon-olt#"


def _instala_sessao_falsa(canal: CanalFalso) -> None:
    vsol._manda = lambda chan, texto, alvos, timeout=20.0: chan.resposta(texto)
    vsol._espera_prompt = lambda chan, alvos, timeout=20.0: "epon-olt#"
    vsol._volta_ao_topo = lambda chan, timeout=20.0: None
    vsol._com_sessao_vsol = lambda ip, u, p, port, timeout, tarefa: tarefa(canal)


def falhas() -> list[str]:
    erros: list[str] = []

    # 1) saida real da OLT: 4 CPEs, VLAN 1000 (nao 1 do Index nem 255 do Aging)
    linhas = vsol.parse_onu_mac_table(MAC_TABLE_REAL)
    macs = [l["cpe_mac"] for l in linhas]
    esperado = ["54:6c:ac:25:e6:cf", "54:6c:ac:25:e8:1a",
                "98:2a:0a:4b:a5:71", "54:6c:ac:25:e8:1c"]
    if macs != esperado:
        erros.append(f"parse real: MACs inesperados {macs}")
    if any(l["vlan"] != "1000" for l in linhas):
        erros.append(f"parse real: vlan errada {[l['vlan'] for l in linhas]}")

    # 2) parser com formato solto e MAC separado por hifen
    linhas = vsol.parse_onu_mac_table(MAC_TABLE_SEM_COLUNA)
    macs = [l["cpe_mac"] for l in linhas]
    if macs != ["ac:cc:8e:11:22:33", "ac:cc:8e:44:55:66"]:
        erros.append(f"parse sem coluna: MACs inesperados {macs}")

    # 3) tabela vazia nao inventa linha
    if vsol.parse_onu_mac_table(MAC_TABLE_VAZIA):
        erros.append("parse de tabela vazia devolveu linha")

    # 4) coleta completa contra a saida real: uma linha por CPE
    canal = CanalFalso(MAC_TABLE_REAL)
    _instala_sessao_falsa(canal)
    linhas = vsol.collect_macs_vsol("192.168.200.2", "admin", "x", pon="0/1")
    online = [l for l in linhas if l["onu_id"] == "1"]
    if len(online) != 4:
        erros.append(f"coleta: esperava 4 linhas de CPE na ONU 1, veio {len(online)}")
    if any(not l.get("cpe_mac") for l in linhas):
        erros.append("coleta: linha com cpe_mac vazio -- a trava do olt_service aborta")
    if not all(l.get("onu_id") and l.get("pon") for l in linhas):
        erros.append("coleta: linha sem vinculo camera->ONU (pon/onu_id)")

    # 4b) nomes de campo que `_sync_camera_inventory_from_olt_rows` procura --
    #     com nome errado a camera casa pelo MAC mas fica sem modelo/estado
    topologia = {
        "onu_model": "R1v2",
        "oper_status": "Active",
        "omci_status": "OK",
        "onu_serial": "98:2a:0a:a0:26:19",
        "vlan": "1000",
    }
    for campo, esperado_valor in topologia.items():
        vistos = {l.get(campo) for l in online}
        if vistos != {esperado_valor}:
            erros.append(f"coleta: {campo} = {vistos} (esperado {esperado_valor!r})")

    # 5) ONU offline continua aparecendo, com o proprio MAC como chave
    offline = [l for l in linhas if l["onu_id"] == "7"]
    if len(offline) != 1 or offline[0]["cpe_mac"] != "98:2a:0a:a0:26:27":
        erros.append(f"coleta: ONU offline sumiu ou perdeu a chave: {offline}")
    if offline and (offline[0]["oper_status"], offline[0]["omci_status"]) != ("Offline", "LOS"):
        erros.append(f"coleta: estado da ONU offline errado: {offline[0]['oper_status']}/{offline[0]['omci_status']}")
    if any(c.endswith("mac-address-table") and " 7 " in c for c in canal.comandos):
        erros.append("coleta: consultou MAC de ONU offline (gasta timeout a toa)")

    # 6) o MAC da propria ONU, quando aparece na tabela, nao vira linha de CPE
    canal = CanalFalso(MAC_TABLE_COM_MAC_DA_ONU)
    _instala_sessao_falsa(canal)
    linhas = vsol.collect_macs_vsol("192.168.200.2", "admin", "x", pon="0/1")
    online = [l for l in linhas if l["onu_id"] == "1"]
    if [l["cpe_mac"] for l in online] != ["54:6c:ac:25:e6:cf"]:
        erros.append(f"coleta: MAC da propria ONU entrou como CPE: {[l['cpe_mac'] for l in online]}")

    # 7) ONU online sem CPE aprendido nao some do relatorio
    canal = CanalFalso(MAC_TABLE_VAZIA)
    _instala_sessao_falsa(canal)
    linhas = vsol.collect_macs_vsol("192.168.200.2", "admin", "x", pon="0/1")
    online = [l for l in linhas if l["onu_id"] == "1"]
    if len(online) != 1 or online[0]["cpe_source"] != "onu-sem-trafego":
        erros.append(f"coleta sem trafego: esperava fallback pelo MAC da ONU, veio {online}")

    # 8) a tela manda o NUMERO da PON; esta OLT so entende "0/N"
    for entrada, esperado in [(1, "0/1"), ("1", "0/1"), ("0/2", "0/2"), ("EPON0/3", "0/3")]:
        if vsol._rotulo_da_pon(entrada) != esperado:
            erros.append(f"rotulo da PON: {entrada!r} virou {vsol._rotulo_da_pon(entrada)!r}, esperado {esperado!r}")

    # 9) PON inexistente tem de falhar na hora. Nesta OLT o CLI ignora o comando
    #    em silencio -- sem checar o prompt, a tela fica minutos pendurada
    #    esperando um prompt que nunca vem.
    canal = CanalFalso(MAC_TABLE_REAL)
    _instala_sessao_falsa(canal)
    try:
        vsol._entra_na_pon(canal, 3)
        erros.append("entrar em PON inexistente nao levantou erro -- a tela fica pendurada")
    except RuntimeError:
        pass
    try:
        vsol._entra_na_pon(canal, 1)      # "PON 1" da tela = 0/1 na OLT
    except RuntimeError as exc:
        erros.append(f"PON 1 vinda da tela nao entrou: {exc}")

    return erros


def main() -> int:
    erros = falhas()
    for e in erros:
        print("FALHOU:", e)
    if not erros:
        print("OK: driver VSOL devolve cpe_mac (uma linha por CPE, ONU sempre visivel)")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
