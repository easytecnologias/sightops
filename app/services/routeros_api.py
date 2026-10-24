"""Cliente MINIMO da API do RouterOS (porta 8728), so de leitura.

Usado pela coleta dos links do rack (rack_links.py). Recusa qualquer comando
que nao seja leitura: so caminhos terminados em /print, ou /monitor com once.
Equipamento de cliente e vivo -- a coleta nunca pode alterar nada.

Protocolo: frases de palavras com o tamanho na frente (wiki "API" da
MikroTik). Login no formato do RouterOS >= 6.43 (=name= =password=).
"""
from __future__ import annotations

import socket
from typing import Dict, List

TIMEOUT_S = 8.0


class RouterOSErro(Exception):
    """Falha de conexao, login ou comando: a mensagem vai para a tela."""


def _comando_de_leitura(palavras: List[str]) -> bool:
    cmd = palavras[0] if palavras else ""
    if not cmd.startswith("/") or "=" in cmd:
        return False
    if cmd.endswith("/print"):
        return True
    return cmd.endswith("/monitor") and "=once=" in palavras


def _tam(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    if n < 0x4000:
        return (n | 0x8000).to_bytes(2, "big")
    if n < 0x200000:
        return (n | 0xC00000).to_bytes(3, "big")
    return (n | 0xE0000000).to_bytes(4, "big")


class LeitorRouterOS:
    def __init__(self, host: str, porta: int, usuario: str, senha: str, timeout: float = TIMEOUT_S):
        try:
            self._s = socket.create_connection((host, int(porta)), timeout=timeout)
        except OSError as exc:
            raise RouterOSErro(f"sem conexao com {host}:{porta} ({exc.__class__.__name__})") from exc
        self._s.settimeout(timeout)
        try:
            self._conversa(["/login", f"=name={usuario}", f"=password={senha}"], login=True)
        except RouterOSErro:
            self.fechar()
            raise

    def __enter__(self) -> "LeitorRouterOS":
        return self

    def __exit__(self, *exc) -> None:
        self.fechar()

    def fechar(self) -> None:
        try:
            self._s.close()
        except OSError:
            pass

    def _enviar(self, palavras: List[str]) -> None:
        for p in palavras:
            b = p.encode("utf-8")
            self._s.sendall(_tam(len(b)) + b)
        self._s.sendall(b"\x00")

    def _ler_exato(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                parte = self._s.recv(n - len(buf))
            except OSError as exc:
                raise RouterOSErro(f"conexao caiu ({exc.__class__.__name__})") from exc
            if not parte:
                raise RouterOSErro("conexao fechada pelo equipamento")
            buf += parte
        return buf

    def _ler_tam(self) -> int:
        c = self._ler_exato(1)[0]
        if c < 0x80:
            return c
        if c < 0xC0:
            return ((c & 0x3F) << 8) | self._ler_exato(1)[0]
        if c < 0xE0:
            return ((c & 0x1F) << 16) | int.from_bytes(self._ler_exato(2), "big")
        return ((c & 0x0F) << 24) | int.from_bytes(self._ler_exato(3), "big")

    def _frase(self) -> List[str]:
        out = []
        while True:
            n = self._ler_tam()
            if n == 0:
                return out
            out.append(self._ler_exato(n).decode("utf-8", "replace"))

    def _conversa(self, palavras: List[str], login: bool = False) -> List[Dict[str, str]]:
        if not login and not _comando_de_leitura(palavras):
            raise RouterOSErro(f"comando recusado (so leitura): {palavras[:1]}")
        self._enviar(palavras)
        linhas: List[Dict[str, str]] = []
        while True:
            f = self._frase()
            if not f:
                continue
            if f[0] == "!re":
                linhas.append(dict(w[1:].split("=", 1) for w in f[1:] if w.startswith("=") and "=" in w[1:]))
            elif f[0] in ("!trap", "!fatal"):
                msg = next((w.split("=", 2)[-1] for w in f[1:] if w.startswith("=message=")), "erro")
                raise RouterOSErro(("login recusado: " if login else "") + msg)
            elif f[0] == "!done":
                return linhas

    def ler(self, comando: str, *args: str) -> List[Dict[str, str]]:
        return self._conversa([comando, *args])
