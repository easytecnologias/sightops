"""Gerador do Espiao no caixa sem Espiao (assets/pdv_coletor/sightops_pdv_espiao.py).

Escreve EspiaoDDMMAA.NNN a partir do CM + Teclas, na pasta do PDV, sem nunca
escrever num Espiao que nao e dele. Fixtures sinteticas (sem dado real). A
conferencia com dia real do PDV1 (Espiao de verdade x gerado: 99,8% das linhas
com o mesmo texto, cupons identicos) foi feita fora do repositorio.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import shutil

import pytest

from app.services import pdv_cm
from app.services.pdv_processador import ProcessadorDia

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(RAIZ, "tests", "fixtures", "pdv")
ASSETS = os.path.join(RAIZ, "app", "services", "assets", "pdv_coletor")
_spec = importlib.util.spec_from_file_location("gerador_espiao", os.path.join(ASSETS, "sightops_pdv_espiao.py"))
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)
DIA = dt.date(2026, 10, 27)


@pytest.fixture()
def pasta(tmp_path):
    p = tmp_path / "Cm"
    p.mkdir()
    shutil.copy(os.path.join(FIX, "CM271026.001"), p / "CM271026.001")
    shutil.copy(os.path.join(FIX, "Teclas271026.001"), p / "Teclas271026.001")
    return p


def _hora(h, m, s=0):
    return dt.datetime(2026, 10, 27, h, m, s)


def _espiao(p):
    with open(p / "Espiao271026.001", "rb") as f:
        return [b.rstrip(b"\r\n").decode("latin-1") for b in f]


def test_gera_o_espiao_do_dia_igual_ao_conversor(pasta):
    d = G.Dia(str(pasta), 1, DIA)
    d.ciclo(_hora(10, 0))
    linhas = _espiao(pasta)
    assert linhas[0] == "00:00:00" + G.MARCA
    so_cm = [l for l in linhas[1:] if ":NUM " not in l]
    esperado = [l for _, l in pdv_cm.converter(
        [(s, t) for s, t in enumerate(open(pasta / "CM271026.001", encoding="latin-1").read().splitlines(), 1)])]
    # o gerador tambem tira do Teclas: NUM, MTP e CSP; o resto e o mesmo conversor do servidor
    assert [l for l in so_cm if not any(x in l for x in (":MTP ", ":CSP ", ":CDP "))] == \
           [l for l in esperado if ":CDP " not in l]
    assert any(":NUM | Descricao: " in l for l in linhas)
    # em ordem de tempo e com fim de linha do PDV
    horas = [l[:8] for l in linhas[1:]]
    assert horas == sorted(horas)
    assert open(pasta / "Espiao271026.001", "rb").read().count(b"\r\n") == len(linhas)


def test_o_espiao_gerado_monta_os_mesmos_cupons(pasta):
    G.Dia(str(pasta), 1, DIA).ciclo(_hora(10, 0))
    esp = [(i, l) for i, l in enumerate(_espiao(pasta), 1)]
    a = ProcessadorDia("2026-10-27").receber(espiao=esp, final=True)
    cm = [(s, t) for s, t in enumerate(open(pasta / "CM271026.001", encoding="latin-1").read().splitlines(), 1)]
    b = ProcessadorDia("2026-10-27").receber(cm=cm, final=True)
    chave = lambda s: {c["cupom"]: (c["situacao"], c["itens"], c["total_centavos"], c["pagamento"]) for c in s["cupons"]}
    assert chave(a) == chave(b)
    assert chave(a)["1002"] == ("fechado", 1, 540, "PIX")


def test_nao_escreve_no_espiao_do_caixa(pasta):
    (pasta / "Espiao271026.001").write_bytes(b"00:00:00---------- 1.93.54 / Linux ----------\r\n")
    d = G.Dia(str(pasta), 1, DIA)
    assert d.ciclo(_hora(10, 0)) == 0 and d.parado
    assert _espiao(pasta) == ["00:00:00---------- 1.93.54 / Linux ----------"]


def test_espera_o_caixa_criar_o_dele_na_virada(pasta):
    d = G.Dia(str(pasta), 1, DIA)
    d.ciclo(_hora(0, 1))
    assert not (pasta / "Espiao271026.001").exists()
    d.ciclo(_hora(0, 4))
    assert (pasta / "Espiao271026.001").exists()


def test_caixa_fechado_sem_cm_nao_cria(pasta):
    os.remove(pasta / "CM271026.001")
    G.Dia(str(pasta), 1, DIA).ciclo(_hora(10, 0))
    assert not (pasta / "Espiao271026.001").exists()


def test_para_se_o_caixa_comecar_a_gravar_no_arquivo(pasta):
    cm = (pasta / "CM271026.001").read_bytes()
    corte = cm.index(b"08:03:00.200")
    (pasta / "CM271026.001").write_bytes(cm[:corte])
    d = G.Dia(str(pasta), 1, DIA)
    d.ciclo(_hora(10, 0))
    with open(pasta / "Espiao271026.001", "ab") as f:  # o caixa passou a gravar o dele
        f.write(b"10:00:01:GAV|\r\n")
    (pasta / "CM271026.001").write_bytes(cm)
    d.ciclo(_hora(10, 1))
    assert d.parado and _espiao(pasta)[-1] == "10:00:01:GAV|"


def test_reiniciou_no_meio_do_dia_nao_repete(pasta):
    cm = (pasta / "CM271026.001").read_bytes()
    corte = cm.index(b"08:03:00.200")
    (pasta / "CM271026.001").write_bytes(cm[:corte])
    G.Dia(str(pasta), 1, DIA).ciclo(_hora(10, 0))
    meio = _espiao(pasta)
    (pasta / "CM271026.001").write_bytes(cm)
    G.Dia(str(pasta), 1, DIA).ciclo(_hora(10, 1))  # processo novo: rele do comeco
    depois = _espiao(pasta)
    assert depois[:len(meio)] == meio
    os.rename(pasta / "Espiao271026.001", pasta / "antes.txt")
    G.Dia(str(pasta), 1, DIA).ciclo(_hora(10, 2))
    assert sorted(depois) == sorted(_espiao(pasta))  # mesmo conteudo de quem rodou o dia sem parar


def test_ultimo_cupom_fecha_mesmo_com_o_caixa_parado(pasta):
    cm = (pasta / "CM271026.001").read_bytes()
    corte = cm.index(b"08:03:52.100")  # sem o FINAL PAGAMENTO do cupom 1002 nem nada depois
    (pasta / "CM271026.001").write_bytes(cm[:corte])
    d = G.Dia(str(pasta), 1, DIA)
    d.ciclo(_hora(8, 3, 50))
    assert not any("FECHACUPOM | Cod: 1002" in l for l in _espiao(pasta))
    d.ciclo(_hora(8, 5, 0))  # passou FECHA_SEM_FINAL sem linha nova
    assert any("FECHACUPOM | Cod: 1002" in l for l in _espiao(pasta))


def test_instalador_leva_o_gerador_e_o_conversor():
    from app.services import pdv_instalador as I
    for nome in ("sightops_pdv_espiao.py", "sightops-pdv-espiao.service", "pdv_cm.py"):
        assert nome in I.ARQUIVOS
        assert os.path.exists(I._ORIGEM.get(nome) or os.path.join(I.ASSETS, nome))
    sh = open(os.path.join(ASSETS, "instalar.sh"), encoding="utf-8").read()
    assert "sightops-pdv-espiao" in sh and "pdv_cm.py" in sh
