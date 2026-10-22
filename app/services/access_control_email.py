"""Aviso por e-mail com a foto da passagem (Controle de Acesso).

Desenho aprovado em 22/10/2026 (mockup "E-mail com foto da passagem"):

- Conexoes > E-mail: servidor SMTP por local (ou padrao do cliente), "a cada
  passagem" ou "resumo do dia", foto por link que expira (padrao) ou anexada.
- Pessoas: e-mail do responsavel (access_people.guardian_email).
- Dispositivos > leitor > "Camera desta porta": canais de gravador do mesmo
  local (inventario de gravadores). Guardado por cliente em acesso-cameras.json.

A foto e da GRAVACAO, no segundo da passagem: a passagem chega com atraso
(o leitor e lido a cada 15 s), entao a foto ao vivo na hora pegaria a porta
vazia. O e-mail espera 3 min para o gravador ter o trecho, pede o quadro no
horario da passagem somado a diferenca do relogio do gravador (relogio()), e
tenta de novo a cada 2 min ate ~15 min. Sem foto, manda so o texto se o local
pediu ("sem_foto_envia").

O link da foto e publico (o responsavel abre do e-mail, sem login): token
aleatorio de 32 caracteres, guardado com o cliente, que vale 7 dias. A foto
fica na pasta do cliente.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services import db_store

logger = logging.getLogger("cam-snapshot")

FUSO = timezone(timedelta(hours=-3))
ESPERA_MIN = 3              # a passagem espera isto para o gravador ter o trecho
NOVA_TENTATIVA_MIN = 2
TENTATIVAS = 6              # 3 + 6 x 2 = ~15 min
JANELA_EVENTO_MIN = 30      # passagem mais antiga que isto (leitor voltou do ar) nao vira e-mail
LINK_DIAS = 7
FMT = "%Y-%m-%d %H:%M:%S"
ARQ_CAMERAS = "acesso-cameras.json"
PASTA_FOTOS = "acesso_email_fotos"
CHAVE = "access_control_email"
CHAVE_SITES = "access_control_email_by_site"
SEGURANCAS = ("starttls", "ssl", "nenhuma")
_EMAIL = re.compile(r"^[^@\s;,]+@[^@\s;,]+\.[^@\s;,]+$")
_RELOGIOS: Dict[Tuple[str, str], Tuple[int, datetime]] = {}


def _t(v: Any, n: int = 300) -> str:
    return str(v or "").strip()[:n]


def _tenant() -> str:
    return db_store._current_tenant_slug()


def _site_key(site: Any) -> str:
    return _t(site, 120).upper()


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _utc_txt(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime(FMT)


def _ler_utc(s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(_t(s, 19), FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ler_local(s: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(_t(s, 19), FMT)
    except ValueError:
        return None


# ---------------------------------------------------------------- configuracao

def _cfgs() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    settings = db_store.load_app_settings()
    geral = settings.get(CHAVE) if isinstance(settings.get(CHAVE), dict) else {}
    sites = settings.get(CHAVE_SITES) if isinstance(settings.get(CHAVE_SITES), dict) else {}
    return settings, geral, sites


def config_efetiva(site: Any = "") -> Dict[str, Any]:
    """Canal do local, senao o padrao do cliente (mesma regra do WhatsApp)."""
    _, geral, sites = _cfgs()
    cfg = sites.get(_site_key(site)) if _site_key(site) in sites else geral
    cfg = dict(cfg or {})
    cfg.setdefault("quando", "passagem")
    cfg.setdefault("foto", "link")
    cfg.setdefault("sem_foto_envia", True)
    cfg.setdefault("security", "starttls")
    cfg.setdefault("resumo_hora", "18:30")
    return cfg


def get_config(site: Any = "") -> Dict[str, Any]:
    _, _, sites = _cfgs()
    cfg = config_efetiva(site)
    return {
        "site": _site_key(site), "site_configured": bool(_site_key(site) and _site_key(site) in sites),
        "enabled": bool(cfg.get("enabled")), "configured": bool(cfg.get("host") and cfg.get("from_email")),
        "host": _t(cfg.get("host"), 200), "port": int(cfg.get("port") or 587), "user": _t(cfg.get("user"), 200),
        "password_saved": bool(cfg.get("password")), "security": cfg.get("security"),
        "from_name": _t(cfg.get("from_name"), 120), "from_email": _t(cfg.get("from_email"), 160),
        "quando": cfg.get("quando"), "resumo_hora": cfg.get("resumo_hora"), "foto": cfg.get("foto"),
        "sem_foto_envia": bool(cfg.get("sem_foto_envia")),
    }


def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.core.crypto import encrypt
    settings, geral, sites = _cfgs()
    site = _site_key(payload.get("site"))
    antigo = (sites.get(site) if site else geral) or {}
    host = _t(payload.get("host"), 200)
    if host and not re.match(r"^[A-Za-z0-9.\-]+$", host):
        raise ValueError("Servidor SMTP invalido.")
    try:
        porta = int(payload.get("port") or 587)
    except (TypeError, ValueError):
        raise ValueError("Porta invalida.")
    if not 1 <= porta <= 65535:
        raise ValueError("Porta invalida.")
    remetente = _t(payload.get("from_email") or payload.get("user"), 160).lower()
    if remetente and not _EMAIL.match(remetente):
        raise ValueError("E-mail do remetente invalido.")
    seguranca = _t(payload.get("security")) or "starttls"
    if seguranca not in SEGURANCAS:
        raise ValueError("Seguranca invalida.")
    quando = _t(payload.get("quando")) or "passagem"
    foto = _t(payload.get("foto")) or "link"
    hora = _t(payload.get("resumo_hora")) or "18:30"
    if quando not in ("passagem", "resumo") or foto not in ("link", "anexo") or not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hora):
        raise ValueError("Opcao invalida.")
    api_base = _t(payload.get("api_base"), 300).rstrip("/")
    if api_base and not re.match(r"^https?://[^\s\"'<>]+$", api_base):
        raise ValueError("Endereco do sistema invalido.")
    senha = _t(payload.get("password"), 300)
    novo = {
        "enabled": bool(payload.get("enabled")), "host": host, "port": porta, "user": _t(payload.get("user"), 200),
        "password": encrypt(senha) if senha else antigo.get("password", ""), "security": seguranca,
        "from_name": _t(payload.get("from_name"), 120), "from_email": remetente, "quando": quando,
        "resumo_hora": hora, "foto": foto, "sem_foto_envia": bool(payload.get("sem_foto_envia", True)),
        # De onde o responsavel abre o link da foto (o /v3 passa o API_BASE da tela).
        "api_base": api_base or antigo.get("api_base", ""),
    }
    if site:
        sites[site] = novo
        settings[CHAVE_SITES] = sites
    else:
        settings[CHAVE] = novo
    db_store.save_app_settings(settings)
    return get_config(site)


# ---------------------------------------------------------------- envio SMTP

def _smtp_enviar(cfg: Dict[str, Any], para: str, assunto: str, texto: str, html: str,
                 imagens: Optional[List[Tuple[bytes, str]]] = None, anexar: bool = False) -> None:
    """imagens: [(jpg, cid)] inline no HTML; anexar=True tambem vai como anexo."""
    from app.core.crypto import decrypt
    if not cfg.get("host") or not cfg.get("from_email"):
        raise RuntimeError("E-mail nao configurado (servidor e remetente).")
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr((cfg.get("from_name") or "", cfg["from_email"]))
    msg["To"] = para
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    if imagens:
        parte = msg.get_payload()[1]
        for dados, cid in imagens:
            parte.add_related(dados, maintype="image", subtype="jpeg", cid=f"<{cid}>")
        if anexar:
            for i, (dados, _) in enumerate(imagens):
                msg.add_attachment(dados, maintype="image", subtype="jpeg", filename=f"passagem-{i + 1}.jpg")
    porta = int(cfg.get("port") or 587)
    seg = cfg.get("security") or "starttls"
    ctx = ssl.create_default_context()
    servidor = smtplib.SMTP_SSL(cfg["host"], porta, timeout=30, context=ctx) if seg == "ssl" else smtplib.SMTP(cfg["host"], porta, timeout=30)
    try:
        if seg == "starttls":
            servidor.starttls(context=ctx)
        if cfg.get("user"):
            servidor.login(cfg["user"], decrypt(cfg.get("password") or "") if cfg.get("password") else "")
        servidor.send_message(msg)
    finally:
        try:
            servidor.quit()
        except Exception:
            pass


def enviar_teste(site: Any, para: str) -> Dict[str, Any]:
    para = _t(para, 160).lower()
    if not _EMAIL.match(para):
        raise ValueError("E-mail de teste invalido.")
    cfg = config_efetiva(site)
    local = _t(site, 120) or "SightOps"
    try:
        _smtp_enviar(cfg, para, f"Teste de aviso por e-mail · {local}",
                     f"Este e-mail confirma que o aviso de entrada e saida de {local} esta configurado.",
                     _html_moldura(local, f"<p>Este e-mail confirma que o aviso de entrada e saída de <b>{escape(local)}</b> está configurado.</p>"))
    except Exception as exc:   # o motivo do servidor SMTP vai para a tela
        return {"ok": False, "error": _erro_smtp(exc)}
    return {"ok": True}


def _erro_smtp(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "O servidor recusou usuario ou senha."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "O servidor recusou o destinatario."
    if isinstance(exc, (OSError, smtplib.SMTPConnectError)) and not isinstance(exc, smtplib.SMTPException):
        return f"Nao conectou no servidor: {exc}"
    return _t(str(exc) or exc.__class__.__name__, 300)


# ---------------------------------------------------------------- cameras das portas

def _arq_cameras() -> Path:
    from app.core.tenant_context import tenant_scoped_path
    return tenant_scoped_path(ARQ_CAMERAS, _tenant())


def _ler_cameras() -> Dict[str, List[Dict[str, Any]]]:
    try:
        d = json.loads(_arq_cameras().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _chave_cam(c: Dict[str, Any]) -> str:
    return f"{_t(c.get('host'))}:{int(c.get('canal') or 0)}"


def candidatas(site: str) -> List[Dict[str, Any]]:
    """Canais de gravador do local (inventario de gravadores do cliente)."""
    from app.core.tenant_context import tenant_recorder_inventory_path
    vistos: Dict[str, Dict[str, Any]] = {}
    for fonte in ("nvr", "dvr"):
        try:
            rows = json.loads(tenant_recorder_inventory_path(fonte).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            local = _t(r.get("local") or r.get("site"), 120)
            if local.upper() != _t(site, 120).upper():
                continue
            host = _t(r.get("host") or r.get("nvr_ip"), 80)
            try:
                canal = int(r.get("channel") or 0)
            except (TypeError, ValueError):
                canal = 0
            if not host or canal <= 0:
                continue
            c = {"host": host, "canal": canal, "http_port": int(r.get("http_port") or 80),
                 "connector_id": _t(r.get("remote_connector_id") or r.get("connector_id"), 80), "titulo": _t(r.get("title") or r.get("name"), 120),
                 "gravador": _t(r.get("recorder_name") or host, 120), "camera_ip": _t(r.get("camera_ip"), 60),
                 "status": _t(r.get("status"), 30), "fonte": fonte}
            vistos.setdefault(_chave_cam(c), c)
    return sorted(vistos.values(), key=lambda c: (c["gravador"], c["canal"]))


def _palavras(texto: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", texto.lower()) if len(w) > 2 and not w.isdigit()}


def sugestao(device: Dict[str, Any], lista: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Camera de nome parecido com o do leitor ("ENTRADA - ESCOLA X" x "CAM 03 ENTRADA")."""
    nome = _t(device.get("name")).upper().replace(_t(device.get("site")).upper(), "")
    alvo = _palavras(nome)
    melhor, pontos = None, 0
    for c in lista:
        p = len(alvo & _palavras(c["titulo"]))
        if p > pontos:
            melhor, pontos = c, p
    return melhor


