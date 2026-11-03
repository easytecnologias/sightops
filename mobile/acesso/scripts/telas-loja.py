"""Capturas de tela do SightOps Acesso para a ficha do Google Play.

Abre o app ja compilado (dist/) num navegador do tamanho de um celular, com a
API trocada por dados FICTICIOS (Colegio Exemplo, nomes inventados, sem foto de
rosto), e fotografa as telas. Nada vai ao servidor de producao.

    npm run build && python scripts/telas-loja.py   -> loja/tela-*.png (1080x1920)
"""
import functools
import http.server
import json
import threading
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
SAIDA = RAIZ / "loja"
PORTA = 8766
LOCAL = "COLEGIO EXEMPLO"

hoje = date.today()
agora = f"{hoje.isoformat()}T07:%s:00"

NOMES = [
    ("Ana Beatriz Souza", "6º ano A"), ("Bruno Henrique Lima", "6º ano A"), ("Carla Mendes", "7º ano B"),
    ("Daniel Oliveira", "7º ano B"), ("Eduarda Ramos", "8º ano A"), ("Felipe Araújo", "8º ano A"),
    ("Gabriela Nunes", "9º ano A"), ("Heitor Cardoso", "9º ano A"),
]

LEITORES = [
    {"id": "l1", "nome": "Portão principal", "site": LOCAL, "status": "online"},
    {"id": "l2", "nome": "Portão lateral", "site": LOCAL, "status": "online"},
    {"id": "l3", "nome": "Secretaria", "site": LOCAL, "status": "online"},
]
PERFIL = {"tipo": "escola", "locais": [{"site": LOCAL, "tipo": "escola"}]}


def pessoa(i, nome, turma):
    return {
        "id": f"p{i}", "nome": nome, "tipo": "aluno", "cpf": "", "matricula": f"2026{i:03d}", "turma": turma,
        "site": LOCAL, "id_controladora": str(i), "responsavel": "", "telefone": "", "whatsapp": False,
        "ativo": True, "email": "", "avisa_email": False, "notas": "", "tem_foto": i != 5, "foto_em": "",
        "grupos": [turma], "ultima": "",
        "leitores": [{"leitor_id": l["id"], "leitor": l["nome"], "status": "ok", "erro": "", "quando": ""}
                     for l in LEITORES[:2]],
    }


PESSOAS = [pessoa(i + 1, n, t) for i, (n, t) in enumerate(NOMES)]
TURMAS = sorted({t for _, t in NOMES})

