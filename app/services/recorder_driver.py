"""Driver de gravador: o que a Investigacao e a padronizacao precisam de um NVR/DVR.

Cobre quatro perguntas, em vez de cada tela reinventar o CGI do fabricante:
  1. o que esta gravado e onde teve movimento   -> indice()
  2. como assistir um horario passado            -> url_playback()
  3. o relogio do gravador bate com o servidor?  -> relogio()
  4. ele esta configurado para ser investigado?  -> diagnostico() / aplicar()

Provado no NVR Intelbras 10.10.9.120 (NVR4X-4KS2, firmware 4.000.00IB001.2) em
09/10/2026: o perfil abaixo foi aplicado a mao, lido de volta, e o indice passou a
marcar movimento nos 13 canais que estavam sem, sem nenhum buraco na gravacao
continua.

O PERFIL nunca troca gravacao continua por gravacao por movimento. A contínua
fica como esta; o movimento so ETIQUETA o trecho no indice (Flags=Event), e a
pre-gravacao puxa a etiqueta 10 s para tras para o comeco da cena nao escapar.

Hikvision: playback e relogio funcionam (provado em DS-7732NXI e DS-7632NXI);
indice e padronizacao ainda nao -- a busca ISAPI nao foi validada em equipamento.
Responde ErroDriver em vez de fingir.
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.services.recorder_xray import _base, _pedir, detectar_marca

FMT = "%Y-%m-%d %H:%M:%S"

# Perfil de Investigacao. Valores sao MINIMOS: o que ja esta acima fica.
PERFIL = {
    "movimento": True,       # MotionDetect ligado e gravando etiqueta no indice
    "pre_gravacao_s": 10,    # Record[N].PreRecord
    "pos_gravacao_s": 30,    # MotionDetect[N].EventHandler.RecordLatch
    "ntp": True,             # relogio do gravador e o que carimba a gravacao
    "ntp_servidor": "a.ntp.br",
    "codec": "H.264",        # navegador toca H.264 sem o servidor recodificar
}

# O gravador so aplica a PRIMEIRA tabela de cada setConfig e responde "OK" para
# o resto (visto no .120: a pre-gravacao de 15 canais e o NTP sumiram calados
# num lote misto). Por isso: um pedido por tabela, e sempre ler de volta.
_LOTE = 20


class ErroDriver(Exception):
    """Falha em linguagem de operacao."""


@dataclass
class Segmento:
    inicio: str
    fim: str
    tipo: str  # "continuo" | "movimento"
    tamanho: int = 0


@dataclass
class Mudanca:
    chave: str      # sem o prefixo "table.", pronto para o setConfig
    de: str
    para: str
    motivo: str


def _pares(texto: str) -> Dict[str, str]:
    saida: Dict[str, str] = {}
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if linha.startswith("table.") and "=" in linha:
            k, v = linha.split("=", 1)
            saida[k[len("table."):]] = v
    return saida


def _tabela(chave: str) -> str:
    return re.split(r"[\[.]", chave, maxsplit=1)[0]


def _indices(pares: Dict[str, str], prefixo: str, campo: str) -> Dict[int, str]:
    padrao = re.compile(rf"^{re.escape(prefixo)}\[(\d+)\]\.{re.escape(campo)}$")
    saida = {}
    for k, v in pares.items():
        m = padrao.match(k)
        if m:
            saida[int(m.group(1))] = v
    return saida


def _int(valor: Any, padrao: int = 0) -> int:
    try:
        return int(str(valor).strip())
    except Exception:
        return padrao


def parse_indice(texto: str) -> List[Segmento]:
    """Resposta do findNextFile -> segmentos. Flags=Event e o trecho com movimento."""
    itens: Dict[int, Dict[str, str]] = {}
    for linha in (texto or "").splitlines():
        m = re.match(r"items\[(\d+)\]\.(\w+)(\[\d+\])?=(.*)", linha.strip())
        if m:
            d = itens.setdefault(int(m.group(1)), {})
            # Flags vem como lista (Flags[0]=Event); o primeiro basta.
            d.setdefault(m.group(2), m.group(4))
    segs = []
    for i in sorted(itens):
        d = itens[i]
        if not d.get("StartTime") or not d.get("EndTime"):
            continue
        movimento = d.get("Flags") == "Event" or "VideoMotion" in (d.get("Events") or "")
        segs.append(Segmento(d["StartTime"], d["EndTime"], "movimento" if movimento else "continuo",
                             _int(d.get("Length"))))
    return segs


def diagnosticar_intelbras(pares: Dict[str, str], perfil: Dict[str, Any] = PERFIL
                           ) -> Tuple[List[Mudanca], List[str]]:
    """Compara a configuracao lida com o perfil. Funcao pura (testavel sem gravador).

    Devolve (mudancas, alertas). Alerta e o que precisa de olho humano e o
    driver NAO muda sozinho: canal sem gravacao continua, sensibilidade, etc.
    """
    mud: List[Mudanca] = []
    alertas: List[str] = []

    if perfil.get("movimento"):
        for i, v in sorted(_indices(pares, "MotionDetect", "Enable").items()):
            if v.lower() != "true":
                mud.append(Mudanca(f"MotionDetect[{i}].Enable", v, "true",
                                   f"canal {i + 1}: deteccao de movimento desligada"))
        for i, v in sorted(_indices(pares, "MotionDetect", "EventHandler.RecordEnable").items()):
            if v.lower() != "true":
                mud.append(Mudanca(f"MotionDetect[{i}].EventHandler.RecordEnable", v, "true",
                                   f"canal {i + 1}: movimento nao marca o indice"))
        alvo = int(perfil.get("pos_gravacao_s") or 0)
        for i, v in sorted(_indices(pares, "MotionDetect", "EventHandler.RecordLatch").items()):
            if _int(v) < alvo:
                mud.append(Mudanca(f"MotionDetect[{i}].EventHandler.RecordLatch", v, str(alvo),
                                   f"canal {i + 1}: pos-gravacao curta picota a cena"))

    alvo = int(perfil.get("pre_gravacao_s") or 0)
    for i, v in sorted(_indices(pares, "Record", "PreRecord").items()):
        if _int(v) < alvo:
            mud.append(Mudanca(f"Record[{i}].PreRecord", v, str(alvo),
                               f"canal {i + 1}: pre-gravacao curta perde o comeco da cena"))

    if perfil.get("ntp") and "NTP.Enable" in pares:
        if not (pares.get("NTP.Address") or "").strip():
            mud.append(Mudanca("NTP.Address", "", perfil["ntp_servidor"], "NTP sem servidor"))
        if pares["NTP.Enable"].lower() != "true":
            mud.append(Mudanca("NTP.Enable", pares["NTP.Enable"], "true",
                               "relogio sem sincronizar: o horario gravado escorrega"))

    codec = str(perfil.get("codec") or "")
    if codec:
        trocou = 0
        for fluxo in ("MainFormat", "ExtraFormat"):
            for i, v in sorted(_indices(pares, "Encode", f"{fluxo}[0].Video.Compression").items()):
                # H.264, H.264B, H.264H sao H.264 (so muda o perfil); nao mexer.
                if v and not v.upper().startswith(codec.upper()):
                    trocou += 1
                    mud.append(Mudanca(f"Encode[{i}].{fluxo}[0].Video.Compression", v, codec,
                                       f"canal {i + 1}: {v} nao toca no navegador sem recodificar"))
        if trocou:
            alertas.append("Troca para H.264 aumenta o tamanho do video (ate ~2x): a retencao "
                           "em disco do gravador cai. Conferir os dias gravados depois.")

    # Gravacao continua: so avisa. Mudar agenda e decisao do cliente (retencao).
    sem_continua = []
    for i in sorted(_indices(pares, "Record", "PreRecord")):
        dias_ok = 0
        for dia in range(7):
            for faixa in range(6):
                v = pares.get(f"Record[{i}].TimeSection[{dia}][{faixa}]", "")
                partes = v.split()
                if len(partes) == 2 and _int(partes[0]) & 1 and partes[1] == "00:00:00-24:00:00":
                    dias_ok += 1
                    break
        if dias_ok < 7:
            sem_continua.append(str(i + 1))
    if sem_continua:
        alertas.append("Sem gravacao continua 24h em todos os dias nos canais "
                       f"{', '.join(sem_continua)} -- nao alterado (afeta retencao).")
    return mud, alertas


class Gravador:
    """Um gravador aberto: marca detectada e base alcancavel (vnat se isolado).

    `pedir` existe para os testes trocarem a rede por um gravador falso.
    """

    def __init__(self, host: str, user: str, password: str, porta: Any = 80,
                 connector_id: str = "", pedir: Optional[Callable[[str], Tuple[Optional[int], str]]] = None,
                 marca: str = ""):
        if not host or not password:
            raise ErroDriver("sem host ou sem senha do gravador")
        self.host = host
        self.user = user or "admin"
        self.password = password
        self.base = _base(host, porta, connector_id)
        self._pedir = pedir or (lambda url: _pedir(url, self.user, self.password))
        self.marca = marca or detectar_marca(self.base, self.user, self.password)

    @property
    def alcance(self) -> str:
        return self.base.split("://", 1)[1].split(":", 1)[0]

    def _get(self, caminho: str) -> str:
        cod, txt = self._pedir(f"{self.base}{caminho}")
        if cod in (401, 403):
            raise ErroDriver("o gravador recusou usuario ou senha")
        if not cod or cod >= 400:
            raise ErroDriver(f"o gravador nao respondeu ({cod or txt[:80]})")
        return txt

    def _so_intelbras(self, o_que: str) -> None:
        if self.marca != "intelbras":
            raise ErroDriver(f"{o_que} ainda nao esta disponivel para {self.marca}")

    # --------------------------------------------------------------- leitura
    def relogio(self) -> Dict[str, Any]:
        agora = datetime.now()
        if self.marca == "hikvision":
            txt = self._get("/ISAPI/System/time")
            m = re.search(r"<localTime>(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)", txt)
            bruto = m.group(1).replace("T", " ") if m else ""
        else:
            bruto = self._get("/cgi-bin/global.cgi?action=getCurrentTime").strip().split("=", 1)[-1]
        try:
            do_gravador = datetime.strptime(bruto, FMT)
        except ValueError as exc:
            raise ErroDriver(f"relogio ilegivel: {bruto[:40]!r}") from exc
        return {"gravador": do_gravador.strftime(FMT), "servidor": agora.strftime(FMT),
                "diferenca_s": int((do_gravador - agora).total_seconds())}

    def ler_config(self, *tabelas: str) -> Dict[str, str]:
        self._so_intelbras("leitura de configuracao")
        pares: Dict[str, str] = {}
        for nome in tabelas:
            pares.update(_pares(self._get(f"/cgi-bin/configManager.cgi?action=getConfig&name={nome}")))
        return pares

    def indice(self, canal: int, inicio: datetime, fim: datetime) -> List[Segmento]:
        """Arquivos gravados no intervalo, etiquetados continuo/movimento."""
        self._so_intelbras("indice de gravacao")
        txt = self._get("/cgi-bin/mediaFileFind.cgi?action=factory.create")
        m = re.search(r"result=(\d+)", txt)
        if not m:
            raise ErroDriver("o gravador nao abriu a busca no indice")
        obj = m.group(1)
        segs: List[Segmento] = []
        try:
            self._get(f"/cgi-bin/mediaFileFind.cgi?action=findFile&object={obj}"
                      f"&condition.Channel={int(canal)}&condition.StartTime={quote(inicio.strftime(FMT))}"
                      f"&condition.EndTime={quote(fim.strftime(FMT))}&condition.Types[0]=dav")
            for _ in range(50):  # teto: 5000 arquivos
                txt = self._get(f"/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={obj}&count=100")
                pagina = parse_indice(txt)
                segs.extend(pagina)
                if len(pagina) < 100:
                    break
        finally:
            for acao in ("close", "destroy"):
                try:
                    self._get(f"/cgi-bin/mediaFileFind.cgi?action={acao}&object={obj}")
                except ErroDriver:
                    pass
        return segs

    def url_playback(self, canal: int, inicio: datetime, fim: datetime, porta_rtsp: int = 554) -> str:
        """RTSP de um horario passado. Provado nas duas marcas (relogio da imagem conferido)."""
        cred = f"{quote(self.user, safe='')}:{quote(self.password, safe='')}"
        if self.marca == "hikvision":
            # Hikvision interpreta o "Z" como hora LOCAL do gravador (conferido).
            caminho = (f"/Streaming/tracks/{int(canal)}01?starttime={inicio:%Y%m%dT%H%M%SZ}"
                       f"&endtime={fim:%Y%m%dT%H%M%SZ}")
        else:
            caminho = (f"/cam/playback?channel={int(canal)}&starttime={inicio:%Y_%m_%d_%H_%M_%S}"
                       f"&endtime={fim:%Y_%m_%d_%H_%M_%S}")
        return f"rtsp://{cred}@{self.alcance}:{int(porta_rtsp)}{caminho}"

    # ---------------------------------------------------------- padronizacao
    _TABELAS = ("MotionDetect", "Record", "NTP", "Encode")

    def diagnostico(self, perfil: Dict[str, Any] = PERFIL) -> Dict[str, Any]:
        self._so_intelbras("padronizacao")
        pares = self.ler_config(*self._TABELAS)
        if not pares:
            raise ErroDriver("o gravador nao devolveu a configuracao")
        mudancas, alertas = diagnosticar_intelbras(pares, perfil)
        try:
            alertas_relogio = self.relogio()
        except ErroDriver:
            alertas_relogio = None
        if alertas_relogio and abs(alertas_relogio["diferenca_s"]) > 60:
            alertas.append(f"Relogio do gravador {alertas_relogio['diferenca_s']:+d} s em relacao ao servidor.")
        return {"host": self.host, "marca": self.marca, "perfil": perfil,
                "canais": len(_indices(pares, "MotionDetect", "Enable")),
                "mudancas": [asdict(m) for m in mudancas], "alertas": alertas,
                "relogio": alertas_relogio}

    def aplicar(self, mudancas: List[Dict[str, str]], backup_dir: Optional[Path] = None) -> Dict[str, Any]:
        """Aplica, uma tabela por pedido, e confere lendo de volta.

        So devolve ok=True se TODAS as chaves estiverem com o valor novo na
        releitura -- o "OK" do setConfig nao prova nada.
        """
        self._so_intelbras("padronizacao")
        if not mudancas:
            return {"ok": True, "aplicadas": 0, "nao_pegaram": [], "backup": ""}
        tabelas = sorted({_tabela(m["chave"]) for m in mudancas})
        antes = self.ler_config(*tabelas)
        backup = ""
        if backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            arq = backup_dir / f"{self.host.replace(':', '_')}-{datetime.now():%Y%m%d-%H%M%S}.txt"
            arq.write_text("\n".join(f"table.{k}={v}" for k, v in sorted(antes.items())), encoding="utf-8")
            backup = str(arq)

        recusas: List[str] = []
        for tabela in tabelas:
            grupo = [m for m in mudancas if _tabela(m["chave"]) == tabela]
            for i in range(0, len(grupo), _LOTE):
                lote = grupo[i:i + _LOTE]
                qs = "&".join(f"{quote(m['chave'], safe='[]._')}={quote(str(m['para']), safe='')}" for m in lote)
                try:
                    txt = self._get(f"/cgi-bin/configManager.cgi?action=setConfig&{qs}")
                    if not txt.strip().upper().startswith("OK"):
                        recusas.append(f"{tabela}: {txt.strip()[:80]}")
                except ErroDriver as exc:
                    recusas.append(f"{tabela}: {exc}")
                time.sleep(0.3)

        depois = self.ler_config(*tabelas)
        nao_pegaram = [m["chave"] for m in mudancas if depois.get(m["chave"]) != str(m["para"])]
        return {"ok": not nao_pegaram, "aplicadas": len(mudancas) - len(nao_pegaram),
                "nao_pegaram": nao_pegaram, "recusas": recusas, "backup": backup}