def cameras_do_leitor(device_id: str) -> List[Dict[str, Any]]:
    return [c for c in _ler_cameras().get(_t(device_id, 80), []) if isinstance(c, dict)]


def salvar_cameras(device: Dict[str, Any], chaves: List[str]) -> List[Dict[str, Any]]:
    """So canais do local do proprio leitor: um leitor nao aponta para gravador
    de outro local (nem de outro cliente -- o inventario ja e do cliente)."""
    validas = {_chave_cam(c): c for c in candidatas(_t(device.get("site")))}
    escolhidas = []
    for k in chaves[:3]:
        if _t(k) not in validas:
            raise ValueError("Camera nao encontrada nos gravadores deste local.")
        escolhidas.append(validas[_t(k)])
    d = _ler_cameras()
    if escolhidas:
        d[_t(device.get("id"), 80)] = escolhidas
    else:
        d.pop(_t(device.get("id"), 80), None)
    arq = _arq_cameras()
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, arq)
    return escolhidas


# ---------------------------------------------------------------- foto da gravacao

def _gravador(cam: Dict[str, Any]):
    from app.services.recorder_credentials import resolve_recorder_credential
    from app.services.recorder_driver import Gravador
    cred = resolve_recorder_credential(cam["host"], int(cam.get("http_port") or 80)) or {}
    if not cred.get("password"):
        raise RuntimeError("gravador sem senha salva no SightOps")
    conector = _t(cam.get("connector_id"))
    if not conector:
        try:
            from app.api.endpoints.nvr import _recorder_connector_for_host
            conector = _recorder_connector_for_host(cam["host"]) or ""
        except Exception:
            conector = ""
    return Gravador(cam["host"], cred.get("username") or "admin", cred["password"], int(cam.get("http_port") or 80), conector)


