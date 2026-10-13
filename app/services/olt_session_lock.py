# -*- coding: utf-8 -*-
"""Serializa o acesso telnet a cada OLT ENTRE PROCESSOS -- nao so entre threads.

POR QUE ISTO EXISTE

A FiberHome AN5516 (e OLTs antigas em geral) aceitam UMA sessao no modo admin.
O `_admin_lock` do driver e um `threading.Lock`: serializa dentro de UM processo.
Mas quem bate na OLT sao processos/containers DIFERENTES e sem coordenacao:

  - a telemetria do app (`sightops-v3-api`),
  - o `olt-telegram-bot` (classe de telnet propria),
  - a CLI/diagnostico manual,
  - o provisionamento.

Cada um com o seu `threading.Lock`, que o outro nao enxerga. Duas sessoes caem
na OLT ao mesmo tempo, ela recusa/reenfileira, e a AN5516 trava a gerencia
(VLAN 100 / IP de gerencia param de responder). Foi o que derrubou a OLT da
Sierra (ver memoria sierra-olt-gerencia-satura-telnet).

A SOLUCAO

Um lock por ARQUIVO (`flock`), num diretorio compartilhado por volume entre todos
os containers que falam com OLT. `flock` e do kernel: vale ENTRE processos e
containers. A chave e o host da OLT -- OLTs diferentes nao se bloqueiam.

Todo caminho que abre telnet com a OLT (driver do app E o olt-telegram-bot) tem
que passar por aqui. O bot, por ser outro container, importa este modulo pelo
volume ou replica estas ~30 linhas; o compose monta `OLT_LOCK_DIR` nos dois.

Fallback: onde nao ha `fcntl` (Windows de desenvolvimento) o lock de processo
vira no-op e sobra o `threading.Lock` do driver -- em producao (Linux) o flock
sempre existe.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import time
from typing import Iterator

# Diretorio compartilhado por volume entre os containers que falam com a OLT.
LOCK_DIR = os.getenv("OLT_LOCK_DIR", "/var/lock/sightops-olt")


@contextlib.contextmanager
def olt_process_lock(host: str, timeout: float = 90.0, poll: float = 0.5) -> Iterator[bool]:
    """Garante sessao unica para `host` entre processos. Rende True se pegou o
    lock de verdade (Linux/flock), False se caiu no fallback sem flock.

    Levanta TimeoutError se outra sessao segura a OLT por mais de `timeout`.
    """
    try:
        import fcntl
    except ImportError:
        # Sem flock (Windows dev): nao serializa entre processos, mas nao quebra.
        yield False
        return

    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
    except OSError:
        # Diretorio indisponivel: melhor seguir sem o lock de processo do que
        # travar toda telemetria -- o lock de thread do driver ainda vale.
        yield False
        return

    chave = hashlib.sha1((host or "").encode("utf-8")).hexdigest()[:16]
    caminho = os.path.join(LOCK_DIR, "olt-%s.lock" % chave)
    fh = open(caminho, "a+")
    try:
        prazo = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= prazo:
                    raise TimeoutError(
                        "OLT %s ocupada por outra sessao do SightOps ha %.0fs. "
                        "Outro processo (telemetria, bot ou CLI) esta com a sessao." % (host, timeout)
                    )
                time.sleep(poll)
        try:
            try:
                fh.seek(0)
                fh.truncate()
                fh.write("%d %.0f\n" % (os.getpid(), time.time()))
                fh.flush()
            except OSError:
                pass
            yield True
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        fh.close()
