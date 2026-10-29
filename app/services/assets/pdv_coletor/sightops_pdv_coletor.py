#!/usr/bin/env python3
"""Coletor do SightOps para o caixa (PDV). Roda NO caixa, Python 3.8, so stdlib.

Le os arquivos Espiao e Teclas do dia (/home/rpdv/frente/Cm/EspiaoDDMMAA.NNN)
e manda as linhas novas, numeradas, para o SightOps. Nao abre porta, nao baixa
video, nao interpreta nada: quem interpreta e o servidor.

Caixa sem Espiao (opcao da estacao desligada na retaguarda): le o CM do dia no
lugar dele. Do CM so vao as linhas que o servidor usa (MARCADORES) e o INSERT
do item vai cortado no comeco do VALUES: o CM tem 10 a 40 MB por dia.

- Posicao de leitura persistida: so avanca quando o servidor confirma.
- Meia-noite: continua lendo o arquivo de ontem ate ele parar de crescer
  (FECHAR_APOS segundos depois da virada) e passa para o de hoje.
- Sem rede: tenta de novo com espera crescente; nada se perde.
- Sinal de vida a cada HEARTBEAT segundos mesmo sem venda.

Configuracao: /etc/sightops-pdv/coletor.json
  {"url": "https://<sightops>/api/pdv/coletor/lote", "caixa": "<id>", "token": "pdv_...",
   "pasta": "/home/rpdv/frente/Cm", "estacao": 1, "fonte": "auto"}
  fonte: "auto" (Espiao se existir, senao CM), "espiao" ou "cm".
"""
from __future__ import print_function

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

VERSAO = "1.1.1"
CONFIG = os.environ.get("SIGHTOPS_PDV_CONFIG", "/etc/sightops-pdv/coletor.json")
ESTADO = os.environ.get("SIGHTOPS_PDV_ESTADO", "/var/lib/sightops-pdv/estado.json")
INTERVALO = 2.0          # s entre leituras
HEARTBEAT = 30.0         # s sem linha nova -> manda lote vazio
MAX_LINHAS = 2000        # por envio
MAX_BYTES = 1024 * 1024  # lidos por arquivo por ciclo
FECHAR_APOS = 600        # s depois da meia-noite para dar o arquivo de ontem por encerrado
ESPERA_MAX = 60.0        # s de espera maxima entre tentativas sem rede
ESPERA_ESPIAO = 300      # s depois da meia-noite antes de decidir que o dia e de CM
                         # (o gerador do Espiao, sightops_pdv_espiao.py, cria o dele aos 180 s)
ESPERA_GERADOR = 120     # s depois que o coletor liga, esperando o gerador criar o Espiao

# Linhas do CM que o servidor usa -- IGUAL a app/services/pdv_cm.py (um teste confere).
MARCADORES_CM = (
    "COMANDO ==> (",
    "Entrada Operador:",
    "ABRE CUPOM FISCAL: COO:",
    "ENTRADA DADOS:",
    "INSERT INTO venda",
    "ProcessaTeclaSubtotal:Inicio",
    "Pagamento Venda:Valor:",
    "AcFinal:mf",
    "FD_Desconto:",
    "Desconto SubTotal:",
    "Informe a Senha do Supervisor",
    "FINAL PAGAMENTO",
    "digo Supervisor:",
    "Supervisor OK:",
    "MostraMensagemItemNaoCadastrado",
)
TAM_VALUES = 320


def linha_cm(texto):
    """Linha do CM que vale mandar (None = descarta). INSERT vai cortado."""
    if not any(m in texto for m in MARCADORES_CM):
        return None
    i = texto.find("INSERT INTO venda")
    j = texto.find(" VALUES (", i) if i >= 0 else -1
    if j < 0:
        return texto
    k = texto.find(":", 9)  # 'HH:MM:SS.mmm:' -> o ':' depois dos milissegundos
    prefixo = texto[:k + 1] if 0 < k < i else ""
    return prefixo + "INSERT INTO venda VALUES (" + texto[j + 9:j + 9 + TAM_VALUES]


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def nome_arquivo(tipo, dia, estacao):
    return "%s%s.%03d" % (tipo, dia.strftime("%d%m%y"), int(estacao))


