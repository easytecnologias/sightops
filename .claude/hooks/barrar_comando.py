"""Hook PreToolUse (Bash/PowerShell): segura comando que ja derrubou producao.

Os comandos para o servidor saem pelo plink, entao passam por aqui como texto.
Cada regra veio de um incidente real:

- recriar o container da API sem `docker commit` antes apagou codigo publicado
  so por `docker cp` (o relatorio em PDF voltou a ser foto);
- `docker image prune -a` apaga as tags locais de rollback (nao ha registry);
- o `sightops-prod-nginx` e a ENTRADA do v3: parar ele derruba o site;
- push e do usuario;
- `plink -pw <senha>` deixou a senha do servidor em cada comando da transcricao
  (14/10/2026) -- e a chave SSH ja estava autorizada. Acesso e `ssh sightops`;
- `compose up -d` sem `--force-recreate` TAMBEM recria o container quando a
  tag do .env.v3 mudou; a regra antiga so pegava o `--force-recreate`;
- arquivo com CRLF copiado do Windows para o servidor: o .py roda, mas o md5
  nunca bate com o git (6 falsos "DIFERE" em 14/10/2026) e um .sh quebra com
  "bad interpreter: /bin/bash^M".

"negar" bloqueia; "perguntar" pede a confirmacao do usuario na hora.
"""
import json
import re
import shlex
import sys
from pathlib import Path

NEGAR = [
    (r"docker\s+(image|system)\s+prune\b[^|;&]*\s-(a\b|-all\b)",
     "apaga as tags de imagem de rollback (sao locais, nao ha registry). Use `docker builder prune -f` para liberar espaco."),
    (r"docker\s+volume\s+(rm|prune)\b",
     "volume guarda banco, inventario e fotos dos clientes."),
    (r"rm\s+-[a-z]*r[a-z]*f?[a-z]*\s+[^|;&]*(/mnt/dados|/var/lib/docker|sightops-v3-release|sightops_prod_data)",
     "apaga dado de producao (volumes, backup ou a pasta publicada)."),
    (r"git\s+push\b[^|;&]*(--force\b|-f\b|--force-with-lease)",
     "push forcado reescreve o historico do GitHub."),
    (r">\s*[^|;&]*\.env\.v3\b",
     "sobrescreve o .env.v3 (tem a SIGHTOPS_SECRET_KEY; sem ela as senhas de OLT ficam ilegiveis). Use `sed -i` so na linha que muda."),
    (r"\b(plink|pscp|psftp)(\.exe)?\b[^|;&]*\s-pw\b|\bsshpass\b",
     "senha na linha de comando fica gravada na transcricao. Use a chave: `ssh sightops '...'` e `scp arq sightops:/tmp/` (alias em ~/.ssh/config)."),
]

PERGUNTAR = [
    (r"docker\s+compose\b[^|;&]*\b(down|rm)\b",
     "derruba containers de producao."),
    (r"docker[\s-]+compose\b(?![^|;&]*--dry-run)[^|;&]*\bup\b",
     "pode recriar container (sempre que a imagem/tag do .env.v3 mudou, mesmo sem --force-recreate): o que entrou so por `docker cp` some se nao houve `docker commit` antes. Rode antes com --dry-run."),
    (r"docker\s+(rm|stop|kill)\b[^|;&]*sightops",
     "para/remove container do SightOps. O `sightops-prod-nginx` e a entrada do v3: parar ele derruba o site."),
    (r"docker\s+(rm|stop|kill|restart)\b[^|;&]*(sightops-v3-postgres|zabbix-v3-postgres)",
     "mexe no banco de producao."),
    (r"git\s+push\b",
     "o push e feito pelo usuario."),
    (r"git\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s|restore\s+\.)",
     "descarta trabalho nao commitado (o Codex trabalha em paralelo neste repo)."),
    (r"\breboot\b|shutdown\s+-r|systemctl\s+(restart|stop)\s+docker",
     "reinicia o servidor ou o Docker. Antes rode a skill sightops-conferir-servidor."),
]


_TEXTO = {".py", ".sh", ".js", ".html", ".css", ".yml", ".yaml", ".conf", ".sql"}


def _crlf_enviado(comando: str, cwd: str) -> str:
    """Arquivo local com CRLF num scp/pscp para o servidor. Devolve o nome ou ''."""
    if not re.search(r"\b(scp|pscp)(\.exe)?\b", comando):
        return ""
    try:
        partes = shlex.split(comando, posix=True)
    except ValueError:
        partes = comando.split()
    base = Path(cwd or ".")
    for p in partes:
        if ":" in p[2:] or Path(p).suffix.lower() not in _TEXTO:
            continue  # destino remoto (host:/caminho) ou nao e texto
        arq = Path(p) if Path(p).is_absolute() else base / p
        try:
            if arq.is_file() and b"\r\n" in arq.read_bytes():
                return p
        except OSError:
            continue
    return ""


def _decidir(decisao: str, motivo: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decisao,
        "permissionDecisionReason": f"SightOps: {motivo}",
    }}))


def main() -> int:
    try:
        dados = json.load(sys.stdin)
    except Exception:
        return 0
    comando = str((dados.get("tool_input") or {}).get("command") or "")
    if not comando:
        return 0
    for decisao, regras in (("deny", NEGAR), ("ask", PERGUNTAR)):
        for padrao, motivo in regras:
            if re.search(padrao, comando, re.IGNORECASE):
                _decidir(decisao, motivo)
                return 0
    arq = _crlf_enviado(comando, str(dados.get("cwd") or ""))
    if arq:
        _decidir("deny", f"`{arq}` tem CRLF (Windows). No servidor o md5 nunca bate com o git e "
                 "um .sh quebra com 'bad interpreter'. Envie uma copia convertida: "
                 "`tr -d '\\r' < arq > $TEMP/arq` e mande essa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