def diferenca_relogio(cam: Dict[str, Any], g=None) -> int:
    """Segundos que o gravador esta adiantado (+) ou atrasado (-). Lido a cada 10 min."""
    chave = (_tenant(), cam["host"])
    guardado = _RELOGIOS.get(chave)
    if guardado and _agora_utc() - guardado[1] < timedelta(minutes=10):
        return guardado[0]
    g = g or _gravador(cam)
    dif = int(g.relogio().get("diferenca_s") or 0)
    _RELOGIOS[chave] = (dif, _agora_utc())
    return dif


ANTES_S = 4        # a gravacao abre no quadro-chave seguinte: comecar antes
QUADROS = 16       # 2 por segundo = 8 s em volta da passagem, numa sessao so


def _melhor_quadro(arquivos: List[Path]) -> Path:
    """O quadro com a pessoa mais clara (maior caixa x confianca). Sem pessoa,
    o do meio -- que e o mais perto do segundo da passagem."""
    meio = arquivos[min(len(arquivos) - 1, ANTES_S * 2)]
    try:
        import cv2
        from app.services import motion_classifier as mc
        det = mc.detector()
    except Exception:          # sem detector, fica o do meio
        return meio
    melhor, nota = meio, 0.0
    for arq in arquivos:
        img = cv2.imread(str(arq))
        for d in det.detectar(img) if img is not None else []:
            if d.classe != "pessoa":
                continue
            n = d.conf * (d.x2 - d.x1) * (d.y2 - d.y1)
            if n > nota:
                melhor, nota = arq, n
    return melhor


