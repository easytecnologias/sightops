"""Hook SessionStart: diz logo de cara se esta copia do repo esta atrasada.

Em 14/10/2026 a copia do Windows estava 54 commits atras do servidor, sem
remote nenhum, e com trabalho inedito (status de canal de NVR) misturado a
versoes velhas de arquivos que o servidor ja tinha. Ninguem sabia ate a hora
do push. Este hook compara com o servidor (remote `servidor`; no proprio
servidor, `origin`) e so fala quando algo nao bate.

Nunca falha a sessao: qualquer erro vira silencio ou um aviso curto.
"""
import json
import subprocess
import sys


def _git(*args: str, timeout: int = 5) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "git falhou")
    return r.stdout.strip()


def _avaliar() -> str:
    remotes = _git("remote").split()
    remote = "servidor" if "servidor" in remotes else "origin" if "origin" in remotes else ""
    if not remote:
        return ("Esta copia do SightOps nao tem remote: nao da para saber se esta atrasada. "
                "Configure: git remote add servidor sightops:/home/central/sightops-v3")
    avisos = []
    try:
        _git("fetch", "-q", remote, timeout=15)
    except Exception:
        avisos.append(f"nao consegui consultar `{remote}` (rede/SSH); comparacao abaixo pode estar velha")
    ramo = _git("rev-parse", "--abbrev-ref", "HEAD")
    alvo = f"{remote}/main"
    atras, frente = _git("rev-list", "--left-right", "--count", f"{alvo}...HEAD").split()
    sujos = [l for l in _git("status", "--porcelain").splitlines() if l.strip()]
    if int(atras):
        avisos.append(f"{atras} commit(s) ATRAS de {alvo} -- nao edite antes de atualizar "
                      f"(git merge --ff-only {alvo}), senao vai trabalhar sobre versao velha")
    if int(frente):
        avisos.append(f"{frente} commit(s) a frente de {alvo} que nao foram para la")
    if sujos:
        avisos.append(f"{len(sujos)} arquivo(s) sem commit")
    if ramo != "main":
        avisos.append(f"ramo atual e `{ramo}`, nao main")
    if not avisos:
        return ""
    return "SightOps -- situacao desta copia: " + "; ".join(avisos) + "."


def main() -> int:
    try:
        msg = _avaliar()
    except Exception as e:  # noqa: BLE001 - hook de inicio nunca derruba a sessao
        msg = f"SightOps: nao consegui conferir a situacao do repo ({e})."
    if msg:
        print(json.dumps({
            "systemMessage": msg,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": msg},
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
