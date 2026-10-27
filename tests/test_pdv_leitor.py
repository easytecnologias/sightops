"""Leitor do PDV (Espiao + Teclas): como o item entrou e os numeros de auditoria.

A fixture em tests/fixtures/pdv e sintetica, no formato real do PDV1 (sem nome
de funcionario nem documento de cliente). A amostra real nunca entra no repo.
"""
from __future__ import annotations

import os
import subprocess
import sys
from decimal import Decimal

import pytest

from app.services import pdv_leitor as L

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(RAIZ, "tests", "fixtures", "pdv")
ESP = os.path.join(FIX, "Espiao271026.001")
TEC = os.path.join(FIX, "Teclas271026.001")


def test_nome_do_arquivo():
    import datetime as dt
    assert L.info_arquivo("Espiao271026.001") == ("Espiao", dt.date(2026, 10, 27), 1)
    assert L.info_arquivo("/x/TECLAS010926.008") == ("Teclas", dt.date(2026, 9, 1), 8)
    assert L.info_arquivo("CM311026.001")[0] == "CM"
    assert L.info_arquivo("Espiao321326.001") is None
    assert L.info_arquivo("Espiao271026.001.bak") is None


def test_linha_do_espiao():
    ev = L.ler_linha_espiao("08:01:13:VIT | Cod: 0011723 | Descricao: PAO | VlTotal: 9,98 | Desc2: 2117230009982|\r\n")
    assert (ev.hora, ev.tipo, ev.get("Cod"), ev.get("Desc2")) == ("08:01:13", "VIT", "0011723", "2117230009982")
    assert L.ler_linha_espiao("09:00:00:GAV|").tipo == "GAV"
    assert L.ler_linha_espiao("lixo") is None


def test_valor_em_reais():
    assert L.valor("1.234,5".replace(".", "")) == Decimal("1234.5")
    assert L.valor("18,90") == Decimal("18.90") and L.valor("") == 0 and L.valor("abc") == 0


def test_teclas_separa_scanner_numerico_menu_e_descarta_senha():
    entradas = L.ler_teclas(TEC)
    modos = {}
    for e in entradas:
        modos.setdefault(e.codigo, []).append(e.modo)
    assert modos["7891000460498"] == ["scanner"] * 3
    assert modos["2117230009982"] == ["scanner"]
    assert modos["123"] == ["manual"]
    assert modos["456"] == ["menu"]
    assert modos["1234567"] == ["outro"]   # fileira de cima, mas devagar e longo
    # "12" antes do campo mascarado nao vira codigo
    assert "12" not in modos and "" not in modos


def test_cada_item_sabe_como_entrou():
    dia = L.ler_dia(ESP, TEC)
    modos = [(i.cupom, i.codigo, i.modo) for i in dia.itens]
    assert modos == [
        ("1001", "7891000460498", "scanner"),
        ("1001", "11723", "scanner"),        # balanca: casou pelo Desc2 da etiqueta
        ("1001", "123", "manual"),
        ("1001", "456", "menu"),
        ("1001", "789", "sem_tecla"),
        ("1001", "1234567", "outro"),
        ("1002", "7891000460498", "scanner"),
        ("1003", "7891000460498", "scanner"),
        ("1004", "7891234567895", "scanner"),
    ]
    assert all(i.operador == "Operador 01" for i in dia.itens)


def test_entrada_do_teclas_so_vale_para_um_item():
    entradas = [L.Entrada(100.0, "789", "scanner")]
    c = L.Casador(entradas)
    assert c.modo(101, "789") == "scanner"
    assert c.modo(102, "789") == "sem_tecla"
    assert L.Casador(entradas).modo(106, "789") == "sem_tecla"  # mais de 5 s


def test_dia_sem_teclas_tudo_sem_tecla():
    dia = L.ler_dia(ESP, None)
    assert dia.itens and {i.modo for i in dia.itens} == {"sem_tecla"}
    assert dia.tem_teclas is False


def test_numeros_da_fixture():
    r = L.numeros(L.dias_da_pasta(FIX))
    assert r["dias"] == 1 and r["cupons"] == 4
    assert r["itens"] == 9 and r["valor_itens"] == Decimal("137.18")
    assert (r["item_scanner"], r["item_manual"], r["item_menu"], r["item_sem_tecla"], r["item_outro"]) == (
        5, 1, 1, 1, 1)
    assert (r["cit"], r["valor_cit"]) == (1, Decimal("18.90"))
    assert (r["cancela_cupom"], r["valor_cancela_cupom"]) == (3, Decimal("75.90"))
    assert (r["ccv_refeito"], r["ccv_nao_refeito"], r["valor_ccv_nao_refeito"]) == (1, 1, Decimal("50.00"))
    assert (r["dit"], r["itemsemcad"], r["sgr"]) == (1, 1, 1)
    assert r["cit_por_mil"] == round(1000 / 9, 2)


