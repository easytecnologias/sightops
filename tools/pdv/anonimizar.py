"""Gera fixture ANONIMIZADA de um dia do PDV (Espiao + Teclas) para os testes.

A amostra real tem nome de funcionario e CPF/CNPJ de cliente e nao pode ir
para o repositorio (que e publico). Este script:
  - corta uma janela de horas;
  - troca nome de operador/supervisor por "Operador NN" e o id por 90NN
    (em todas as linhas dos dois arquivos, inclusive o texto de tela do Teclas);
  - mascara CLIENTE (documento -> zeros, nome -> CLIENTE) e qualquer CPF/CNPJ visto;
  - tira a senha: linhas TECDO: saem, NUM com valor mascarado vira R:*, e digitos
    que nao terminam em CDP (CPF, quantidade, senha) viram 0;
  - confere a saida e recusa gravar se sobrou algum nome ou documento.

Uso:
    python tools/pdv/anonimizar.py <Espiao.001> <Teclas.001> <pasta saida> --de 10:00 --ate 13:00
Revise a saida a olho antes de versionar.
"""
import argparse
import os
import re
import sys

COD = "latin-1"
COM_NOME = {"VENDACF", "ABRECUPOM", "FECHACUPOM", "CCV", "CCG", "EOP", "SOP", "SUPERVISOR"}
COM_ID = {"EOP", "SOP", "SUPERVISOR", "SGR"}
HORA = re.compile(r"^(\d{2}:\d{2}:\d{2})")
ESP = re.compile(r"^(\d{2}:\d{2}:\d{2}):([A-Z]+)\s*\|(.*)$")
TEC = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d+)\|K:([^|]*)\|A:([^|]*)\|R:([^|]*)\|(.*)$")
JA_ANONIMO = re.compile(r"^Operador \d+$")
CPF_FMT = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")


def ler(caminho):
    with open(caminho, encoding=COD, errors="replace", newline="") as f:
        return [l.rstrip("\r\n") for l in f]


def gravar(caminho, linhas):
    with open(caminho, "w", encoding=COD, errors="replace", newline="") as f:
        for l in linhas:
            f.write(l + "\r\n")


def campos(corpo):
    out = {}
    for p in corpo.split("|"):
        if ":" in p:
            k, v = p.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def na_janela(linha, de, ate, ultima):
    m = HORA.match(linha)
    return (de <= m.group(1) < ate) if m else ultima


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("espiao")
    ap.add_argument("teclas")
    ap.add_argument("saida")
    ap.add_argument("--de", default="00:00")
    ap.add_argument("--ate", default="24:00")
    a = ap.parse_args()
    de, ate = [h if len(h) == 8 else h + ":00" for h in (a.de, a.ate)]

    esp, tec = ler(a.espiao), ler(a.teclas)

    # 1. quem aparece (no dia inteiro, nao so na janela: o nome pode estar na tela)
    nomes, ids, docs = {}, {}, set()
    for l in esp:
        m = ESP.match(l)
        if not m:
            continue
        ev, f = m.group(2), campos(m.group(3))
        d = f.get("Descricao", "")
        if ev in COM_NOME and d and not d.replace(",", "").replace(".", "").isdigit() and not JA_ANONIMO.match(d):
            nomes.setdefault(f["Descricao"], "Operador %02d" % (len(nomes) + 1))
        if ev in COM_ID and f.get("Cod", "").isdigit():
            ids.setdefault(f["Cod"], "90%02d" % (len(ids) + 1))
        if ev == "CLIENTE":
            d = re.sub(r"\D", "", f.get("Cod", ""))
            if len(d) >= 11:
                docs.add(d)

    troca_nome = sorted(nomes.items(), key=lambda kv: -len(kv[0]))
    padroes = [(re.compile(re.escape(n), re.I), novo) for n, novo in troca_nome]
    # pedacos do nome (>= 4 letras) tambem saem: a tela pode mostrar so o primeiro nome
    pedacos = sorted({p for n in nomes for p in re.split(r"\W+", n) if len(p) >= 4}, key=len, reverse=True)
    padroes += [(re.compile(r"\b%s\b" % re.escape(p), re.I), "OPERADOR") for p in pedacos]

    def limpa(texto):
        for rx, novo in padroes:
            texto = rx.sub(novo, texto)
        texto = CPF_FMT.sub("000.000.000-00", texto)
        for d in docs:
            texto = texto.replace(d, "0" * len(d))
        return texto

    # 2. Espiao
    out_esp, dentro = [], False
    for l in esp:
        dentro = na_janela(l, de, ate, dentro)
        if not dentro:
            continue
        m = ESP.match(l)
        if m:
            ev, f = m.group(2), campos(m.group(3))
            if ev == "CLIENTE":
                l = "%s:CLIENTE | Cod: 00000000000 | Descricao: CLIENTE|" % m.group(1)
            elif ev in COM_ID and f.get("Cod") in ids:
                l = re.sub(r"(Cod:\s*)%s\b" % re.escape(f["Cod"]), r"\g<1>" + ids[f["Cod"]], l)
        out_esp.append(limpa(l))

    # 3. Teclas: digitos so ficam se a sequencia fecha com CDP (codigo de produto)
    out_tec, dentro, seq = [], False, []

    def fecha(com_cdp):
        for i in seq:
            if not com_cdp:
                m = TEC.match(out_tec[i])
                k = m.group(2)
                k0 = "48" if k.isdigit() and 48 <= int(k) <= 57 else ("96" if k.isdigit() and 96 <= int(k) <= 105 else k)
                out_tec[i] = "%s|K:%s|A:NUM|R:0|S:N|" % (m.group(1), k0)
        del seq[:]

    for l in tec:
        dentro = na_janela(l, de, ate, dentro)
        if not dentro and HORA.match(l):
            continue
        if "TECDO:" in l:
            continue
        m = TEC.match(l)
        if not m:
            out_tec.append(limpa(l))
            continue
        a_, r = m.group(3), m.group(4)
        if a_ == "NUM":
            if len(r) == 1 and r.isdigit():
                out_tec.append("%s|K:%s|A:NUM|R:%s|S:N|" % (m.group(1), m.group(2), r))
                seq.append(len(out_tec) - 1)
            else:
                fecha(False)
                out_tec.append("%s|K:%s|A:NUM|R:*|S:N|" % (m.group(1), m.group(2)))
            continue
        fecha(a_ == "CDP")
        out_tec.append(limpa(l))
    fecha(False)

    # 4. conferencia: nada de nome nem documento na saida
    sobra = []
    texto = "\n".join(out_esp + out_tec)
    for n in list(nomes) + pedacos:
        if re.search(r"\b%s\b" % re.escape(n), texto, re.I):
            sobra.append(n)
    for d in docs:
        if d in texto:
            sobra.append("documento ...%s" % d[-3:])
    if sobra:
        print("RECUSADO: sobrou %d nome/documento na saida (nao mostrados aqui)." % len(sobra))
        return 2

    os.makedirs(a.saida, exist_ok=True)
    gravar(os.path.join(a.saida, os.path.basename(a.espiao)), out_esp)
    gravar(os.path.join(a.saida, os.path.basename(a.teclas)), out_tec)
    print("Espiao: %d linhas, Teclas: %d linhas, %d nomes e %d ids trocados, %d documentos mascarados."
          % (len(out_esp), len(out_tec), len(nomes), len(ids), len(docs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
