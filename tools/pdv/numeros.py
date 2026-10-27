"""Numeros da secao 5 do briefing do modulo PDV, lidos de uma pasta de amostra.

Uso (a amostra fica FORA do repositorio -- tem nome de funcionario e CPF):
    python tools/pdv/numeros.py <pasta com Espiao*.001 e Teclas*.001> [--estacao 1]

Imprime cada medida ao lado do numero de referencia (PDV1, 28/08 a 26/10/2026).
"""
import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from app.services import pdv_leitor as L  # noqa: E402

# medida -> (chave de contagem, chave de valor, referencia contagem, referencia valor)
REFERENCIA = [
    ("Cupons (ABRECUPOM)", "cupons", None, 15192, None),
    ("Itens (VIT dentro de cupom)", "itens", "valor_itens", 263051, "2099944.93"),
    ("  bipados", "item_scanner", None, 237095, None),
    ("  digitados", "item_manual", None, 18686, None),
    ("  menu", "item_menu", None, 2533, None),
    ("  sem tecla", "item_sem_tecla", None, 4723, None),
    ("  outro (nao classificado)", "item_outro", None, None, None),
    ("Cancelamento de item (CIT)", "cit", "valor_cit", 702, "9880.40"),
    ("  por 1.000 itens", "cit_por_mil", None, 2.67, None),
    ("Cancelamento de cupom (CCV+CCG)", "cancela_cupom", "valor_cancela_cupom", 57, "18692.41"),
    ("CCV refeito <= 30 min", "ccv_refeito", None, 21, None),
    ("CCV nao refeito", "ccv_nao_refeito", "valor_ccv_nao_refeito", 24, "8611.60"),
    ("Desconto em item (DIT)", "dit", None, 8666, None),
    ("Itens sem cadastro (ITEMSEMCAD)", "itemsemcad", None, 1330, None),
    ("Sangrias (SGR)", "sgr", None, 300, None),
    ("Digitado de produto normalmente bipado", "digitado_fora_padrao", "valor_digitado_fora_padrao",
     596, "13695.17"),
    ("  por 1.000 itens", "digitado_fora_padrao_por_mil", None, 2.27, None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("--estacao", type=int, default=1)
    ap.add_argument("--incluir-dia-sem-teclas", action="store_true")
    a = ap.parse_args()

    dias = list(L.dias_da_pasta(a.pasta, a.estacao, exigir_teclas=not a.incluir_dia_sem_teclas))
    r = L.numeros(dias)
    if dias:
        print("Periodo: %s a %s (%d dias)" % (dias[0].data, dias[-1].data, len(dias)))
    sem_tec = [d.data for d in dias if not d.tem_teclas]
    if sem_tec:
        print("Dias sem Teclas (itens como sem_tecla): %s" % ", ".join(map(str, sem_tec)))
    print("%-42s %10s %10s %16s %16s  %s" % ("medida", "lido", "ref", "R$ lido", "R$ ref", ""))
    diverge = 0
    for nome, k, kv, ref, refv in REFERENCIA:
        lido = r.get(k, 0)
        vlido = r.get(kv, Decimal("0.00")) if kv else None
        ok = (ref is None or lido == ref) and (refv is None or vlido == Decimal(refv))
        diverge += 0 if ok else 1
        print("%-42s %10s %10s %16s %16s  %s" % (
            nome, lido, "" if ref is None else ref, "" if vlido is None else vlido,
            refv or "", "ok" if ok else "DIFERENTE"))
    print("\n%s" % ("Tudo igual a referencia." if not diverge else "%d medida(s) diferente(s)." % diverge))
    return 1 if diverge else 0


if __name__ == "__main__":
    sys.exit(main())
