import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli.tools.olt_4840e_add_onu import (
    _classify_auth_mode,
    _parse_onu_status,
    _parse_opm_diagnosis,
    _parse_white_list,
    command_failed,
)

FALHAS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        FALHAS.append(msg)


_STATUS_OUTPUT = """
ONU    Mac Address       Dis(m) RegisterTime      Type  Software   State
0/1/1  30:e1:f1:3e:a0:3f 2555   26/08/28 05:45:20 other 1.3-220719 Up
0/1/13 80:85:44:5f:32:f8 -      -                 other -          Down
Total onu entries: 2 .
onu online : 1 .
"""

_WHITE_LIST_OUTPUT = """
WHITE LIST:
Port Index Mac Address
pon-0/1 1 00:0a:5a:00:01:01
Total white-list entries: 1 .
"""

_OPM_OUTPUT = """
ONU: 0/4/1
Optical Transceiver Diagnosis :
Work Temperature : 38.25 C
Supply Voltage(Vcc) : 3.29 V
TX Bias Current : 16.99 mA
TX Power(Output) : 1.445 mW (3.00 dBm)
RX Power(Input) : 0.573 mW (-2.40 dBm)
"""


def test_parse_onu_status():
    rows = _parse_onu_status(_STATUS_OUTPUT)
    check(len(rows) == 2, f"esperava 2 linhas, veio {len(rows)}")
    up = rows[0]
    check(up["pon"] == 1 and up["onu"] == 1, f"pon/onu da linha Up errados: {up}")
    check(up["mac"] == "30:e1:f1:3e:a0:3f", f"mac errado: {up}")
    check(up["distance_m"] == 2555, f"distancia errada: {up}")
    check(up["register_time"] == "26/08/28 05:45:20", f"register_time errado: {up}")
    check(up["state"] == "Up", f"state errado: {up}")

    down = rows[1]
    check(down["onu"] == 13, f"onu da linha Down errado: {down}")
    check(down["distance_m"] is None, f"distancia da linha Down devia ser None: {down}")
    check(down["register_time"] == "", f"register_time da linha Down devia ser vazio: {down}")
    check(down["state"] == "Down", f"state da linha Down errado: {down}")


def test_parse_white_list():
    rows = _parse_white_list(_WHITE_LIST_OUTPUT)
    check(len(rows) == 1, f"esperava 1 entrada, veio {len(rows)}")
    check(rows[0]["pon"] == 1, f"pon errado: {rows[0]}")
    check(rows[0]["index"] == 1, f"index errado: {rows[0]}")
    check(rows[0]["mac"] == "00:0a:5a:00:01:01", f"mac errado: {rows[0]}")


def test_parse_opm_diagnosis():
    diag = _parse_opm_diagnosis(_OPM_OUTPUT)
    check(diag.get("temperature_c") == 38.25, f"temperatura errada: {diag}")
    check(diag.get("voltage_v") == 3.29, f"tensao errada: {diag}")
    check(diag.get("tx_bias_ma") == 16.99, f"corrente errada: {diag}")
    check(diag.get("tx_power_dbm") == 3.00, f"tx power errado: {diag}")
    check(diag.get("rx_power_dbm") == -2.40, f"rx power errado: {diag}")


def test_classify_auth_mode():
    check(_classify_auth_mode("pon 0/1 onu-authentication mode: disable") == "disable", "disable")
    check(_classify_auth_mode("pon 0/2 onu-authentication mode: mac-auth") == "mac-auth", "mac-auth")
    check(_classify_auth_mode("pon 0/3 onu-authentication mode: loid-auth") == "loid-auth", "loid-auth")
    check(_classify_auth_mode("pon 0/4 onu-authentication mode: hybrid-auth") == "hybrid-auth", "hybrid-auth")


def test_command_failed():
    check(command_failed("% Invalid parameter, and error detected at '^' marker.") is True, "invalid parameter")
    check(command_failed("% Incomplete command, and error detected at '^' marker.") is True, "incomplete command")
    check(command_failed("% Unrecognized command, and error detected at '^' marker.") is True, "unrecognized command")
    check(command_failed("Total onu entries: 2 .") is False, "saida normal nao deve contar como falha")


def main() -> None:
    test_parse_onu_status()
    test_parse_white_list()
    test_parse_opm_diagnosis()
    test_classify_auth_mode()
    test_command_failed()
    if FALHAS:
        print(f"FALHOU ({len(FALHAS)}):")
        for f in FALHAS:
            print(" -", f)
        raise SystemExit(1)
    print("OK: sightops_olt_4840e_add_onu_parsers_test")


if __name__ == "__main__":
    main()
