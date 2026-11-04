"""Regras do Ponto de venda (momentos para olhar): casos montados a mao, no
formato de pdv_eventos / pdv_itens / pdv_cupons. Nomes ficticios."""
from __future__ import annotations

import json
from collections import Counter

from app.services import pdv_regras as R

DIA = "2026-11-03"


def ev(seq, hora, tipo, cupom="", valor=0, operador="Operador 01", **campos):
    return {"seq": seq, "ts": "%s %s" % (DIA, hora), "tipo": tipo, "cupom": cupom, "operador": operador,
            "codigo": campos.pop("codigo", ""), "descricao": "", "valor_centavos": valor,
            "campos_json": json.dumps(campos)}


def it(seq, hora, cupom, codigo, descricao, valor, modo="scanner"):
    return {"seq": seq, "ts": "%s %s" % (DIA, hora), "cupom": cupom, "operador": "Operador 01",
            "codigo": codigo, "descricao": descricao, "valor_centavos": valor, "modo": modo}


def regras(ms):
    return [(m["regra"], m["gravidade"]) for m in ms]


# ------------------------------------------------------------------ gaveta

def test_gaveta_depois_do_troco_e_normal():
    evs = [ev(1, "10:00:00", "FIN", "100", 5000, Descricao="DINHEIRO", Cod="1"),
           ev(2, "10:00:02", "TRC", "100", 1000), ev(3, "10:00:10", "GAV", "100")]
    assert R.avaliar(evs, [], []) == []


def test_gaveta_da_sangria_e_da_troca_de_operador_e_normal():
    evs = [ev(1, "09:31:26", "GAV"), ev(2, "09:31:34", "SGR", valor=100000),
           ev(3, "13:05:23", "GAV"), ev(4, "13:05:40", "EOP", Descricao="Operador 02")]
    assert R.avaliar(evs, [], []) == []


def test_gaveta_sem_nada_perto_e_alta_e_com_supervisor_e_media():
    evs = [ev(1, "15:00:00", "FECHACUPOM", "100", 900), ev(2, "15:05:00", "GAV"),
           ev(3, "18:33:11", "SUPERVISOR", Descricao="Supervisor 01"), ev(4, "18:33:49", "GAV")]
    ms = R.avaliar(evs, [], [])
    assert regras(ms) == [("gaveta_sem_venda", "media"), ("gaveta_sem_venda", "alta")]
    assert "Supervisor 01" in ms[0]["detalhe"]


# ------------------------------------------------------------------ cupom cancelado

def test_cupom_cancelado_e_refeito_nao_acusa():
    evs = [ev(1, "10:16:50", "CCV", "200", 21834)]
    cupons = [{"cupom": "201", "situacao": "fechado", "aberto_em": DIA + " 10:18:00", "total_centavos": 21800}]
    assert R.avaliar(evs, [], cupons) == []


def test_cupom_cancelado_nao_refeito_e_alta_e_avisa_dinheiro():
    evs = [ev(1, "10:15:00", "FIN", "200", 25000, Descricao="DINHEIRO", Cod="1"),
           ev(2, "10:16:50", "CCV", "200", 21834)]
    cupons = [{"cupom": "201", "situacao": "fechado", "aberto_em": DIA + " 11:30:00", "total_centavos": 21834}]
    ms = R.avaliar(evs, [], cupons)
    assert regras(ms) == [("cupom_cancelado", "alta")]
    assert ms[0]["valor_centavos"] == 21834 and "dinheiro" in ms[0]["detalhe"]


# ------------------------------------------------------------------ item cancelado

def test_item_cancelado_niveis():
    evs = [
        # barato antes do subtotal: nao acusa
        ev(1, "08:00:00", "CIT", "300", 500, Descricao="Bala"),
        # barato depois do subtotal: baixa
        ev(2, "08:10:00", "SBT", "301", 2000), ev(3, "08:10:05", "CIT", "301", 500, Descricao="Chiclete"),
        # caro antes do subtotal: media
        ev(4, "08:20:00", "CIT", "302", 4500, Descricao="Picanha Kg"),
        # caro depois do subtotal: alta
        ev(5, "08:30:00", "SBT", "303", 9000), ev(6, "08:30:05", "CIT", "303", 4500, Descricao="Picanha Kg"),
        # liberado por quem opera: alta mesmo barato
        ev(7, "08:40:00", "SUPERVISOR", "304", operador="Operador 01", Descricao="Operador 01"),
        ev(8, "08:40:03", "CIT", "304", 300, Descricao="Pao"),
    ]
    ms = {m["cupom"]: m for m in R.avaliar(evs, [], [])}
    assert "300" not in ms
    assert ms["301"]["gravidade"] == "baixa"
    assert ms["302"]["gravidade"] == "media"
    assert ms["303"]["gravidade"] == "alta" and ms["303"]["titulo"] == "Item cancelado depois do subtotal"
    assert ms["304"]["gravidade"] == "alta" and "próprio operador" in ms["304"]["titulo"]