def capturar(cam: Dict[str, Any], momento: datetime, destino: Path, largura: int = 1280, escolher: bool = True) -> None:
    """Foto da gravacao na passagem `momento` (hora local). Na prova com os
    gravadores do RESERVA (22/10/2026) um quadro so, pedido no segundo exato,
    saiu 4 s depois e a porta ja estava vazia: aqui abre 4 s antes, tira 16
    quadros em 8 s e fica com o que mostra a pessoa. escolher=False (previa
    da camera) fica com um quadro so. Levanta erro com o motivo."""
    import subprocess
    import tempfile
    from app.services import investigation_classify as ic
    g = _gravador(cam)
    alvo = momento + timedelta(seconds=diferenca_relogio(cam, g) - (ANTES_S if escolher else 0))
    url = g.url_playback(int(cam["canal"]), alvo, alvo + timedelta(minutes=1))
    sessao = ic.sessao_do_gravador(cam["host"])
    if not sessao.acquire(timeout=40):
        raise RuntimeError("gravador ocupado")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not escolher:
            if not ic.tirar_quadro(url, destino, largura=largura):
                raise RuntimeError("sem gravacao nesse instante")
            return
        with tempfile.TemporaryDirectory() as tmp:
            try:
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
                                "-i", url, "-vf", f"fps=2,scale={largura}:-2", "-frames:v", str(QUADROS), "-q:v", "4", "-y",
                                str(Path(tmp) / "q_%02d.jpg")], capture_output=True, timeout=45)
            except subprocess.TimeoutExpired:
                pass
            quadros = sorted(q for q in Path(tmp).glob("q_*.jpg") if q.stat().st_size > 1000)
            if not quadros:
                raise RuntimeError("sem gravacao nesse instante")
            destino.write_bytes(_melhor_quadro(quadros).read_bytes())
    finally:
        sessao.release()