def _item(cod, modo, v="10"):
    return L.Item(codigo=cod, modo=modo, valor=Decimal(v), cupom="1", operador="Operador 01")


def test_digitado_de_produto_normalmente_bipado():
    itens = (
        [_item("A", "scanner")] * 25 + [_item("A", "manual", "7,50".replace(",", "."))] * 2  # 2/27 < 10%
        + [_item("B", "scanner")] * 18 + [_item("B", "manual")]                           # 19 vendas: pouco
        + [_item("C", "scanner")] * 20 + [_item("C", "menu")] * 3                         # 13%: hortifruti
    )
    r = L.numeros([L.Dia(None, 1, [], itens, True)])
    assert r["digitado_fora_padrao"] == 2 and r["valor_digitado_fora_padrao"] == Decimal("15.00")


def test_ccv_so_e_refeito_com_mesmo_valor_em_30_min():
    ev = lambda h, t, v: L.ler_linha_espiao("%s:%s | Cod: 1 | VlTotal: %s|" % (h, t, v))
    eventos = [ev("10:00:00", "CCV", "10,00"), ev("10:31:00", "FECHACUPOM", "10,00"),
               ev("11:00:00", "CCV", "20,00"), ev("11:10:00", "FECHACUPOM", "20,00"),
               ev("12:00:00", "CCV", "30,00"), ev("12:01:00", "FECHACUPOM", "30,01")]
    assert [r for _, r in L.ccv_refeitos(eventos)] == [False, True, False]


def test_latin1_e_crlf(tmp_path):
    p = tmp_path / "Espiao010926.001"
    p.write_bytes("08:00:00:VIT | Cod: 1 | Descricao: P\xc3O FRANC\xcaS | VlTotal: 1,00|\r\n".encode("latin-1"))
    ev = next(L.ler_espiao(str(p)))
    assert ev.get("Descricao") == "P\xc3O FRANC\xcaS" and ev.get("VlTotal") == "1,00"


def test_numeros_cli_compara_com_referencia():
    out = subprocess.run([sys.executable, os.path.join(RAIZ, "tools", "pdv", "numeros.py"), FIX],
                         capture_output=True, text=True, cwd=RAIZ)
    assert "Cupons (ABRECUPOM)" in out.stdout and "DIFERENTE" in out.stdout  # fixture != 60 dias
    assert out.returncode == 1


def test_anonimizar_tira_nome_e_documento_e_mantem_os_numeros(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    nome, cpf = "MARIA APARECIDA SOUZA", "12345678909"
    esp = open(ESP, encoding="latin-1").read().replace("Operador 01", nome).replace(
        "Cod: 00000000000 | Descricao: CLIENTE", "Cod: %s | Descricao: JOAO CLIENTE DA SILVA" % cpf)
    (real / "Espiao271026.001").write_bytes(esp.encode("latin-1"))
    tec = open(TEC, encoding="latin-1").read().replace("[REGISTRANDO]", "[CAIXA MARIA]")
    tec += "08:02:24.000|K:97|A:NUM|R:1|S:N|[]|\r\n08:02:24.300|K:98|A:NUM|R:2|S:N|[]|\r\n" \
           "08:02:25.000|K:CPF|A:CLI|R:|S:N|[CPF 123.456.789-09]|\r\n08:02:26.000|K:0|A:TECDO:x|R:|S:N|[]|\r\n"
    (real / "Teclas271026.001").write_bytes(tec.encode("latin-1"))

    saida = tmp_path / "anon"
    out = subprocess.run([sys.executable, os.path.join(RAIZ, "tools", "pdv", "anonimizar.py"),
                          str(real / "Espiao271026.001"), str(real / "Teclas271026.001"), str(saida)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    texto = (saida / "Espiao271026.001").read_text("latin-1") + (saida / "Teclas271026.001").read_text("latin-1")
    for proibido in ("MARIA", "SOUZA", "APARECIDA", "JOAO", cpf, "123.456.789-09", "TECDO"):
        assert proibido not in texto.upper()
    antes, depois = L.numeros(L.dias_da_pasta(str(real))), L.numeros(L.dias_da_pasta(str(saida)))
    assert antes == depois