def test_supervisor_com_acento_diferente_ainda_e_o_proprio_operador():
    evs = [ev(1, "08:40:00", "SUPERVISOR", "304", operador="Jose Antonio", Descricao="José  Antônio"),
           ev(2, "08:40:03", "CIT", "304", 300, operador="Jose Antonio", Descricao="Pao")]
    assert regras(R.avaliar(evs, [], [])) == [("item_cancelado", "alta")]


# ------------------------------------------------------------------ sem cadastro

def test_sem_cadastro_bipado_de_novo_ou_codigo_parecido_nao_acusa():
    evs = [ev(1, "10:00:00", "ITEMSEMCAD", "400", codigo="0789890319078"),
           ev(5, "10:05:00", "ITEMSEMCAD", "401", codigo="7891991002189")]
    its = [it(2, "10:00:05", "400", "7898903159078", "Ovos C 30", 1699, "manual"),
           it(6, "10:05:04", "401", "7891991000826", "Refri Lata", 402, "scanner")]
    assert R.avaliar(evs, its, []) == []


def test_sem_cadastro_e_outro_produto_digitado_e_media():
    evs = [ev(1, "10:00:00", "ITEMSEMCAD", "400", codigo="7891234567895")]
    its = [it(2, "10:00:20", "400", "224", "Laranja Kg", 541, "manual")]
    ms = R.avaliar(evs, its, [])
    assert regras(ms) == [("sem_cadastro_digitado", "media")]


def test_etiqueta_da_balanca_trocada_por_item_barato_e_alta():
    assert R.preco_etiqueta("0200383010322") == 1032
    assert R.preco_etiqueta("7891234567895") is None
    evs = [ev(1, "10:00:00", "ITEMSEMCAD", "400", codigo="2003830050009"),   # etiqueta de R$ 50,00
           ev(3, "10:10:00", "ITEMSEMCAD", "401", codigo="0200383010322")]   # etiqueta de R$ 10,32
    its = [it(2, "10:00:15", "400", "224", "Laranja Kg", 541, "manual"),
           it(4, "10:10:10", "401", "383", "Bacon Kg", 1032, "manual")]
    ms = R.avaliar(evs, its, [])
    assert regras(ms) == [("sem_cadastro_digitado", "alta")]
    assert ms[0]["cupom"] == "400" and "R$ 50,00" in ms[0]["detalhe"]


# ------------------------------------------------------------------ digitado / parado

def test_digitado_o_que_costuma_ser_bipado():
    base = {"7896": Counter(scanner=95, manual=5), "1001": Counter(menu=40, manual=10), "7899": Counter(scanner=5)}
    its = [it(1, "11:00:00", "500", "7896", "Feijao 1kg", 799, "manual"),
           it(2, "11:00:10", "500", "1001", "Alface", 299, "manual"),       # costuma ir pelo menu
           it(3, "11:00:20", "500", "7899", "Raro", 5000, "manual"),        # pouco historico
           it(4, "11:00:30", "500", "7896", "Feijao 1kg", 799, "scanner")]
    ms = R.avaliar([], its, [], base)
    assert regras(ms) == [("digitado_fora_padrao", "media")]
    assert "95%" in ms[0]["detalhe"]


def test_cupom_parado_dois_minutos_entre_itens():
    its = [it(1, "12:00:00", "600", "1", "A", 100), it(2, "12:00:30", "600", "2", "B", 100),
           it(3, "12:03:10", "600", "3", "C", 100)]
    ms = R.avaliar([], its, [])
    assert regras(ms) == [("cupom_parado", "baixa")]
    assert ms[0]["ts"] == DIA + " 12:00:30" and ms[0]["titulo"] == "Cupom parado 2 min"


# ------------------------------------------------------------------ fora da media

def test_operador_fora_da_media_da_loja():
    ms = ([{"loja": "L", "operador": "Operador 01", "gravidade": "alta", "regra": "gaveta_sem_venda"}] * 6
          + [{"loja": "L", "operador": "Operador 02", "gravidade": "media", "regra": "item_cancelado"}] * 2
          + [{"loja": "L", "operador": "Operador 03", "gravidade": "baixa", "regra": "cupom_parado"}] * 50)
    cup = {("L", "Operador 01"): 100, ("L", "Operador 02"): 100, ("L", "Operador 03"): 100}
    fora = R.fora_da_media(ms, cup)
    assert [f["operador"] for f in fora] == ["Operador 01"]
    assert fora[0]["vezes"] == 2.2 and fora[0]["regra_principal"] == "gaveta_sem_venda"