def _pasta_fotos(tenant: str = "") -> Path:
    from app.core.tenant_context import tenant_scoped_path
    p = tenant_scoped_path(PASTA_FOTOS, tenant or _tenant())
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- fila

def ensure_schema() -> None:
    backend = db_store._db_backend()
    with db_store._conn() as c:
        db_store._exec_many_statements(c, backend, """
            CREATE TABLE IF NOT EXISTS access_email_queue (
              id TEXT PRIMARY KEY,
              tenant_slug TEXT NOT NULL,
              event_id TEXT NOT NULL DEFAULT '',
              person_id TEXT NOT NULL DEFAULT '',
              device_id TEXT NOT NULL DEFAULT '',
              site TEXT NOT NULL DEFAULT '',
              event_type TEXT NOT NULL DEFAULT '',
              occurred_at TEXT NOT NULL DEFAULT '',
              email TEXT NOT NULL DEFAULT '',
              due_at TEXT NOT NULL DEFAULT '',
              attempts INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'pendente',
              error TEXT NOT NULL DEFAULT '',
              photo_file TEXT NOT NULL DEFAULT '',
              photo_source TEXT NOT NULL DEFAULT '',
              photo_token TEXT NOT NULL DEFAULT '',
              photo_expires TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT '',
              sent_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_email_queue_due ON access_email_queue(tenant_slug, status, due_at);
            CREATE INDEX IF NOT EXISTS idx_email_queue_token ON access_email_queue(photo_token);
            CREATE INDEX IF NOT EXISTS idx_email_queue_event ON access_email_queue(tenant_slug, event_id);
        """)


def _rows(sql: str, params: Tuple[Any, ...]) -> List[Dict[str, Any]]:
    with db_store._conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def _exec(sql: str, params: Tuple[Any, ...]) -> None:
    with db_store._conn() as c:
        c.execute(sql, params)


def enfileirar(evento: Dict[str, Any], agora: Optional[datetime] = None) -> str:
    """Chamado a cada passagem (notify_access_event). So poe na fila: a foto e o
    envio saem no laco, 3 min depois. Devolve o status para o evento."""
    agora = agora or _agora_utc()
    tipo = _t(evento.get("event_type"), 20).lower()
    if tipo not in ("entrada", "saida", "saida_manual"):
        return "email_skipped"
    cfg = config_efetiva(evento.get("site"))
    if not cfg.get("enabled"):
        return "email_skipped"
    pid = _t(evento.get("person_id"), 80)
    if not pid:
        return "email_skipped"
    tenant = _tenant()
    p = _rows("SELECT guardian_email, email_enabled FROM access_people WHERE tenant_slug=? AND id=?", (tenant, pid))
    if not p or not _t(p[0].get("guardian_email")) or not int(p[0].get("email_enabled") or 0):
        return "email_skipped"
    quando = _ler_local(evento.get("occurred_at"))
    if not quando:
        return "email_skipped"
    quando_utc = quando.replace(tzinfo=FUSO).astimezone(timezone.utc)
    if agora - quando_utc > timedelta(minutes=JANELA_EVENTO_MIN):
        return "email_antigo"     # leitor voltou do ar com historico: nao vira enxurrada de e-mail
    ensure_schema()
    eid = _t(evento.get("id"), 80)
    if eid and _rows("SELECT id FROM access_email_queue WHERE tenant_slug=? AND event_id=?", (tenant, eid)):
        return "email_queued"
    devido = max(agora, quando_utc + timedelta(minutes=ESPERA_MIN))
    _exec("INSERT INTO access_email_queue(id, tenant_slug, event_id, person_id, device_id, site, event_type, occurred_at, "
          "email, due_at, status, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendente', ?)",
          (uuid.uuid4().hex, tenant, eid, pid, _t(evento.get("device_id"), 80), _t(evento.get("site"), 120), tipo,
           quando.strftime(FMT), _t(p[0]["guardian_email"], 160), _utc_txt(devido), _utc_txt(agora)))
    return "email_queued"


def _pessoa(pid: str) -> Dict[str, Any]:
    r = _rows("SELECT full_name, class_name, guardian_name, site FROM access_people WHERE tenant_slug=? AND id=?", (_tenant(), pid))
    return r[0] if r else {}


