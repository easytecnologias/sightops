#!/usr/bin/env python3
"""Gerador do Espiao no caixa que nao grava o seu (SightOps). Python 3.8, so stdlib.

O programa do caixa so grava o EspiaoDDMMAA.NNN quando a estacao tem o Espiao
ligado. Sem ele, este servico escreve o mesmo arquivo, na mesma pasta e no
mesmo formato, a partir do CM e do Teclas do dia (pdv_cm.py, ao lado). Quem le
o Espiao (coletor do SightOps, ponte do gravador, auditor) nao percebe diferenca.

Seguranca (o caixa e do cliente e esta vendendo):
- So le o CM e o Teclas. Nao toca em nenhum outro arquivo do caixa.
- So cria o Espiao do dia se ele nao existir ESPERA_S depois da meia-noite (o
  caixa cria o dele a 00:00). Arquivo que nao comeca com MARCA nao e nosso:
  nunca escreve nele.
- Se o arquivo mudar de tamanho sem ser por ele (o caixa passou a gravar o
  Espiao), para de escrever naquele dia.
- Reiniciou no meio do dia: rele o CM e o Teclas do comeco e so acrescenta o
  que ainda nao esta no arquivo.

Configuracao: a do coletor (/etc/sightops-pdv/coletor.json: pasta, estacao).
"""
from __future__ import print_function

import collections
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pdv_cm  # no caixa: vai junto, na mesma pasta
except ImportError:  # no repositorio (testes): o mesmo arquivo do servidor
    from app.services import pdv_cm

VERSAO = "1.0.0"
CONFIG = os.environ.get("SIGHTOPS_PDV_CONFIG", "/etc/sightops-pdv/coletor.json")
MARCA = "---------- SightOps: Espiao gerado do CM ----------"
ESPERA_S = 180       # s depois da meia-noite antes de criar o Espiao do dia
ATRASO_S = 3.0       # s: so escreve o que tem mais de 3 s (CM e Teclas chegam em paralelo)
INTERVALO = 1.0
MAX_BYTES = 4 * 1024 * 1024  # lidos por arquivo por ciclo


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def nome(tipo, dia, estacao):
    return "%s%s.%03d" % (tipo, dia.strftime("%d%m%y"), int(estacao))


def nosso(caminho):
    try:
        with open(caminho, "rb") as f:
            return MARCA.encode("latin-1") in f.read(200)
    except OSError:
        return False


class Leitor(object):
    """Linhas completas novas de um arquivo do PDV (a ultima, sem fim, espera)."""

    def __init__(self, caminho):
        self.caminho, self.offset, self.n = caminho, 0, 0
        self.atrasado = False   # ainda tem o que ler (relendo o dia depois de reiniciar)
        self.ate = ""           # hora (HH:MM:SS.mmm) da ultima linha lida

    def novas(self):
        try:
            tam = os.path.getsize(self.caminho)
        except OSError:
            return []
        if tam < self.offset:
            self.offset = 0  # encolheu: o servidor e a contagem cuidam de repeticao
        if tam == self.offset:
            self.atrasado = False
            return []
        with open(self.caminho, "rb") as f:
            f.seek(self.offset)
            bruto = f.read(MAX_BYTES)
        partes = bruto.split(b"\n")
        partes.pop()  # depois do ultimo \n: ainda sendo escrita
        out = []
        for p in partes:
            self.offset += len(p) + 1
            self.n += 1
            out.append((self.n, p.rstrip(b"\r").decode("latin-1")))
        self.atrasado = self.offset < tam
        for _, t in reversed(out):
            if len(t) >= 12 and t[2] == ":" and t[5] == ":":
                self.ate = t[:12] if t[8] == "." else t[:8] + ".999"
                break
        return out


