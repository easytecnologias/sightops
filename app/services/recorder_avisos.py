"""Avisos do gravador com correcao: o "Avisos e correcoes" da tela do gravador.

Cada aviso diz o que foi LIDO, o que isso causa e, quando da para corrigir,
exatamente o que muda (chave, valor atual, valor novo). O valor novo nunca vem
do navegador: `corrigir()` le o gravador de novo, remonta o aviso e aplica so
o que ainda esta fora -- equipamento de cliente e vivo, e a tela pode estar
velha.

Toda correcao vira um REGISTRO (json por tenant) com os valores de antes. E
dele que sai o "Desfazer" e, depois, o historico do gravador.

Intelbras primeiro: e a marca em que a leitura e a escrita de configuracao
foram provadas (ver recorder_driver). Hikvision so tem o relogio aqui.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from app.services.recorder_driver import (
    FMT, PERFIL, ErroDriver, Gravador, _indices, _int, diagnosticar_intelbras,
)

# Diferenca de relogio que vira aviso. Abaixo disso e ruido de leitura.
RELOGIO_TOLERANCIA_S = 60
DIAS = 7


def _faixas(nums: List[int]) -> str:
    """[1,2,3,5,9,10] -> '01–03, 05, 09–10'"""
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        a, b = f"{nums[i]:02d}", f"{nums[j]:02d}"
        out.append(a if i == j else f"{a}–{b}")
        i = j + 1
    return ", ".join(out)


def _canal_da_chave(chave: str) -> Optional[int]:
    m = re.match(r"\w+\[(\d+)\]", chave)
    return int(m.group(1)) + 1 if m else None


def _grupo(chave: str) -> str:
    if chave.startswith("NTP."):
        return "ntp"
    if chave.startswith("Encode["):
        return "codec"
    if ".Enable" in chave and chave.startswith("MotionDetect[") and "EventHandler" not in chave:
        return "movimento"
    if "EventHandler.RecordEnable" in chave:
        return "movimento"
    if "RecordLatch" in chave or "PreRecord" in chave:
        return "pre_pos"
    if "TimeSection" in chave:
        return "continua"
    return "outro"


def _sem_continua(pares: Dict[str, str]) -> List[Dict[str, str]]:
    """Mudancas para gravacao continua 24 h nos canais que nao tem.

    Mexe so na faixa 0 de cada dia, somando o bit de gravacao continua (1) ao
    que ja estava: quem gravava por movimento continua etiquetando.
    """
    mud = []
    for i in sorted(_indices(pares, "Record", "PreRecord")):
        dias_ok = 0
        for dia in range(DIAS):
            for faixa in range(6):
                partes = pares.get(f"Record[{i}].TimeSection[{dia}][{faixa}]", "").split()
                if len(partes) == 2 and _int(partes[0]) & 1 and partes[1] == "00:00:00-24:00:00":
                    dias_ok += 1
                    break
        if dias_ok == DIAS:
            continue
        for dia in range(DIAS):
            chave = f"Record[{i}].TimeSection[{dia}][0]"
            antes = pares.get(chave, "")
            mascara = _int((antes.split() or ["0"])[0]) | 1
            mud.append({"chave": chave, "de": antes, "para": f"{mascara} 00:00:00-24:00:00"})
    return mud


def _sem_perda_video(pares: Dict[str, str], com_camera: Optional[set]) -> List[Dict[str, str]]:
    """Canais COM camera sem alarme de perda de video. Canal livre fica de
    fora: ligar nele dispararia o alarme o tempo todo."""
    if not com_camera:
        return []
    mud = []
    for i, v in sorted(_indices(pares, "LossDetect", "Enable").items()):
        if (i + 1) in com_camera and v.lower() != "true":
            mud.append({"chave": f"LossDetect[{i}].Enable", "de": v, "para": "true"})
    return mud


def montar_avisos(pares: Dict[str, str], relogio: Optional[Dict[str, Any]] = None,
                  perfil: Dict[str, Any] = PERFIL, com_camera: Optional[set] = None) -> List[Dict[str, Any]]:
    """Funcao pura: configuracao lida (+ relogio, canais com camera) -> avisos."""
    mudancas, _alertas = diagnosticar_intelbras(pares, perfil)
    grupos: Dict[str, List[Dict[str, str]]] = {}
    for m in mudancas:
        d = {"chave": m.chave, "de": m.de, "para": m.para}
        grupos.setdefault(_grupo(m.chave), []).append(d)
    cont = _sem_continua(pares)
    if cont:
        grupos["continua"] = cont

    avisos: List[Dict[str, Any]] = []

    def canais(lista):
        return sorted({c for c in (_canal_da_chave(x["chave"]) for x in lista) if c})

    if relogio and abs(int(relogio.get("diferenca_s") or 0)) > RELOGIO_TOLERANCIA_S:
        dif = int(relogio["diferenca_s"])
        m, s = divmod(abs(dif), 60)
        h, m = divmod(m, 60)
        txt = (f"{h} h " if h else "") + f"{m} min {s} s"
        avisos.append({
            "id": "relogio", "nivel": "erro",
            "titulo": f"Relógio {txt} {'adiantado' if dif > 0 else 'atrasado'}",
            "lido": f"Hora do gravador {relogio['gravador'][11:]}, hora do servidor {relogio['servidor'][11:]}.",
            "causa": "A hora carimbada na gravação está errada: procurar um fato pelo horário devolve o trecho errado.",
            "mudancas": [{"o": "Hora agora", "de": relogio["gravador"], "para": "hora do servidor"}],
            "confirmar": "Acertar a hora agora", "seguro": True,
            "alerta": ("Hora voltando para trás faz o gravador ter dois trechos com o mesmo horário "
                       "nesse intervalo." if dif > 0 else ""),
        })

    perda = _sem_perda_video(pares, com_camera)
    if perda:
        cs = canais(perda)
        avisos.append({
            "id": "perda_video", "nivel": "erro",
            "titulo": f"{len(cs)} canal(is) não avisam se a câmera cair",
            "lido": f"Alarme de perda de vídeo desligado nos canais {_faixas(cs)}, que têm câmera.",
            "causa": "A câmera pode sumir sem gerar evento nenhum: ninguém fica sabendo até precisar do gravado.",
            "mudancas": [{"o": f"Canais {_faixas(cs)} · perda de vídeo", "de": "sem aviso", "para": "avisa"}],
            "confirmar": f"Ligar em {len(cs)} canal(is)", "seguro": True, "alerta": "",
            "_mudancas": perda,
        })

    if grupos.get("ntp"):
        lista = grupos["ntp"]
        avisos.append({
            "id": "ntp", "nivel": "erro", "titulo": "Relógio sem sincronizar (NTP)",
            "lido": "; ".join(f"{x['chave']} = {x['de'] or '(vazio)'}" for x in lista) + ".",
            "causa": "O relógio anda sozinho e a hora da gravação escorrega com o tempo.",
            "mudancas": [{"o": x["chave"], "de": x["de"] or "(vazio)", "para": x["para"], "chave": x["chave"]} for x in lista],
            "confirmar": "Ligar NTP", "seguro": True, "alerta": "",
        })

    if grupos.get("continua"):
        lista = grupos["continua"]
        cs = canais(lista)
        avisos.append({
            "id": "continua", "nivel": "erro",
            "titulo": f"{len(cs)} canal(is) sem gravação contínua 24 h",
            "lido": f"Agenda de gravação sem 24 h contínuas em todos os dias nos canais {_faixas(cs)}.",
            "causa": "Fora da agenda nada é gravado. O ao vivo mostra a câmera normal, então ninguém percebe até precisar do gravado.",
            "mudancas": [{"o": f"Canais {_faixas(cs)} · agenda", "de": "parcial ou vazia", "para": "contínua 24 h, todos os dias"}],
            "confirmar": "Ligar gravação contínua", "seguro": False,
            "alerta": "Gravar 24 h ocupa mais disco: a retenção (dias guardados) do gravador cai.",
            "_mudancas": lista,
        })

    if grupos.get("movimento"):
        lista = grupos["movimento"]
        cs = canais(lista)
        avisos.append({
            "id": "movimento", "nivel": "aviso",
            "titulo": f"{len(cs)} canal(is) sem detecção de movimento no índice",
            "lido": f"Detecção de movimento desligada ou sem marcar a gravação nos canais {_faixas(cs)}.",
            "causa": "A Investigação e as Gravações não acham os trechos com movimento desses canais.",
            "mudancas": [{"o": f"Canais {_faixas(cs)} · detecção de movimento", "de": "desligada", "para": "ligada e marcando o índice"}],
            "confirmar": f"Ligar em {len(cs)} canal(is)", "seguro": True, "alerta": "",
            "_mudancas": lista,
        })

    if grupos.get("pre_pos"):
        lista = grupos["pre_pos"]
        cs = canais(lista)
        avisos.append({
            "id": "pre_pos", "nivel": "aviso",
            "titulo": f"Pré e pós-gravação curtas em {len(cs)} canal(is)",
            "lido": f"Abaixo de {perfil['pre_gravacao_s']} s antes / {perfil['pos_gravacao_s']} s depois do movimento nos canais {_faixas(cs)}.",
            "causa": "O trecho com movimento começa depois da cena e acaba antes dela terminar.",
            "mudancas": [{"o": f"Canais {_faixas(cs)} · pré / pós-gravação", "de": "curtas",
                          "para": f"{perfil['pre_gravacao_s']} s / {perfil['pos_gravacao_s']} s"}],
            "confirmar": "Ajustar", "seguro": True, "alerta": "",
            "_mudancas": lista,
        })

    if grupos.get("codec"):
        lista = grupos["codec"]
        cs = canais(lista)
        de = sorted({x["de"] for x in lista})
        avisos.append({
            "id": "codec", "nivel": "aviso",
            "titulo": f"{len(cs)} canal(is) em {'/'.join(de)}",
            "lido": f"Compressão {'/'.join(de)} nos canais {_faixas(cs)}.",
            "causa": "O navegador não toca esse vídeo: o SightOps recodifica e o gravado demora mais para abrir.",
            "mudancas": [{"o": f"Canais {_faixas(cs)} · codec", "de": "/".join(de), "para": perfil["codec"]}],
            "confirmar": f"Trocar para {perfil['codec']}", "seguro": False,
            "alerta": "H.264 ocupa até 2× mais disco: a retenção do gravador pode cair à metade.",
            "_mudancas": lista,
        })

    for a in avisos:
        if "_mudancas" not in a:
            a["_mudancas"] = [{"chave": x["chave"], "de": x["de"], "para": x["para"]}
                              for x in a["mudancas"] if x.get("chave")]
        # Canais do aviso (1..N): a tela marca o mosaico com isso ("NAO GRAVA").
        a["canais"] = canais(a["_mudancas"])
    return avisos


def _publico(aviso: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in aviso.items() if not k.startswith("_")}


_TABELAS_AVISOS = Gravador._TABELAS + ("LossDetect",)


def canais_com_camera(g: Gravador) -> Optional[set]:
    """Canais (1..N) que tem camera, pelo getCameraAll. None se nao der para ler."""
    from app.services.recorder_xray import _endereco_de_canal
    try:
        txt = g._get("/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll")
    except ErroDriver:
        return None
    cams: Dict[int, Dict[str, str]] = {}
    for idx, chave, valor in re.findall(r"camera\[(\d+)\]\.([^=\r\n]+)=([^\r\n]*)", txt):
        cams.setdefault(int(idx), {})[chave.strip()] = valor.strip()
    return {i + 1 for i, c in cams.items()
            if str(c.get("Type", "")).lower() != "compose" and _endereco_de_canal(c.get("DeviceInfo.Address"))}


def _ler(g: Gravador):
    pares = g.ler_config(*_TABELAS_AVISOS)
    if not pares:
        raise ErroDriver("o gravador nao devolveu a configuracao")
    try:
        relogio = g.relogio()
    except ErroDriver:
        relogio = None
    return pares, relogio, canais_com_camera(g)


def avisos_do_gravador(g: Gravador) -> Dict[str, Any]:
    if g.marca != "intelbras":
        try:
            relogio = g.relogio()
        except ErroDriver:
            relogio = None
        avisos = montar_avisos({}, relogio) if relogio else []
        # Sem leitura de configuracao nesta marca: so o relogio, e sem correcao
        # (a escrita de hora na Hikvision nao foi provada em equipamento).
        for a in avisos:
            a["seguro"] = False
            a["manual"] = True
        return {"marca": g.marca, "avisos": [_publico(a) for a in avisos], "parcial": True}
    pares, relogio, com_camera = _ler(g)
    return {"marca": g.marca, "avisos": [_publico(a) for a in montar_avisos(pares, relogio, com_camera=com_camera)],
            "parcial": False, "relogio": relogio}


# ------------------------------------------------------------------ registros
def _registros_dir(base: Path) -> Path:
    d = base / "registros"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gravar_registro(base: Path, reg: Dict[str, Any]) -> None:
    (_registros_dir(base) / f"{reg['id']}.json").write_text(
        json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def ler_registro(base: Path, reg_id: str) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{12}", reg_id or ""):
        raise ErroDriver("registro invalido")
    arq = _registros_dir(base) / f"{reg_id}.json"
    if not arq.exists():
        raise ErroDriver("registro nao encontrado")
    return json.loads(arq.read_text(encoding="utf-8"))


def _mesmo_gravador(reg: Dict[str, Any], host: str, conector: str) -> bool:
    # Host sozinho nao basta: o mesmo IP aparece em sites diferentes do mesmo
    # cliente, atras de conectores diferentes.
    return reg.get("host") == host and str(reg.get("conector") or "") == str(conector or "")


def registros_do_host(base: Path, host: str, limite: int = 50, conector: str = "") -> List[Dict[str, Any]]:
    out = []
    for arq in _registros_dir(base).glob("*.json"):
        try:
            r = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _mesmo_gravador(r, host, conector):
            r.pop("backup", None)   # caminho interno do servidor nao vai para a tela
            out.append(r)
    out.sort(key=lambda r: r.get("quando", ""), reverse=True)
    return out[:limite]


def _acertar_relogio(g: Gravador) -> Dict[str, Any]:
    if g.marca != "intelbras":
        raise ErroDriver(f"acertar a hora ainda nao esta disponivel para {g.marca}")
    agora = datetime.now().strftime(FMT)
    txt = g._get(f"/cgi-bin/global.cgi?action=setCurrentTime&time={quote(agora)}")
    if not txt.strip().upper().startswith("OK"):
        raise ErroDriver(f"o gravador recusou a hora: {txt.strip()[:80]}")
    depois = g.relogio()
    ok = abs(int(depois["diferenca_s"])) <= 5
    return {"ok": ok, "aplicadas": 1 if ok else 0, "nao_pegaram": [] if ok else ["hora"],
            "relogio": depois}


def corrigir(g: Gravador, aviso_id: str, base: Path, por: str = "", conector: str = "") -> Dict[str, Any]:
    """Rele o gravador, remonta o aviso e aplica so o que ainda esta fora."""
    if g.marca != "intelbras":
        raise ErroDriver(f"correcao ainda nao esta disponivel para {g.marca}")
    pares, relogio, com_camera = _ler(g)
    aviso = next((a for a in montar_avisos(pares, relogio, com_camera=com_camera) if a["id"] == aviso_id), None)
    if not aviso:
        return {"ok": True, "ja_estava": True, "aplicadas": 0, "nao_pegaram": []}

    reg = {"id": uuid.uuid4().hex[:12], "host": g.host, "conector": conector or "", "aviso": aviso_id, "titulo": aviso["titulo"],
           "quando": datetime.now().isoformat(timespec="seconds"), "por": por,
           "mudancas": aviso["_mudancas"], "desfazivel": aviso_id != "relogio"}
    if aviso_id == "relogio":
        r = _acertar_relogio(g)
        reg["mudancas"] = [{"chave": "hora", "de": relogio["gravador"] if relogio else "", "para": r["relogio"]["gravador"]}]
    else:
        r = g.aplicar(aviso["_mudancas"], backup_dir=base)
    reg.update({"ok": r["ok"], "nao_pegaram": r.get("nao_pegaram", []), "backup": r.get("backup", "")})
    _gravar_registro(base, reg)
    r.pop("backup", None)
    return {**r, "registro": reg["id"], "titulo": aviso["titulo"]}


def desfazer(g: Gravador, reg_id: str, base: Path, por: str = "", conector: str = "") -> Dict[str, Any]:
    reg = ler_registro(base, reg_id)
    if not _mesmo_gravador(reg, g.host, conector):
        raise ErroDriver("esse registro e de outro gravador")
    if not reg.get("desfazivel"):
        raise ErroDriver("essa correcao nao tem como desfazer")
    if reg.get("desfeito_em"):
        return {"ok": True, "ja_estava": True, "aplicadas": 0, "nao_pegaram": []}
    volta = [{"chave": m["chave"], "de": m["para"], "para": m["de"]} for m in reg.get("mudancas", [])]
    r = g.aplicar(volta, backup_dir=base)
    if r["ok"]:
        reg["desfeito_em"] = datetime.now().isoformat(timespec="seconds")
        reg["desfeito_por"] = por
        _gravar_registro(base, reg)
    r.pop("backup", None)
    return {**r, "registro": reg_id}


# ------------------------------------------------------------------ resumo
def _primeiro_no_dia(g: Gravador, canal: int, fim: datetime) -> Optional[str]:
    """Inicio do primeiro arquivo nas 24 h que terminam em `fim`, ou None.

    A Intelbras responde 400 no findFile quando a janela nao tem gravacao
    (visto no NVD 7132) -- isso e "nada", nao falha.
    """
    from datetime import timedelta

    from app.services.recorder_driver import parse_indice
    inicio = fim - timedelta(days=1)
    txt = g._get("/cgi-bin/mediaFileFind.cgi?action=factory.create")
    m = re.search(r"result=(\d+)", txt)
    if not m:
        raise ErroDriver("o gravador nao abriu a busca no indice")
    obj = m.group(1)
    try:
        cod, corpo = g._pedir(f"{g.base}/cgi-bin/mediaFileFind.cgi?action=findFile&object={obj}"
                              f"&condition.Channel={int(canal)}&condition.StartTime={quote(inicio.strftime(FMT))}"
                              f"&condition.EndTime={quote(fim.strftime(FMT))}&condition.Types[0]=dav")
        if cod == 400:
            return None
        if not cod or cod >= 400:
            raise ErroDriver(f"o gravador nao respondeu ({cod or str(corpo)[:80]})")
        segs = parse_indice(g._get(f"/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={obj}&count=1"))
    finally:
        for acao in ("close", "destroy"):
            try:
                g._get(f"/cgi-bin/mediaFileFind.cgi?action={acao}&object={obj}")
            except ErroDriver:
                pass
    return min((x.inicio for x in segs), default=None)


_DEGRAUS = (1, 3, 7, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365)


def gravacao_mais_antiga(g: Gravador, canal: int, agora: Optional[datetime] = None) -> Optional[str]:
    """Inicio do arquivo mais antigo do canal ainda no disco (= retencao).

    Buscar 400 dias de uma vez estoura o tempo do gravador (13 s no NVD 7132).
    Busca de 1 dia leva 0,5 s: sobe em degraus ate achar dia sem gravacao e
    refina por bissecao -- uns 15 pedidos pequenos. Gravador em sobrescrita
    grava continuo do mais antigo ate agora, entao a borda e uma so.
    """
    from datetime import timedelta

    agora = agora or datetime.now()
    if g.marca == "hikvision":
        from app.services.recorder_driver import _HIK_NS, parse_indice_hik
        inicio = agora - timedelta(days=400)
        corpo = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<CMSearchDescription version="1.0" xmlns="{_HIK_NS}">'
            f'<searchID>{uuid.uuid4()}</searchID>'
            f'<trackList><trackID>{int(canal)}01</trackID></trackList>'
            '<timeSpanList><timeSpan>'
            f'<startTime>{inicio:%Y-%m-%dT%H:%M:%SZ}</startTime><endTime>{agora:%Y-%m-%dT%H:%M:%SZ}</endTime>'
            '</timeSpan></timeSpanList><maxResults>1</maxResults><searchResultPostion>0</searchResultPostion>'
            '</CMSearchDescription>')
        segs, _ = parse_indice_hik(g._post("/ISAPI/ContentMgmt/search", corpo))
        return min((x.inicio for x in segs), default=None)

    def dia(d: int) -> Optional[str]:
        return _primeiro_no_dia(g, canal, agora - timedelta(days=d))

    achado = dia(0)
    if achado is None:
        return None
    sim, nao = 0, None
    for d in _DEGRAUS:
        r = dia(d)
        if r is None:
            nao = d
            break
        sim, achado = d, r
    if nao is None:
        return achado   # grava ha mais de um ano: o degrau mais alto basta
    while nao - sim > 1:
        meio = (sim + nao) // 2
        r = dia(meio)
        if r is None:
            nao = meio
        else:
            sim, achado = meio, r
    return achado


# Retencao muda devagar e custa ~15 pedidos ao gravador: guarda por 6 h.
# Chave com o cliente, porque o mesmo IP existe em clientes diferentes.
_RETENCAO_CACHE: Dict[tuple, tuple] = {}
_RETENCAO_TTL_S = 6 * 3600


def resumo_do_gravador(g: Gravador, canal: int) -> Dict[str, Any]:
    import time as _t
    t = _t.monotonic()
    try:
        relogio = g.relogio()
    except ErroDriver:
        relogio = None
    latencia = int((_t.monotonic() - t) * 1000)
    import time as _tm
    from app.core.tenant_context import get_current_tenant_slug
    chave = (get_current_tenant_slug() or "default", g.host, g.base, int(canal))
    guardado = _RETENCAO_CACHE.get(chave)
    if guardado and _tm.time() - guardado[0] < _RETENCAO_TTL_S:
        return {"marca": g.marca, "relogio": relogio, "latencia_ms": latencia, "retencao": guardado[1]}
    retencao = None
    try:
        antiga = gravacao_mais_antiga(g, canal)
        if antiga:
            dias = (datetime.now() - datetime.strptime(antiga, FMT)).total_seconds() / 86400
            retencao = {"canal": canal, "mais_antiga": antiga, "dias": round(dias, 1)}
        _RETENCAO_CACHE[chave] = (_tm.time(), retencao)
    except ErroDriver as exc:
        retencao = {"canal": canal, "erro": str(exc)}
    return {"marca": g.marca, "relogio": relogio, "latencia_ms": latencia, "retencao": retencao}