def _porta(device_id: str) -> str:
    r = _rows("SELECT name, site FROM access_devices WHERE tenant_slug=? AND id=?", (_tenant(), device_id))
    if not r:
        return ""
    nome, site = _t(r[0].get("name")), _t(r[0].get("site"))
    if site and nome.upper().endswith(" - " + site.upper()):
        nome = nome[: -len(site) - 3]
    return nome.title()


def _verbo(tipo: str) -> str:
    return "entrou" if tipo == "entrada" else "saiu"


def _html_moldura(local: str, corpo: str) -> str:
    return (f'<div style="font-family:Arial,Helvetica,sans-serif;background:#f3f5f7;padding:24px">'
            f'<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #dfe4e8;border-radius:12px;overflow:hidden">'
            f'<div style="padding:18px 22px;border-bottom:3px solid #087f5b"><b style="font-size:16px;color:#172026">{escape(local)}</b>'
            f'<div style="font-size:12px;color:#66747e">Aviso de entrada e saída</div></div>'
            f'<div style="padding:20px 22px;font-size:15px;color:#172026;line-height:1.5">{corpo}</div></div></div>')


def _link_foto(cfg: Dict[str, Any], token: str) -> str:
    base = _t(cfg.get("api_base"), 300).rstrip("/")
    return f"{base}/api/access-control/foto/{token}" if base and token else ""


def _montar(cfg: Dict[str, Any], itens: List[Dict[str, Any]]) -> Tuple[str, str, str, List[Tuple[bytes, str]]]:
    """Um e-mail para 1 passagem (a cada passagem) ou varias do mesmo dia (resumo)."""
    p = _pessoa(itens[0]["person_id"])
    nome = _t(p.get("full_name")) or "A pessoa"
    turma = _t(p.get("class_name"))
    local = _t(itens[0].get("site") or p.get("site")) or "o local"
    resp = _t(p.get("guardian_name"))
    imagens: List[Tuple[bytes, str]] = []
    blocos, linhas_txt = [], []
    for it in itens:
        q = _ler_local(it["occurred_at"])
        quando = q.strftime("%d/%m/%Y às %H:%M:%S") if q else it["occurred_at"]
        porta = _porta(it["device_id"])
        frase = f"{_verbo(it['event_type'])} {('pela ' + porta) if porta else ''} {quando}".replace("  ", " ")
        linhas_txt.append(f"- {nome} {frase}")
        foto = ""
        arq = _pasta_fotos() / it["photo_file"] if it.get("photo_file") else None
        if arq and arq.exists():
            if cfg.get("foto") == "anexo":
                cid = make_msgid(domain="sightops")[1:-1]
                imagens.append((arq.read_bytes(), cid))
                foto = f'<img src="cid:{cid}" alt="Foto da passagem" style="width:100%;max-width:516px;border-radius:8px;display:block;margin-top:8px">'
            else:
                link = _link_foto(cfg, it.get("photo_token", ""))
                if link:
                    foto = (f'<a href="{escape(link)}" style="display:inline-block;margin-top:8px;padding:10px 16px;background:#087f5b;'
                            f'color:#ffffff;text-decoration:none;border-radius:8px;font-weight:bold">Ver a foto da {"entrada" if it["event_type"] == "entrada" else "saída"}</a>')
                    linhas_txt.append(f"  Foto: {link}")
        elif cfg.get("sem_foto_envia"):
            foto = '<div style="font-size:12px;color:#66747e;margin-top:6px">Sem imagem da câmera para esta passagem.</div>'
        blocos.append(f'<div style="border:1px solid #dfe4e8;border-radius:10px;padding:12px 14px;margin-top:12px">'
                      f'<b style="color:{"#087f5b" if it["event_type"] == "entrada" else "#172026"}">{escape(_verbo(it["event_type"]).capitalize())}</b> '
                      f'{escape(("pela " + porta) if porta else "")} · {escape(quando)}{foto}</div>')
    saud = f"Olá, {escape(resp)}." if resp else "Olá."
    quem = f"<b>{escape(nome)}</b>{(' (' + escape(turma) + ')') if turma else ''}"
    if len(itens) == 1:
        q = _ler_local(itens[0]["occurred_at"])
        assunto = f"{nome} {_verbo(itens[0]['event_type'])} · {local} · {q.strftime('%H:%M') if q else ''}".strip()
        abertura = f"<p>{saud}</p><p>{quem} {_verbo(itens[0]['event_type'])} — {escape(local)}.</p>"
    else:
        q = _ler_local(itens[0]["occurred_at"])
        assunto = f"{nome} · entradas e saídas de {q.strftime('%d/%m') if q else 'hoje'} · {local}"
        abertura = f"<p>{saud}</p><p>Entradas e saídas de {quem} hoje — {escape(local)}.</p>"
    rodape = ('<p style="font-size:12px;color:#66747e;margin-top:16px">'
              + (f"O link da foto vale por {LINK_DIAS} dias. " if cfg.get("foto") != "anexo" else "")
              + "Você recebe este aviso porque este e-mail está no cadastro. Para parar de receber, fale com o local.</p>")
    html = _html_moldura(local, abertura + "".join(blocos) + rodape)
    texto = (f"Olá, {resp}." if resp else "Olá.") + "\n\n" + "\n".join(linhas_txt) + f"\n\n{local}"
    return assunto, texto, html, imagens


