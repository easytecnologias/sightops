import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.cli.tools.olt_8820i_collect_macs as mod

PROMPT = mod.PROMPT


class FakeChannel:
    def __init__(self, script):
        self._script = script
        # Simula o banner inicial do invoke_shell ja contendo o prompt,
        # para o open_shell() sincronizar de imediato (sem esperar timeout).
        self._pending = PROMPT
        self.closed = False

    def recv_ready(self):
        return bool(self._pending)

    def recv(self, n):
        out = self._pending[:n]
        self._pending = self._pending[n:]
        return out.encode()

    def send(self, data):
        cmd = data.strip()
        body = self._script(cmd)
        self._pending = body + "\n" + PROMPT

    def close(self):
        self.closed = True


class FakeSSHClient:
    def __init__(self, script):
        self._script = script

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, *a, **kw):
        pass

    def invoke_shell(self):
        return FakeChannel(self._script)

    def close(self):
        pass


def _onu_row(onu_id: int) -> str:
    return f"{onu_id}  8B3E3755  Active  OK  -20.52 dBm  -18.83 dBm  0.758  7:22:52:22"


def make_script(configured_pons, macs_by_onu, bulk_ok=True):
    """`macs_by_onu`: {(pon, onu_id): [mac, ...]}. `bulk_ok=False` simula uma
    OLT cujo firmware nao reconhece 'bridge show mac all' (resposta vazia),
    forcando o modo antigo (um comando por ONU)."""

    def script(cmd: str) -> str:
        if cmd.startswith("onu status gpon "):
            p = int(cmd.split()[-1])
            if p in configured_pons:
                return _onu_row(1) + "\nConfigured ONUs: 1"
            return ""
        if cmd == "bridge show mac all":
            if not bulk_ok:
                return ""
            lines = []
            for (p, onu_id), macs in macs_by_onu.items():
                for mac in macs:
                    lines.append(f"{mac}  gpon {p} onu {onu_id} gem 257 - vlan 3000  ")
            return "\n".join(lines)
        if cmd.startswith("bridge show mac gpon "):
            parts = cmd.split()
            p, onu_id = int(parts[4]), int(parts[6])
            macs = macs_by_onu.get((p, onu_id), [])
            if not macs:
                return "Total entries: 0 ."
            return "\n".join(f"{mac} vlan 100" for mac in macs)
        return ""

    return script


def _patch_client(factory):
    original = mod.paramiko.SSHClient
    mod.paramiko.SSHClient = factory
    return original


def test_bulk_collection_all_pons():
    macs_by_onu = {
        (1, 1): ["aa:aa:aa:aa:aa:01"],
        (3, 1): ["aa:aa:aa:aa:aa:03"],
        (5, 1): ["aa:aa:aa:aa:aa:05"],
    }
    script = make_script(configured_pons={1, 3, 5}, macs_by_onu=macs_by_onu)
    original = _patch_client(lambda: FakeSSHClient(script))
    try:
        rows = mod.collect_macs_8820i("10.0.0.1", "admin", "admin", pon="all")
    finally:
        mod.paramiko.SSHClient = original

    assert len(rows) == 3, f"esperava 3 linhas, veio {len(rows)}: {rows}"
    got = {(r["pon"], r["onu_id"], r["cpe_mac"]) for r in rows}
    assert got == {
        (1, 1, "aa:aa:aa:aa:aa:01"),
        (3, 1, "aa:aa:aa:aa:aa:03"),
        (5, 1, "aa:aa:aa:aa:aa:05"),
    }, got


def test_single_pon_still_works_without_discovery_phase():
    macs_by_onu = {(3, 1): ["bb:bb:bb:bb:bb:03"]}
    script = make_script(configured_pons={3}, macs_by_onu=macs_by_onu)
    original = _patch_client(lambda: FakeSSHClient(script))
    try:
        rows = mod.collect_macs_8820i("10.0.0.1", "admin", "admin", pon="3")
    finally:
        mod.paramiko.SSHClient = original

    assert len(rows) == 1, f"esperava 1 linha, veio {len(rows)}: {rows}"
    assert rows[0]["pon"] == 3
    assert rows[0]["cpe_mac"] == "bb:bb:bb:bb:bb:03"


def test_all_blank_discovery_raises_runtime_error():
    script = make_script(configured_pons=set(), macs_by_onu={})
    original = _patch_client(lambda: FakeSSHClient(script))
    try:
        try:
            mod.collect_macs_8820i("10.0.0.1", "admin", "admin", pon="all")
            assert False, "esperava RuntimeError"
        except RuntimeError as exc:
            assert "sessao/prompt" in str(exc) or "reconhecivel" in str(exc)
    finally:
        mod.paramiko.SSHClient = original


def test_falls_back_to_per_onu_when_bulk_command_unsupported():
    macs_by_onu = {(1, 1): ["cc:cc:cc:cc:cc:01"], (2, 1): ["cc:cc:cc:cc:cc:02"]}
    script = make_script(configured_pons={1, 2}, macs_by_onu=macs_by_onu, bulk_ok=False)
    original = _patch_client(lambda: FakeSSHClient(script))
    try:
        rows = mod.collect_macs_8820i("10.0.0.1", "admin", "admin", pon="all")
    finally:
        mod.paramiko.SSHClient = original

    assert len(rows) == 2, f"esperava 2 linhas (fallback ONU a ONU), veio {len(rows)}: {rows}"
    got = {(r["pon"], r["onu_id"], r["cpe_mac"]) for r in rows}
    assert got == {(1, 1, "cc:cc:cc:cc:cc:01"), (2, 1, "cc:cc:cc:cc:cc:02")}, got


def test_parse_bulk_macs_all_ignores_eth_lines():
    output = (
        "    MAC Address                 Bridge              \n"
        "================== =================================\n"
        "74:4d:28:b7:8d:44  eth 1 vlan 3051                   \n"
        "18:0d:2c:c0:26:f0  gpon 1 onu 1 gem 257 - vlan 3000  \n"
        "80:8f:e8:f8:58:1e  gpon 1 onu 2 gem 258 - vlan 3000  \n"
    )
    parsed = mod.parse_bulk_macs_all(output)
    assert parsed == {
        (1, 1): [{"cpe_mac": "18:0d:2c:c0:26:f0", "vlan": "3000"}],
        (1, 2): [{"cpe_mac": "80:8f:e8:f8:58:1e", "vlan": "3000"}],
    }, parsed


def main() -> None:
    test_bulk_collection_all_pons()
    test_single_pon_still_works_without_discovery_phase()
    test_all_blank_discovery_raises_runtime_error()
    test_falls_back_to_per_onu_when_bulk_command_unsupported()
    test_parse_bulk_macs_all_ignores_eth_lines()
    print("OK: sightops_olt_8820i_collect_macs_test")


if __name__ == "__main__":
    main()