RESPOSTAS = {
    "/api/auth/me": {"user": {"username": "secretaria", "full_name": "Secretaria", "tenant_name": "Colégio Exemplo"}},
    "/api/access-control/painel/visao-geral": {
        "perfil": PERFIL,
        "leitores": {"total": 3, "online": 3, "lista": LEITORES},
        "pessoas": {"total": 412, "ativas": 405}, "fotos": {"ok": 398, "falhou": 2, "pendente": 5},
    },
    "/api/access-control/painel/ao-vivo": {
        "resumo": {"total": 318, "entries": 301, "exits": 17, "inside_now": 284},
        "passagens": [
            {"id": f"v{i}", "hora": agora % f"{55 - i * 3:02d}", "tipo": "entrada", "porta": LEITORES[i % 2]["nome"],
             "pessoa_id": f"p{i + 1}", "nome": n, "turma": t, "tipo_pessoa": "aluno", "tem_foto": False}
            for i, (n, t) in enumerate(NOMES[:7])
        ],
    },
    "/api/access-control/painel/pessoas": {
        "pessoas": PESSOAS, "perfil": PERFIL, "sites": [LOCAL],
        "grupos": [{"id": f"g{i}", "nome": t, "site": LOCAL, "ativo": True, "membros": 30 + i,
                    "leitores": [{"id": l["id"], "nome": l["nome"]} for l in LEITORES[:2]]}
                   for i, t in enumerate(TURMAS)],
    },
    "/api/access-control/painel/relatorios/catalogo": {
        "site": LOCAL, "modo": "escola",
        "vocab": {"grupo": "Turma", "grupos": "Turmas", "pessoa": "Aluno", "pessoas": "Alunos"},
        "relatorios": [
            {"id": "frequencia", "nome": "Frequência", "pergunta": "Quem está vindo às aulas?", "motor": "presenca"},
            {"id": "diario", "nome": "Dia", "pergunta": "Quem chegou e saiu hoje?", "motor": "diario"},
        ],
        "grupos": TURMAS, "quem": [],
    },
    "/api/access-control/painel/relatorios/r/frequencia": {
        "id": "frequencia", "nome": "Frequência", "pergunta": "Quem está vindo às aulas?", "motor": "presenca",
        "de": (hoje - timedelta(days=30)).isoformat(), "ate": (hoje - timedelta(days=1)).isoformat(),
        "resumo": {"pct": 94, "dias": 21, "criticos": 6}, "faltas_alerta": 3,
        "grupos": [
            {"grupo": "6º ano A", "pessoas": 32, "presencas": 650, "faltas": 22, "pct": 97, "vieram": 32, "criticos": 1},
            {"grupo": "7º ano B", "pessoas": 30, "presencas": 590, "faltas": 40, "pct": 94, "vieram": 30, "criticos": 2},
            {"grupo": "8º ano A", "pessoas": 31, "presencas": 580, "faltas": 71, "pct": 89, "vieram": 31, "criticos": 2},
            {"grupo": "9º ano A", "pessoas": 29, "presencas": 520, "faltas": 89, "pct": 85, "vieram": 29, "criticos": 1},
        ],
        "pessoas": [
            {"id": "p4", "nome": "Daniel Oliveira", "grupo": "7º ano B", "presencas": 16, "faltas": 5, "dias_falta": [], "pct": 76},
            {"id": "p6", "nome": "Felipe Araújo", "grupo": "8º ano A", "presencas": 17, "faltas": 4, "dias_falta": [], "pct": 81},
            {"id": "p8", "nome": "Heitor Cardoso", "grupo": "9º ano A", "presencas": 18, "faltas": 3, "dias_falta": [], "pct": 86},
        ],
    },
}


def responder(route):
    url = route.request.url
    caminho = "/" + url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
    corpo = RESPOSTAS.get(caminho)
    if corpo is None:
        route.fulfill(status=404, content_type="application/json", body='{"detail":"ficticio"}')
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(corpo))


def main():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORTA), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SAIDA.mkdir(exist_ok=True)
    base = f"http://127.0.0.1:{PORTA}/index.html"
    with sync_playwright() as p:
        nav = p.chromium.launch()
        # 360x640 com escala 3 = 1080x1920 (9:16, dentro do limite 2:1 da Play)
        ctx = nav.new_context(viewport={"width": 360, "height": 640}, device_scale_factor=3,
                              locale="pt-BR", is_mobile=True, has_touch=True)
        ctx.route("**/api/**", responder)

        # 1) Tela de entrada, sem sessao
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('acesso.apresentacao','1')")
        pg.goto(base)
        pg.wait_for_timeout(2500)
        pg.screenshot(path=str(SAIDA / "tela-1-entrada.png"))
        pg.close()

        # 2..5) Dentro do app, com sessao ficticia
        sessao = ("localStorage.setItem('acesso.apresentacao','1');"
                  "localStorage.setItem('acesso.permissoes','1');"
                  "localStorage.setItem('acesso.token','ficticio');"
                  f"localStorage.setItem('acesso.local','{LOCAL}');")
        for nome, rota in [("tela-2-inicio", "#/"), ("tela-3-pessoas", "#/pessoas"),
                           ("tela-4-relatorio", "#/relatorio"), ("tela-5-portas", "#/portas")]:
            pg = ctx.new_page()
            pg.add_init_script(sessao)
            pg.goto(base + rota)
            pg.wait_for_timeout(3000)
            pg.screenshot(path=str(SAIDA / f"{nome}.png"))
            pg.close()
        nav.close()
    srv.shutdown()
    print("capturas em", SAIDA)


if __name__ == "__main__":
    main()