def _processar_um(r: Dict[str, Any], agora: datetime) -> None:
    cfg = config_efetiva(r["site"])
    if not cfg.get("enabled"):
        _exec("UPDATE access_email_queue SET status='cancelado', error='e-mail desligado no local' WHERE id=?", (r["id"],))
        return
    cams = cameras_do_leitor(r["device_id"])
    foto, fonte, erro = "", "", ""
    if cams and not r.get("photo_file"):
        momento = _ler_local(r["occurred_at"])
        for cam in cams:
            nome_arq = f"{r['id']}.jpg"
            try:
                capturar(cam, momento, _pasta_fotos() / nome_arq)
                foto, fonte = nome_arq, f"gravacao {cam['gravador']} canal {cam['canal']}"
                break
            except Exception as exc:
                erro = _t(str(exc) or exc.__class__.__name__, 200)
        if not foto and int(r.get("attempts") or 0) < TENTATIVAS:
            _exec("UPDATE access_email_queue SET attempts=attempts+1, due_at=?, error=? WHERE id=?",
                  (_utc_txt(agora + timedelta(minutes=NOVA_TENTATIVA_MIN)), erro, r["id"]))
            return
    elif not cams:
        erro = "porta sem camera vinculada"
    if foto:
        token = secrets.token_urlsafe(24)
        _exec("UPDATE access_email_queue SET photo_file=?, photo_source=?, photo_token=?, photo_expires=?, error='' WHERE id=?",
              (foto, fonte, token, _utc_txt(agora + timedelta(days=LINK_DIAS)), r["id"]))
        r.update(photo_file=foto, photo_token=token)
    if not foto and not r.get("photo_file"):
        if not cfg.get("sem_foto_envia"):
            _exec("UPDATE access_email_queue SET status='sem_foto', error=? WHERE id=?", (erro or "sem foto", r["id"]))
            return
        # vai sem foto: o motivo fica no historico (saida manual nao tem porta, camera sem gravacao...)
        _exec("UPDATE access_email_queue SET error=? WHERE id=?", (f"sem foto: {erro}" if erro else "sem foto", r["id"]))
    if cfg.get("quando") == "resumo":
        _exec("UPDATE access_email_queue SET status='aguardando_resumo' WHERE id=?", (r["id"],))
        return
    _enviar_itens(cfg, [r], agora)


def _enviar_itens(cfg: Dict[str, Any], itens: List[Dict[str, Any]], agora: datetime) -> None:
    ids = [it["id"] for it in itens]
    marcas = ",".join("?" for _ in ids)
    try:
        assunto, texto, html, imagens = _montar(cfg, itens)
        _smtp_enviar(cfg, itens[0]["email"], assunto, texto, html, imagens, anexar=cfg.get("foto") == "anexo")
    except Exception as exc:
        erro = _erro_smtp(exc)
        logger.warning("e-mail de passagem falhou (%s): %s", itens[0]["email"], erro)
        _exec(f"UPDATE access_email_queue SET status='falhou', error=? WHERE id IN ({marcas})", (erro, *ids))
        return
    _exec(f"UPDATE access_email_queue SET status='enviado', sent_at=? WHERE id IN ({marcas})", (_utc_txt(agora), *ids))


