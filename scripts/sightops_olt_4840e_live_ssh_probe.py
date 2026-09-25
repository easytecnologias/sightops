from __future__ import annotations

import socket
import sys
import traceback

import paramiko

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cli.tools.olt_4840e_collect_macs import _open_shell


def main() -> int:
    host = sys.argv[1]
    user = sys.argv[2]
    password = sys.argv[3]
    print("paramiko", paramiko.__version__)
    transport = paramiko.Transport(socket.socket())
    opts = transport.get_security_options()
    print("supports", {
        "group1": "diffie-hellman-group1-sha1" in opts.kex,
        "3des": "3des-cbc" in opts.ciphers,
        "ssh-rsa": "ssh-rsa" in opts.key_types,
    })
    transport.close()
    try:
        client, chan = _open_shell(host, user, password, timeout=12)
        print("connected", type(client).__name__, type(chan).__name__)
        client.close()
    except Exception as exc:
        print(type(exc).__name__, str(exc))
        traceback.print_exc(limit=4)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