def carregar_json(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, obj):
    pasta = os.path.dirname(caminho)
    if pasta and not os.path.isdir(pasta):
        os.makedirs(pasta, exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def ler_novas(caminho, offset, seq, encerrado, max_bytes=MAX_BYTES, max_linhas=MAX_LINHAS):
    """(linhas [(seq, texto)], novo_offset, novo_seq). Linha sem fim (ainda sendo
    escrita) fica para depois, a menos que o arquivo esteja encerrado."""
    try:
        tam = os.path.getsize(caminho)
    except OSError:
        return [], offset, seq
    if tam < offset:  # arquivo encolheu: recomeca (o servidor ignora seq repetido)
        log("arquivo encolheu, relendo do inicio:", caminho)
        offset, seq = 0, 0
    if tam == offset:
        return [], offset, seq
    with open(caminho, "rb") as f:
        f.seek(offset)
        bruto = f.read(max_bytes)
    partes = bruto.split(b"\n")
    sobra = partes.pop()  # depois do ultimo \n
    linhas = []
    usado = 0
    for p in partes:
        if len(linhas) >= max_linhas:
            break
        usado += len(p) + 1
        seq += 1
        linhas.append((seq, p.rstrip(b"\r").decode("latin-1")))
    else:
        if encerrado and sobra and len(bruto) < max_bytes and len(linhas) < max_linhas:
            usado += len(sobra)
            seq += 1
            linhas.append((seq, sobra.rstrip(b"\r").decode("latin-1")))
    return linhas, offset + usado, seq


class Coletor(object):
    def __init__(self, cfg, estado_path=ESTADO, enviar=None, relogio=None):
        self.cfg = cfg
        self.pasta = cfg.get("pasta", "/home/rpdv/frente/Cm")
        self.estacao = int(cfg.get("estacao", 1))
        self.estado_path = estado_path
        self.estado = carregar_json(estado_path, {})
        self.enviar = enviar or self._enviar_http
        self.relogio = relogio or dt.datetime.now
        self.ultimo_envio = 0.0
        self.espera = INTERVALO
        # Gerador do Espiao instalado ao lado (sightops_pdv_espiao.py): sem Espiao do
        # dia, espera ele criar antes de cair para o CM (na instalacao os dois ligam
        # juntos e o coletor escolhia o CM um segundo antes do Espiao aparecer).
        self.gerador = cfg.get("gerar_espiao") is not False and os.path.exists(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "sightops_pdv_espiao.py"))
        self.inicio = time.time()

    # ------------------------------------------------------------ rede
    def _enviar_http(self, payload):
        corpo = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.cfg["url"], data=corpo, method="POST", headers={
            "Content-Type": "application/json",
            "X-Pdv-Caixa": self.cfg["caixa"],
            "X-Pdv-Token": self.cfg["token"],
            "User-Agent": "sightops-pdv-coletor/" + VERSAO,
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    # ------------------------------------------------------------ ciclo
    def _dias(self, agora):
        hoje = agora.date()
        ontem = hoje - dt.timedelta(days=1)
        segundos_hoje = agora.hour * 3600 + agora.minute * 60 + agora.second
        out = []
        for dia in (ontem, hoje):
            fonte = self._fonte(dia, dia == hoje and segundos_hoje < ESPERA_ESPIAO)
            for tipo in ("Teclas",) + ((fonte,) if fonte else ()):
                nome = nome_arquivo(tipo, dia, self.estacao)
                st = self.estado.get(nome) or {}
                if dia == ontem and (st.get("fim") or nome not in self.estado and segundos_hoje > FECHAR_APOS):
                    continue  # ontem ja terminado, ou coletor comecou hoje: nao manda dia velho
                encerrado = dia == ontem and segundos_hoje > FECHAR_APOS
                out.append((tipo, dia, nome, encerrado))
        return out

    def _fonte(self, dia, cedo):
        """'Espiao' ou 'CM' para o dia ('' = ainda nao da para saber). Depois de
        escolhida, a fonte fica ate o fim do dia (o servidor tambem nao mistura)."""
        forcada = str(self.cfg.get("fonte") or "auto").lower()
        if forcada == "espiao":
            return "Espiao"
        if forcada == "cm":
            return "CM"
        esp, cm = nome_arquivo("Espiao", dia, self.estacao), nome_arquivo("CM", dia, self.estacao)
        if esp in self.estado:
            return "Espiao"
        if cm in self.estado:
            return "CM"
        if os.path.exists(os.path.join(self.pasta, esp)):
            return "Espiao"
        if self.gerador and time.time() - self.inicio < ESPERA_GERADOR:
            return ""  # o gerador ainda vai criar o Espiao do dia
        if not cedo and os.path.exists(os.path.join(self.pasta, cm)):
            return "CM"  # na virada do dia o Espiao nasce uns segundos depois do CM
        return ""

    def ciclo(self):
        """Uma leitura + envio. Devolve quantas linhas foram aceitas (ou -1 em erro)."""
        agora = self.relogio()
        lotes, pendente, total = [], {}, 0
        for tipo, dia, nome, encerrado in self._dias(agora):
            st = self.estado.get(nome) or {"offset": 0, "seq": 0}
            caminho = os.path.join(self.pasta, nome)
            linhas, off, seq = ler_novas(caminho, st["offset"], st["seq"], encerrado,
                                         max_linhas=max(0, MAX_LINHAS - total))
            total += len(linhas)
            lidas = bool(linhas)
            if tipo == "CM":  # so o que o servidor usa; o seq continua o da linha no arquivo
                linhas = [(s, x) for s, x in ((s, linha_cm(t)) for s, t in linhas) if x is not None]
            if linhas:
                lotes.append({"arquivo": tipo, "dia": dia.isoformat(), "linhas": [[s, t] for s, t in linhas]})
            pendente[nome] = {"offset": off, "seq": seq, "fim": bool(encerrado and off >= self._tam(caminho)),
                              "chave": "%s/%s" % (tipo, dia.isoformat()), "ultimo": linhas[-1][0] if linhas else None,
                              "so_descartadas": lidas and not linhas}
        if not lotes and time.time() - self.ultimo_envio < HEARTBEAT:
            self._marcar_fim(pendente)
            return 0
        try:
            resp = self.enviar({"versao": VERSAO, "relogio": agora.strftime("%Y-%m-%d %H:%M:%S"), "lotes": lotes})
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.espera = min(ESPERA_MAX, max(INTERVALO, self.espera * 2))
            log("falha no envio (%s); nova tentativa em %.0f s" % (exc, self.espera))
            return -1
        aceito = (resp or {}).get("aceito") or {}
        for nome, p in pendente.items():
            if p["ultimo"] is None:
                continue
            if aceito.get(p["chave"]) == p["ultimo"]:
                self.estado[nome] = {"offset": p["offset"], "seq": p["seq"], "fim": False}
        self._marcar_fim(pendente)
        gravar_json(self.estado_path, self.estado)
        self.ultimo_envio = time.time()
        self.espera = INTERVALO
        return total

    def _marcar_fim(self, pendente):
        mudou = False
        for nome, p in pendente.items():
            # trecho do CM so com linhas descartadas: nada a confirmar, avanca aqui
            # (senao relia o mesmo trecho a cada ciclo ate aparecer linha util)
            if p.get("so_descartadas"):
                self.estado[nome] = {"offset": p["offset"], "seq": p["seq"], "fim": False}
                mudou = True
        for nome, p in pendente.items():
            st = self.estado.get(nome)
            if p["fim"] and p["ultimo"] is None and st is not None and not st.get("fim"):
                st["fim"] = True
                mudou = True
        # esquece arquivos de mais de 3 dias
        limite = (self.relogio().date() - dt.timedelta(days=3)).strftime("%y%m%d")
        for nome in list(self.estado):
            dd, mm, aa = nome[-10:-8], nome[-8:-6], nome[-6:-4]
            if (aa + mm + dd) < limite:
                del self.estado[nome]
                mudou = True
        if mudou:
            gravar_json(self.estado_path, self.estado)

    @staticmethod
    def _tam(caminho):
        try:
            return os.path.getsize(caminho)
        except OSError:
            return 0

    def rodar(self):
        log("coletor %s: caixa %s, pasta %s, estacao %03d" % (VERSAO, self.cfg.get("caixa"), self.pasta, self.estacao))
        while True:
            try:
                n = self.ciclo()
            except Exception as exc:  # nunca morre por um arquivo estranho
                log("erro inesperado:", repr(exc))
                n = -1
            time.sleep(self.espera if n < 0 else (0.2 if n >= MAX_LINHAS else INTERVALO))


def main():
    cfg = carregar_json(CONFIG, None)
    if not cfg or not all(cfg.get(k) for k in ("url", "caixa", "token")):
        log("configuracao ausente ou incompleta:", CONFIG)
        return 2
    Coletor(cfg).rodar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
