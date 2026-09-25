from __future__ import annotations

import socket
import sys


def main() -> int:
    host = sys.argv[1]
    ports = [int(p) for p in sys.argv[2:]]
    for port in ports:
        sock = socket.socket()
        sock.settimeout(5)
        try:
            sock.connect((host, port))
            print(f"{port} open")
        except Exception as exc:
            print(f"{port} {type(exc).__name__}: {exc}")
        finally:
            sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
