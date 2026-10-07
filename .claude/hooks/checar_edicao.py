"""Hook PostToolUse: confere cada arquivo editado pelo agente.

- .py  -> py_compile (erro de sintaxe volta para o agente na hora)
- .js  -> node --check
- frontend/js/*.js ou styles.css alterado sem subir o ?v= no index.html -> lembrete

O ?v= so fura o cache do Cloudflare com numero inedito; esquecer de subir faz
parecer que a correcao nao funcionou.
"""
import json
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        dados = json.load(sys.stdin)
    except Exception:
        return 0
    caminho = (dados.get("tool_input") or {}).get("file_path") or ""
    if not caminho:
        return 0
    arq = Path(caminho)
    raiz = Path(dados.get("cwd") or ".")
    if not arq.exists():
        return 0

    if arq.suffix == ".py":
        try:
            py_compile.compile(str(arq), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"Erro de sintaxe em {arq.name}:\n{exc.msg}", file=sys.stderr)
            return 2

    if arq.suffix == ".js" and shutil.which("node"):
        r = subprocess.run(["node", "--check", str(arq)], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"Erro de sintaxe em {arq.name}:\n{r.stderr.strip()[-800:]}", file=sys.stderr)
            return 2

    lembrete = _lembrete_versao(arq, raiz)
    if lembrete:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": lembrete}}))
    return 0


def _lembrete_versao(arq: Path, raiz: Path) -> str:
    try:
        rel = arq.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return ""
    if rel == "frontend/styles.css":
        alvo = "styles.css"
    elif re.fullmatch(r"frontend/js/[A-Za-z0-9_]+\.js", rel):
        alvo = rel[len("frontend/"):]
    else:
        return ""
    index = raiz / "frontend" / "index.html"
    try:
        atual = index.read_text(encoding="utf-8")
        antes = subprocess.run(["git", "show", "HEAD:frontend/index.html"], cwd=raiz,
                               capture_output=True, text=True, encoding="utf-8").stdout
    except Exception:
        return ""
    padrao = re.escape(alvo) + r"\?v=(\d+)"
    v_atual, v_antes = re.search(padrao, atual), re.search(padrao, antes)
    if not v_atual or not v_antes:
        return ""
    maior_antes = max((int(n) for n in re.findall(r"\?v=(\d+)", antes)), default=0)
    if v_atual.group(1) == v_antes.group(1):
        return (f"{alvo} mudou e o ?v= dele no index.html continua {v_atual.group(1)}. "
                f"Antes de publicar, suba para um numero inedito (maior que {maior_antes}).")
    if int(v_atual.group(1)) <= maior_antes:
        return (f"O ?v= novo de {alvo} ({v_atual.group(1)}) nao e maior que {maior_antes}, "
                f"o maior ja usado: pode reaproveitar um numero e servir JS velho.")
    return ""


if __name__ == "__main__":
    sys.exit(main())
