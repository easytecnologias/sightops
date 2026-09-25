"""Verificacao completa antes de commitar/publicar: um comando, tudo de uma vez.

Roda, em ordem, e para no primeiro grupo que falhar:
  1. compila todo o Python de app/
  2. `node --check` em todo frontend/js/*.js (se o node existir)
  3. os testes de scripts/ (sightops_*_test.py e *_smoke.py)

Descobre os arquivos sozinho -- nao tem lista fixa, entao nao envelhece quando
alguem adiciona um teste ou um modulo novo. E o mesmo conjunto que o CI roda
antes de construir a imagem (.github/workflows/docker-image.yml).

Uso:  python scripts/check.py
Saida 0 = tudo verde; qualquer outra = algo quebrou (com o detalhe acima).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VERDE = "\033[32m"
VERMELHO = "\033[31m"
CINZA = "\033[90m"
ZERA = "\033[0m"


def _run(titulo: str, cmd: list[str], cwd: Path = ROOT) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as exc:
        return False, f"comando nao encontrado: {exc}"
    ok = proc.returncode == 0
    saida = (proc.stdout or "") + (proc.stderr or "")
    return ok, saida.strip()


def _ultimas_linhas(texto: str, n: int = 12) -> str:
    linhas = [l for l in texto.splitlines() if l.strip()]
    return "\n".join(linhas[-n:])


def main() -> int:
    falhas: list[str] = []

    # 1. compila todo o Python de app/
    print(f"{CINZA}[1/3] compilando Python de app/…{ZERA}")
    ok, saida = _run("compileall", [sys.executable, "-m", "compileall", "-q", "app"])
    if ok:
        print(f"  {VERDE}OK{ZERA} app/ compila")
    else:
        print(f"  {VERMELHO}FALHOU{ZERA}\n{_ultimas_linhas(saida)}")
        falhas.append("compilacao de app/")

    # 2. node --check nos JS (so se o node existir; nao e obrigatorio ter node)
    print(f"{CINZA}[2/3] node --check em frontend/js/…{ZERA}")
    node = shutil.which("node")
    if not node:
        print(f"  {CINZA}pulado (node nao instalado nesta maquina){ZERA}")
    else:
        js_files = sorted((ROOT / "frontend" / "js").glob("*.js"))
        quebrados = []
        for js in js_files:
            ok, saida = _run("node", [node, "--check", str(js)])
            if not ok:
                quebrados.append(f"{js.name}: {_ultimas_linhas(saida, 3)}")
        if not quebrados:
            print(f"  {VERDE}OK{ZERA} {len(js_files)} arquivo(s) JS")
        else:
            for q in quebrados:
                print(f"  {VERMELHO}FALHOU{ZERA} {q}")
            falhas.append("sintaxe de frontend/js/")

    # 3. testes de scripts/
    print(f"{CINZA}[3/3] testes de scripts/…{ZERA}")
    testes = sorted(
        p for p in (ROOT / "scripts").glob("*.py")
        if p.name.endswith("_test.py") or p.name.endswith("_smoke.py")
    )
    for teste in testes:
        # Dois estilos de teste convivem em scripts/:
        #  - baseados em unittest.TestCase: precisam de `-m unittest`, que poe a
        #    raiz do projeto no sys.path (senao `import app` falha). Rodar o
        #    arquivo direto quebra em ModuleNotFoundError: No module named 'app'.
        #  - scripts com sys.path.insert proprio e __main__: rodam direto.
        # Detectar pela presenca de unittest.TestCase e o criterio confiavel --
        # ter __main__ nao distingue, porque o estilo unittest tambem costuma ter.
        conteudo = teste.read_text(encoding="utf-8", errors="replace")
        if "unittest.TestCase" in conteudo:
            cmd = [sys.executable, "-m", "unittest", f"scripts.{teste.stem}"]
        else:
            cmd = [sys.executable, str(teste)]
        ok, saida = _run(teste.name, cmd)
        if ok:
            print(f"  {VERDE}OK{ZERA} {teste.name}")
        else:
            print(f"  {VERMELHO}FALHOU{ZERA} {teste.name}\n{_ultimas_linhas(saida)}")
            falhas.append(teste.name)

    print()
    if falhas:
        print(f"{VERMELHO}CHECK FALHOU{ZERA} — {len(falhas)} grupo(s): {', '.join(falhas)}")
        return 1
    print(f"{VERDE}CHECK OK{ZERA} — Python compila, JS valido, {len(testes)} testes verdes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