def _resumos(agora: datetime) -> int:
    """Resumo do dia: um e-mail por pessoa e dia, no horario do local (ou
    depois, para dias que ja passaram)."""
    prontos = _rows("SELECT * FROM access_email_queue WHERE tenant_slug=? AND status='aguardando_resumo' ORDER BY occurred_at",
                    (_tenant(),))
    grupos: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for r in prontos:
        grupos.setdefault((r["email"], r["person_id"], r["occurred_at"][:10]), []).append(r)
    local = agora.astimezone(FUSO)
    enviados = 0
    for (_, _, dia), itens in grupos.items():
        cfg = config_efetiva(itens[0]["site"])
        hora = cfg.get("resumo_hora") or "18:30"
        if dia > local.strftime("%Y-%m-%d") or (dia == local.strftime("%Y-%m-%d") and local.strftime("%H:%M") < hora):
            continue
        _enviar_itens(cfg, itens, agora)
        enviados += 1
    return enviados


def processar_fila(agora: Optional[datetime] = None, limite: int = 30) -> Dict[str, Any]:
    """Uma volta do laco (por cliente): fotos, envios, resumos e limpeza."""
    agora = agora or _agora_utc()
    ensure_schema()
    devidos = _rows("SELECT * FROM access_email_queue WHERE tenant_slug=? AND status='pendente' AND due_at <= ? "
                    "ORDER BY due_at LIMIT ?", (_tenant(), _utc_txt(agora), int(limite)))
    for r in devidos:
        try:
            _processar_um(r, agora)
        except Exception as exc:   # um item nao para a fila
            logger.exception("fila de e-mail: item %s falhou", r.get("id"))
            _exec("UPDATE access_email_queue SET status='falhou', error=? WHERE id=?", (_t(str(exc), 200), r["id"]))
    resumos = _resumos(agora)
    _limpar(agora)
    return {"processados": len(devidos), "resumos": resumos}


def _limpar(agora: datetime) -> None:
    """Foto vencida sai do disco (o link ja nao abre)."""
    for r in _rows("SELECT id, photo_file FROM access_email_queue WHERE tenant_slug=? AND photo_file <> '' AND photo_expires <> '' "
                   "AND photo_expires < ?", (_tenant(), _utc_txt(agora))):
        (_pasta_fotos() / r["photo_file"]).unlink(missing_ok=True)
        _exec("UPDATE access_email_queue SET photo_file='', photo_token='' WHERE id=?", (r["id"],))


def foto_publica(token: str, agora: Optional[datetime] = None) -> Optional[Path]:
    """Link do e-mail (sem login). O token e aleatorio e so abre a foto dele,
    na pasta do cliente dono do registro, ate vencer."""
    token = _t(token, 64)
    if len(token) < 24 or not re.match(r"^[A-Za-z0-9_\-]+$", token):
        return None
    ensure_schema()
    r = _rows("SELECT tenant_slug, photo_file, photo_expires FROM access_email_queue WHERE photo_token=?", (token,))
    if not r or not r[0]["photo_file"]:
        return None
    vence = _ler_utc(r[0]["photo_expires"])
    if not vence or vence < (agora or _agora_utc()):
        return None
    arq = _pasta_fotos(r[0]["tenant_slug"]) / Path(r[0]["photo_file"]).name
    return arq if arq.exists() else None


def historico(site: str = "", limite: int = 80, locais: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """`locais`: usuario restrito sem local escolhido so ve os locais dele
    (revisor-isolamento 22/10/2026: sem isto via e-mail e nome de aluno de
    outro local do mesmo cliente)."""
    ensure_schema()
    filtro, params = "", [_tenant()]
    if site:
        filtro, params = " AND upper(q.site)=?", params + [_t(site, 120).upper()]
    elif locais is not None:
        if not locais:
            return []
        filtro = f" AND upper(q.site) IN ({','.join('?' for _ in locais)})"
        params += [_t(x, 120).upper() for x in locais]
    sql = ("SELECT q.id, q.site, q.event_type, q.occurred_at, q.email, q.status, q.error, q.attempts, q.photo_source, q.sent_at, "
           "p.full_name FROM access_email_queue q LEFT JOIN access_people p ON p.id=q.person_id AND p.tenant_slug=q.tenant_slug "
           "WHERE q.tenant_slug=?" + filtro + " ORDER BY q.occurred_at DESC LIMIT ?")
    return _rows(sql, tuple(params + [int(limite)]))
