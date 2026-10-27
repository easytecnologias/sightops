"""Instala o coletor no caixa PELO SightOps: SSH pelo IP virtual do conector.

Nunca pelo IP publico da loja nem pelo IP real: o caixa so e alcancado pelo
vnat do conector do proprio cliente (connector_routing_vnat). Sem conector, ou
IP fora das redes do conector, recusa.

O que faz no caixa (e so isso): confere python3 e a pasta do PDV, copia o
coletor para /tmp, roda o instalar.sh com sudo (senha pela entrada padrao, nunca
na linha de comando) e apaga a copia. Nao mexe na ponte do gravador nem em
outro servico. A senha do caixa fica cifrada (app.core.crypto).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.core.crypto import decrypt, encrypt
from app.services import db_store
from app.services import pdv_store

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pdv_coletor")
ARQUIVOS = ("sightops_pdv_coletor.py", "sightops-pdv-coletor.service", "instalar.sh")
SERVICO = "sightops-pdv-coletor"
TIMEOUT_CONEXAO = 12


class ErroInstalacao(Exception):
    pass


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caixa(c: Any, caixa_id: str) -> Dict[str, Any]:
    r = c.execute("SELECT * FROM pdv_caixas WHERE tenant_slug=? AND id=?", (pdv_store._tenant(), caixa_id)).fetchone()
    if not r:
        raise ValueError("Caixa não encontrado.")
    return dict(r)


def acesso_publico(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"pdv_host": r.get("pdv_host") or "", "ssh_porta": int(r.get("ssh_porta") or 22),
            "ssh_usuario": r.get("ssh_usuario") or "", "tem_senha": bool(r.get("ssh_senha_enc")),
            "ssh_hostkey": r.get("ssh_hostkey") or "", "instalacao_estado": r.get("instalacao_estado") or "",
            "instalacao_em": r.get("instalacao_em") or ""}


def salvar_acesso(caixa_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """IP do caixa NA LOJA, porta e usuario SSH; senha em branco mantem a guardada.

    Trocar IP ou porta sem senha nova apaga a senha e a chave conhecida: a senha
    nunca segue para outro destino sem alguem digita-la de novo.
    """
    host = str(payload.get("pdv_host") or "").strip()
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("Informe o IP do caixa na rede da loja (ex.: 192.168.24.97).")
    if not ip.is_private:
        raise ValueError("Use o IP do caixa na rede da loja. IP público não é aceito: o acesso é pelo conector.")
    try:
        porta = int(payload.get("ssh_porta") or 22)
    except (TypeError, ValueError):
        raise ValueError("Porta SSH é um número.")
    if not 1 <= porta <= 65535:
        raise ValueError("Porta SSH de 1 a 65535.")
    usuario = str(payload.get("ssh_usuario") or "").strip()[:64]
    if not usuario:
        raise ValueError("Informe o usuário do caixa.")
    senha = str(payload.get("ssh_senha") or "")
    with db_store._conn() as c:
        atual = _caixa(c, caixa_id)
        mudou_destino = host != atual.get("pdv_host") or porta != int(atual.get("ssh_porta") or 22)
        if senha:
            senha_enc = encrypt(senha)
        elif mudou_destino:
            senha_enc = ""
        else:
            senha_enc = atual.get("ssh_senha_enc") or ""
        hostkey = "" if mudou_destino else (atual.get("ssh_hostkey") or "")
        c.execute("UPDATE pdv_caixas SET pdv_host=?, ssh_porta=?, ssh_usuario=?, ssh_senha_enc=?, ssh_hostkey=?, updated_at=? "
                  "WHERE tenant_slug=? AND id=?",
                  (host, porta, usuario, senha_enc, hostkey, _agora(), pdv_store._tenant(), caixa_id))
        return acesso_publico(_caixa(c, caixa_id))


def ip_pelo_conector(connector_id: str, host: str) -> str:
    """IP virtual do caixa no conector do cliente; recusa qualquer outro caminho."""
    if not connector_id:
        raise ErroInstalacao("Este caixa não tem conector. A instalação só é feita pelo túnel do conector da loja.")
    from app.services.connector_routing_vnat import IP_BLOQUEADO, virtual_ip_for
    vip = virtual_ip_for(connector_id, host)
    if not vip or vip == IP_BLOQUEADO:
        raise ErroInstalacao("O conector deste caixa não pertence a este cliente.")
    if vip == host:
        raise ErroInstalacao("O IP %s não está nas redes do conector da loja. Confira o IP do caixa." % host)
    return vip


def _impressao(chave: Any) -> str:
    return "SHA256:" + hashlib.sha256(chave.asbytes()).hexdigest()[:32]


def _abrir_ssh(vip: str, porta: int, usuario: str, senha: str, hostkey: str):
    """paramiko com a chave do caixa conferida (aprende na primeira vez)."""
    import paramiko

    vista = {}

    class _Politica(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            vista["fp"] = _impressao(key)
            if hostkey and vista["fp"] != hostkey:
                raise ErroInstalacao("A chave SSH do caixa mudou (%s, esperada %s): outro equipamento neste IP? "
                                     "Confira antes de instalar." % (vista["fp"], hostkey))

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(_Politica())
    cli.connect(vip, port=porta, username=usuario, password=senha, timeout=TIMEOUT_CONEXAO,
                banner_timeout=TIMEOUT_CONEXAO, auth_timeout=TIMEOUT_CONEXAO, look_for_keys=False, allow_agent=False)
    return cli, vista.get("fp", "")


def _rodar(cli: Any, cmd: str, entrada: str = "", timeout: int = 60) -> tuple:
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    if entrada:
        stdin.write(entrada)
        stdin.flush()
    stdin.channel.shutdown_write()
    saida = stdout.read().decode("utf-8", "replace") + stderr.read().decode("utf-8", "replace")
    return stdout.channel.recv_exit_status(), saida


def _limpar(texto: str, segredos: List[str]) -> str:
    for s in segredos:
        if s:
            texto = texto.replace(s, "***")
    return texto[-2000:]


def _preparar(caixa_id: str) -> Dict[str, Any]:
    with db_store._conn() as c:
        cx = _caixa(c, caixa_id)
    if not cx.get("pdv_host") or not cx.get("ssh_usuario") or not cx.get("ssh_senha_enc"):
        raise ErroInstalacao("Informe o IP do caixa na loja, o usuário e a senha antes de instalar.")
    cx["_vip"] = ip_pelo_conector(cx.get("connector_id") or "", cx["pdv_host"])
    cx["_senha"] = decrypt(cx["ssh_senha_enc"])
    return cx


def _gravar_estado(caixa_id: str, estado: str, hostkey: str = "") -> None:
    with db_store._conn() as c:
        if hostkey:
            c.execute("UPDATE pdv_caixas SET instalacao_estado=?, instalacao_em=?, ssh_hostkey=? WHERE tenant_slug=? AND id=?",
                      (estado, _agora(), hostkey, pdv_store._tenant(), caixa_id))
        else:
            c.execute("UPDATE pdv_caixas SET instalacao_estado=?, instalacao_em=? WHERE tenant_slug=? AND id=?",
                      (estado, _agora(), pdv_store._tenant(), caixa_id))


def instalar(caixa_id: str, url_base: str, pasta: str = "/home/rpdv/frente/Cm",
             abrir: Optional[Callable] = None) -> Dict[str, Any]:
    """Instala (ou reinstala) o coletor. Devolve os passos com o resultado de cada um."""
    passos: List[Dict[str, Any]] = []

    def passo(nome: str, ok: bool, detalhe: str = "") -> None:
        passos.append({"passo": nome, "ok": ok, "detalhe": detalhe})

    try:
        cx = _preparar(caixa_id)
    except ErroInstalacao as exc:
        passo("Caminho pelo conector", False, str(exc))
        return {"ok": False, "passos": passos}
    senha, vip = cx["_senha"], cx["_vip"]
    passo("Caminho pelo conector", True, "%s na loja = %s pelo túnel" % (cx["pdv_host"], vip))
    abrir = abrir or _abrir_ssh
    try:
        cli, fp = abrir(vip, int(cx["ssh_porta"] or 22), cx["ssh_usuario"], senha, cx.get("ssh_hostkey") or "")
    except Exception as exc:  # senha errada, porta fechada, chave mudou
        passo("Entrar no caixa", False, _limpar(str(exc) or type(exc).__name__, [senha]))
        _gravar_estado(caixa_id, "falhou")
        return {"ok": False, "passos": passos}
    token = ""
    try:
        passo("Entrar no caixa", True, "chave do caixa %s" % (fp or cx.get("ssh_hostkey") or "conhecida"))
        cod, out = _rodar(cli, "python3 --version; test -d %s && echo PASTA_OK; ls %s | grep -c '^Espiao.*\\.%03d$' || true"
                          % (_aspas(pasta), _aspas(pasta), int(cx["numero"])), timeout=20)
        if "Python 3" not in out or "PASTA_OK" not in out:
            passo("Conferir o caixa", False, _limpar(out, [senha]) or "sem python3 ou sem a pasta do PDV")
            _gravar_estado(caixa_id, "falhou", fp)
            return {"ok": False, "passos": passos}
        passo("Conferir o caixa", True, out.strip().splitlines()[0] + " · pasta do PDV encontrada")
        cod, out = _rodar(cli, "sudo -S -p '' true", entrada=senha + "\n", timeout=20)
        if cod != 0:
            passo("Permissão de administrador (sudo)", False, "o usuário não tem sudo neste caixa ou a senha não vale para o sudo")
            _gravar_estado(caixa_id, "falhou", fp)
            return {"ok": False, "passos": passos}
        passo("Permissão de administrador (sudo)", True)
        destino = "/tmp/sightops-pdv-%s" % secrets.token_hex(4)
        token = pdv_store.novo_token(caixa_id)["token"]  # o anterior para de valer aqui
        config = json.dumps({"url": url_base.rstrip("/") + "/api/pdv/coletor/lote", "caixa": caixa_id,
                             "token": token, "pasta": pasta, "estacao": int(cx["numero"])})
        sftp = cli.open_sftp()
        try:
            sftp.mkdir(destino, 0o700)
            for nome in ARQUIVOS:
                sftp.put(os.path.join(ASSETS, nome), "%s/%s" % (destino, nome))
            # O token vai num arquivo 600, nunca na linha de comando (o sudo
            # gravaria no auth.log e qualquer usuario veria no ps).
            with sftp.open("%s/coletor.json" % destino, "w") as f:
                f.write(config)
            sftp.chmod("%s/coletor.json" % destino, 0o600)
        finally:
            sftp.close()
        passo("Enviar o coletor", True, "versão %s" % _versao_coletor())
        cod, out = _rodar(cli, "sudo -S -p '' sh %s/instalar.sh --config %s/coletor.json; rm -rf %s"
                          % (destino, destino, destino), entrada=senha + "\n", timeout=90)
        ok = cod == 0 and "Pronto." in out
        passo("Instalar e ligar o serviço", ok, _limpar(out, [senha, token]))
        _gravar_estado(caixa_id, "instalado" if ok else "falhou", fp)
        return {"ok": ok, "passos": passos}
    except Exception as exc:
        passo("Instalação interrompida", False, _limpar("%s: %s" % (type(exc).__name__, exc), [senha, token]))
        _gravar_estado(caixa_id, "falhou")
        return {"ok": False, "passos": passos}
    finally:
        try:
            cli.close()
        except Exception:
            pass


def status(caixa_id: str, abrir: Optional[Callable] = None) -> Dict[str, Any]:
    """Situacao do servico no caixa (so leitura)."""
    try:
        cx = _preparar(caixa_id)
    except ErroInstalacao as exc:
        return {"ok": False, "erro": str(exc)}
    abrir = abrir or _abrir_ssh
    try:
        cli, fp = abrir(cx["_vip"], int(cx["ssh_porta"] or 22), cx["ssh_usuario"], cx["_senha"], cx.get("ssh_hostkey") or "")
    except Exception as exc:
        return {"ok": False, "erro": _limpar(str(exc) or type(exc).__name__, [cx["_senha"]])}
    if fp and not cx.get("ssh_hostkey"):
        with db_store._conn() as c:  # aprende a chave na primeira conexao, como o instalar
            c.execute("UPDATE pdv_caixas SET ssh_hostkey=? WHERE tenant_slug=? AND id=?", (fp, pdv_store._tenant(), caixa_id))
    try:
        _, ativo = _rodar(cli, "systemctl is-active %s; systemctl show -p ActiveEnterTimestamp --value %s" % (SERVICO, SERVICO), timeout=15)
        _, log = _rodar(cli, "journalctl -u %s -n 15 --no-pager 2>/dev/null || true" % SERVICO, timeout=15)
        linhas = ativo.strip().splitlines()
        return {"ok": True, "ativo": (linhas[0] if linhas else "") == "active", "estado": linhas[0] if linhas else "",
                "desde": linhas[1] if len(linhas) > 1 else "", "log": _limpar(log, [cx["_senha"]])}
    finally:
        cli.close()


def _aspas(valor: str) -> str:
    """Argumento de shell entre aspas simples (os valores sao nossos, mas sem confiar)."""
    return "'" + str(valor).replace("'", "'\"'\"'") + "'"


def _versao_coletor() -> str:
    with open(os.path.join(ASSETS, "sightops_pdv_coletor.py"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("VERSAO"):
                return linha.split("=", 1)[1].strip().strip('"')
    return "?"