class Dia(object):
    """Um dia de um caixa: le CM + Teclas e escreve o Espiao em ordem de tempo."""

    def __init__(self, pasta, estacao, dia):
        self.dia = dia
        self.espiao = os.path.join(pasta, nome("Espiao", dia, estacao))
        self.cm = Leitor(os.path.join(pasta, nome("CM", dia, estacao)))
        self.teclas = Leitor(os.path.join(pasta, nome("Teclas", dia, estacao)))
        self.conv, self.tec = pdv_cm.ConversorCM(), pdv_cm.TeclasEspiao()
        self.fila = []      # (ms, origem, n, k, linha) esperando ATRASO_S
        self.tam = None     # tamanho do Espiao que nos escrevemos (None = ainda nao e nosso)
        self.parado = ""    # motivo de nao escrever neste dia
        self.ja_escrito = collections.Counter()  # ao reiniciar: o que o arquivo ja tem

    # ------------------------------------------------------------ dono do arquivo
    def assumir(self, agora):
        """True se este dia e nosso para escrever."""
        if self.parado:
            return False
        if self.tam is not None:
            return True
        if os.path.exists(self.espiao):
            if not nosso(self.espiao):
                self.parado = "o caixa grava o proprio Espiao"
                log(self.espiao, ":", self.parado, "- nada a fazer hoje")
                return False
            # reiniciou no meio do dia: o que ja esta no arquivo nao se repete
            with open(self.espiao, "rb") as f:
                for b in f:
                    self.ja_escrito[b.rstrip(b"\r\n").decode("latin-1")] += 1
            self.tam = os.path.getsize(self.espiao)
            log("continuando", self.espiao, "(%d linhas)" % sum(self.ja_escrito.values()))
            return True
        segundos = agora.hour * 3600 + agora.minute * 60 + agora.second
        if self.dia == agora.date() and segundos < ESPERA_S:
            return False  # o caixa ainda pode criar o dele
        if not os.path.exists(self.cm.caminho):
            return False  # caixa fechado: sem CM, sem Espiao
        with open(self.espiao, "xb") as f:  # 'x': se alguem criou agora, falha e nao sobrescreve
            f.write(("00:00:00%s\r\n" % MARCA).encode("latin-1"))
        self.tam = os.path.getsize(self.espiao)
        log("criado", self.espiao)
        return True

    # ------------------------------------------------------------ ciclo
    def ciclo(self, agora, final=False):
        try:
            if not self.assumir(agora):
                return 0
        except OSError as exc:
            log("nao deu para criar", self.espiao, exc)
            return 0
        for n, texto in self.cm.novas():
            for k, (ms, l) in enumerate(self.conv.linha_com_tempo(texto)):
                self.fila.append((ms, 0, n, k, l))
        for n, texto in self.teclas.novas():
            for k, (ms, l) in enumerate(self.tec.linha_com_tempo(texto)):
                self.fila.append((ms, 1, n, k, l))
        if final:
            for k, (ms, l) in enumerate(self.conv.fim()):
                self.fila.append((ms, 0, 10 ** 9, k, l))
            corte = "99"
        else:
            if not self.cm.atrasado and self.dia == agora.date():
                # ultimo cupom e o caixa parou: fecha sem esperar a proxima linha do CM
                for k, (ms, l) in enumerate(self.conv.vencer(agora.hour * 3600 + agora.minute * 60 + agora.second)):
                    self.fila.append((ms, 0, 10 ** 9, k, l))
            limite = agora - dt.timedelta(seconds=ATRASO_S)
            corte = "24" if limite.date() > self.dia else limite.strftime("%H:%M:%S.%f")[:12]
            # relendo o dia: nada passa de onde o arquivo mais atrasado ja foi lido
            for lt in (self.cm, self.teclas):
                if lt.atrasado and lt.ate:
                    corte = min(corte, lt.ate)
        self.fila.sort()
        sai = [e for e in self.fila if e[0] <= corte]
        self.fila = self.fila[len(sai):]
        linhas = []
        for e in sai:
            if self.ja_escrito[e[4]] > 0:
                self.ja_escrito[e[4]] -= 1
                continue
            linhas.append(e[4])
        return self._escrever(linhas)

    def _escrever(self, linhas):
        if not linhas:
            return 0
        try:
            if os.path.getsize(self.espiao) != self.tam:
                self.parado = "o arquivo mudou sem ser por nos (o caixa passou a gravar o Espiao?)"
                log(self.espiao, ":", self.parado, "- parei de escrever hoje")
                return 0
        except OSError:
            self.parado = "o arquivo sumiu"
            log(self.espiao, ":", self.parado)
            return 0
        dados = "".join(l + "\r\n" for l in linhas).encode("latin-1", "replace")
        with open(self.espiao, "ab") as f:
            f.write(dados)
            f.flush()
        self.tam += len(dados)
        return len(linhas)


def main():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        log("configuracao ausente:", CONFIG)
        return 2
    if cfg.get("gerar_espiao") is False:
        log("gerar_espiao desligado no", CONFIG)
        while True:
            time.sleep(3600)
    pasta, estacao = cfg.get("pasta", "/home/rpdv/frente/Cm"), int(cfg.get("estacao", 1))
    log("gerador do Espiao %s: pasta %s, estacao %03d" % (VERSAO, pasta, estacao))
    atual = None
    while True:
        agora = dt.datetime.now()
        try:
            if atual is None or atual.dia != agora.date():
                if atual is not None:
                    atual.ciclo(agora, final=True)  # termina o de ontem
                atual = Dia(pasta, estacao, agora.date())
            atual.ciclo(agora)
        except Exception as exc:  # nunca morre por um arquivo estranho
            log("erro inesperado:", repr(exc))
        time.sleep(INTERVALO)


if __name__ == "__main__":
    sys.exit(main())
