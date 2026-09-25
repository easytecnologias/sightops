from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import argparse


class Handler(BaseHTTPRequestHandler):
    dest_dir = Path(".")

    def _write_file(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        name = self.path.rsplit("/", 1)[-1] or "upload.bin"
        name = name.replace("..", "_").replace("\\", "_").replace("/", "_")
        dest = self.dest_dir / name
        data = self.rfile.read(length)
        dest.write_bytes(data)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_PUT(self):  # noqa: N802
        self._write_file()

    def do_POST(self):  # noqa: N802
        self._write_file()

    def log_message(self, format, *args):  # noqa: A003
        print(format % args, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--dest", default="output/olt-backups")
    args = parser.parse_args()

    Handler.dest_dir = Path(args.dest)
    Handler.dest_dir.mkdir(parents=True, exist_ok=True)
    httpd = HTTPServer((args.host, args.port), Handler)
    print(f"listening on {args.host}:{args.port}, saving to {Handler.dest_dir}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
