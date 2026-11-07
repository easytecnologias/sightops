"""Deteccao de pessoa pelo calor (app/services/termico_deteccao.py) contra a
matriz REAL da HM-TD2628-8/QA/BR 03 - CAM P 03 (10.0.0.81, UFV-RODOANEL),
capturada em 05/11/2026 13:47 com o sol a pino: chao 24-56 °C.

A "pessoa" e desenhada por cima do quadro real: 34 °C, do tamanho que um
adulto ocupa a ~20 m nessa lente (6x14 pontos). Nada sai para a rede."""
from array import array
from pathlib import Path

import pytest

from app.services import termico_deteccao as T

FX = Path(__file__).parent / "fixtures" / "termico"
W, H = 256, 192


def _quadro(nome: str = "quadro1") -> T.Quadro:
    temps = array("f")
    temps.frombytes((FX / f"{nome}.temps.bin").read_bytes())
    return T.Quadro(W, H, temps)


def _com_pessoa(q: T.Quadro, x0=170, y0=90, larg=6, alt=14, temp=34.0) -> T.Quadro:
    temps = array("f", q.temps)
    for y in range(y0, y0 + alt):
        for x in range(x0, x0 + larg):
            temps[y * W + x] = temp
    return T.Quadro(W, H, temps)


# ------------------------------------------------------------ leitura -------
def _multipart(q_json: bytes, termico: bytes, matriz: bytes) -> bytes:
    def parte(tipo, dado):
        return (b"--boundary\r\nContent-Disposition: form-data;\r\nContent-Type: " + tipo
                + b"\r\nContent-Length:" + str(len(dado)).encode() + b"\r\n\r\n" + dado + b"\r\n")
    return (parte(b'application/json; charset="UTF-8"', q_json) + parte(b"image/pjpeg", termico)
            + parte(b"application/octet-stream", matriz) + parte(b"image/pjpeg", b"\xff\xd8visivel") + b"--boundary--\r\n")


def test_le_resposta_multipart_da_camera():
    import json
    info = json.loads((FX / "quadro1.json").read_text(encoding="utf-8"))["info"]
    corpo = _multipart(json.dumps({"JpegPictureWithAppendData": info}).encode(),
                       (FX / "quadro1.termico.jpg").read_bytes(), (FX / "quadro1.temps.bin").read_bytes())
    q = T.ler_quadro(corpo, "multipart/form-data; boundary=boundary")
    assert (q.largura, q.altura) == (256, 192)
    assert q.resumo() == {"min": 24.3, "max": 56.2, "media": 44.3}
    assert q.jpeg_termico[:2] == b"\xff\xd8"
    assert q.jpeg_visivel.startswith(b"\xff\xd8visivel")


def test_matriz_que_termina_em_crlf_nao_perde_bytes():
    # O ultimo float pode ter bytes \r\n; quem corta pelo final come a matriz.
    import json
    info = {"jpegPicWidth": 2, "jpegPicHeight": 1, "temperatureDataLength": 4}
    matriz = array("f", [30.0, 0.0]).tobytes()[:4] + b"\x00\x00\r\n"
    corpo = _multipart(json.dumps({"JpegPictureWithAppendData": info}).encode(), b"\xff\xd8", matriz)
    q = T.ler_quadro(corpo, "multipart/form-data; boundary=boundary")
    assert len(q.temps) == 2 and q.temps[0] == 30.0


def test_medicao_desligada_vira_erro_claro():
    with pytest.raises(ValueError, match="medicao desligada"):
        T.ler_quadro(b'{"statusCode":4,"statusString":"Invalid Operation"}', "application/json")


# ----------------------------------------------------------- deteccao -------
def test_quadro_real_sem_ninguem_nao_dispara():
    v = T.Vigia(T.Regra(quadros_seguidos=1))
    v.processar(_quadro("quadro1"), 0)
    manchas, disparo = v.processar(_quadro("quadro2"), 2)
    assert disparo is None
    assert manchas == []


def test_pessoa_mais_fria_que_o_chao_ao_sol_dispara():
    q = _quadro("quadro1")
    fundo_ali = sum(q.t(x, y) for y in range(90, 104) for x in range(170, 176)) / 84
    assert fundo_ali > 40          # estrada ao sol: a pessoa vai ser a mancha FRIA
    v = T.Vigia(T.Regra(quadros_seguidos=1, movimento_min=0))
    v.processar(q, 0)
    manchas, disparo = v.processar(_com_pessoa(_quadro("quadro2")), 2)
    assert disparo is not None
    m = disparo.mancha
    assert m.pontos == 84
    assert m.dif < -5
    x, y, w, h = m.caixa
    assert abs(x - 170 / W) < 1e-6 and abs(y - 90 / H) < 1e-6
    assert abs(w - 6 / W) < 1e-6 and abs(h - 14 / H) < 1e-6


def test_precisa_aparecer_em_quadros_seguidos():
    v = T.Vigia(T.Regra(quadros_seguidos=2, movimento_min=0))
    v.processar(_quadro("quadro1"), 0)
    _, d1 = v.processar(_com_pessoa(_quadro("quadro2")), 2)
    _, d2 = v.processar(_com_pessoa(_quadro("quadro2"), x0=172), 4)   # andou 2 pontos
    assert d1 is None
    assert d2 is not None and d2.quadros == 2


def test_pisca_de_um_quadro_nao_dispara():
    v = T.Vigia(T.Regra(quadros_seguidos=2))
    v.processar(_quadro("quadro1"), 0)
    v.processar(_com_pessoa(_quadro("quadro2")), 2)
    _, d = v.processar(_quadro("quadro2"), 4)
    assert d is None


def test_mancha_pequena_e_ignorada():
    v = T.Vigia(T.Regra(quadros_seguidos=1, pontos_min=12))
    v.processar(_quadro("quadro1"), 0)
    _, d = v.processar(_com_pessoa(_quadro("quadro2"), larg=2, alt=3), 2)
    assert d is None


def test_calor_fora_da_faixa_de_corpo_nao_e_pessoa():
    # Inversor esquentando (70 °C) destoa do fundo, mas nao e gente.
    v = T.Vigia(T.Regra(quadros_seguidos=1))
    v.processar(_quadro("quadro1"), 0)
    _, d = v.processar(_com_pessoa(_quadro("quadro2"), temp=70.0), 2)
    assert d is None


def test_area_ignorada_nao_dispara():
    mato = [(0.6, 0.4), (0.75, 0.4), (0.75, 0.6), (0.6, 0.6)]
    v = T.Vigia(T.Regra(quadros_seguidos=1, ignorar=[mato]))
    v.processar(_quadro("quadro1"), 0)
    _, d = v.processar(_com_pessoa(_quadro("quadro2")), 2)
    assert d is None


def test_fora_da_area_vigiada_nao_dispara():
    so_esquerda = [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)]
    v = T.Vigia(T.Regra(quadros_seguidos=1, areas=[so_esquerda]))
    v.processar(_quadro("quadro1"), 0)
    _, d = v.processar(_com_pessoa(_quadro("quadro2")), 2)
    assert d is None


def test_respeita_intervalo_entre_alertas():
    v = T.Vigia(T.Regra(quadros_seguidos=1, intervalo_alertas_s=60, movimento_min=0))
    v.processar(_quadro("quadro1"), 0)
    _, d1 = v.processar(_com_pessoa(_quadro("quadro2")), 2)
    _, d2 = v.processar(_com_pessoa(_quadro("quadro2")), 4)
    _, d3 = v.processar(_com_pessoa(_quadro("quadro2")), 70)
    assert d1 is not None and d2 is None and d3 is not None


def test_pessoa_parada_nao_vira_fundo():
    v = T.Vigia(T.Regra(quadros_seguidos=1, intervalo_alertas_s=0, aprendizado=0.5, movimento_min=0))
    v.processar(_quadro("quadro1"), 0)
    disparos = [v.processar(_com_pessoa(_quadro("quadro2")), 2 * i)[1] for i in range(1, 8)]
    assert all(d is not None for d in disparos)


def test_poligono_em_coordenada_da_tela():
    # Origem no canto superior esquerdo: o quadrado de cima nao pega a linha de baixo.
    m = T.mascara(4, 4, T.Regra(areas=[[(0, 0), (1, 0), (1, 0.5), (0, 0.5)]]))
    assert list(m[:8]) == [1] * 8 and list(m[8:]) == [0] * 8


# Quadros reais dos 2 alarmes falsos de 06/11/2026 (CAM P 03, 07:26 e 07:44):
# chao esfriando, 6 °C abaixo do fundo aprendido e igual ao entorno.
@pytest.mark.parametrize("nome,x0,y0,larg,alt", [("sombra1", 188, 119, 6, 3), ("sombra2", 185, 115, 9, 8)])
def test_chao_esfriando_nao_e_pessoa(nome, x0, y0, larg, alt):
    q = _quadro(nome)
    fundo = T.Fundo(q)
    for y in range(y0 - 1, y0 + alt + 1):
        for x in range(x0 - 1, x0 + larg + 1):
            fundo.valores[y * W + x] = q.t(x, y) + 6
    regra = T.Regra(pontos_min=6)
    assert T.detectar(q, fundo, T.Regra(pontos_min=6, contraste_min=0))    # sem a regra, dispara
    assert T.detectar(q, fundo, regra) == []


@pytest.mark.parametrize("nome", ["quadro1", "quadro2"])
def test_pessoa_ao_sol_passa_pelo_contraste(nome):
    q = _quadro(nome)
    m = T.detectar(_com_pessoa(q), T.Fundo(q), T.Regra())
    assert len(m) == 1 and m[0].contraste >= 3 and m[0].como_dict()["contraste"] == round(m[0].contraste, 1)


def test_simular_pessoa_acha_no_chao_quente_e_some_onde_o_chao_e_igual():
    q = _quadro("quadro1")
    r = T.simular_pessoa(q, T.Fundo(q), T.Regra())
    media = next(t for t in r["tamanhos"] if t["nome"] == "média")
    assert media["posicoes"] > 100 and 50 < media["pct"] < 100 and r["cegos"]
    # Chao inteiro a 34 °C, igual a pessoa: nenhuma posicao deve ser vista.
    igual = T.Quadro(W, H, array("f", [34.0] * (W * H)))
    assert all(t["detectadas"] == 0 for t in T.simular_pessoa(igual, T.Fundo(igual), T.Regra())["tamanhos"])


def test_simular_respeita_a_area_vigiada():
    q = _quadro("quadro1")
    area = [[(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)]]
    r = T.simular_pessoa(q, T.Fundo(q), T.Regra(areas=area))
    t = T.simular_pessoa(q, T.Fundo(q), T.Regra())
    assert 0 < r["tamanhos"][1]["posicoes"] < t["tamanhos"][1]["posicoes"]


def _rodar(vigia, q, quadros):
    disparos = []
    for n, f in enumerate(quadros):
        _, d = vigia.processar(f, 1000.0 + n * 2)
        disparos.append(d)
    return disparos


def test_marca_parada_no_chao_nao_dispara_nem_com_a_borda_tremendo():
    q = _quadro("sombra2")
    v = T.Vigia(T.Regra())
    v.processar(q, 0.0)
    # Mesma marca fria, com a borda oscilando 1 ponto, por 2 minutos de leituras.
    marcas = [_com_pessoa(q, x0=185 + (n % 2), y0=115, larg=12, alt=8, temp=33.0) for n in range(60)]
    assert not any(_rodar(v, q, marcas))


def test_pessoa_andando_dispara():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra())
    v.processar(q, 0.0)
    passos = [_com_pessoa(q, x0=170 + 4 * n) for n in range(5)]
    assert any(_rodar(v, q, passos))


def test_pessoa_longe_e_devagar_dispara():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra())
    v.processar(q, 0.0)
    passos = [_com_pessoa(q, x0=170 + n, larg=3, alt=6) for n in range(7)]
    assert any(_rodar(v, q, passos))


def test_quem_chega_e_para_ja_contou_como_andou():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra(intervalo_alertas_s=0))
    v.processar(q, 0.0)
    assert any(_rodar(v, q, [_com_pessoa(q, x0=170 + 4 * n) for n in range(3)] + [_com_pessoa(q, x0=178)] * 3))


def test_mancha_parada_entra_no_fundo_e_some():
    q = _quadro("sombra2")
    v = T.Vigia(T.Regra())
    v.processar(q, 0.0)
    marca = _com_pessoa(q, x0=185, y0=115, larg=12, alt=8, temp=33.0)
    for n in range(T.ABSORVER_LEITURAS + 90):
        manchas, _ = v.processar(marca, 2.0 * n)
    assert manchas == []


def test_movimento_zero_aceita_parada():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra(movimento_min=0))
    v.processar(q, 0.0)
    assert any(_rodar(v, q, [_com_pessoa(q)] * 3))


PERFIS = [{"de": "18:00", "ate": "06:00", "dif_min": 3, "pontos_min": 6},
          {"de": "06:00", "ate": "10:00", "dif_min": 8, "quadros_seguidos": 3}]


@pytest.mark.parametrize("hora,faixa,dif", [(23 * 60, "18:00-06:00", 3.0), (5 * 60 + 59, "18:00-06:00", 3.0), (6 * 60, "06:00-10:00", 8.0),
                                            (9 * 60 + 59, "06:00-10:00", 8.0), (10 * 60, "", 5.0), (12 * 60, "", 5.0), (18 * 60, "18:00-06:00", 3.0)])
def test_faixa_certa_em_cada_hora(hora, faixa, dif):
    r = T.Regra(perfis=PERFIS).no_minuto(hora)
    assert r.faixa == faixa and r.dif_min == dif and isinstance(r.dif_min, float)
    assert isinstance(r.pontos_min, int) and isinstance(r.quadros_seguidos, int)


def test_faixa_muda_a_deteccao_sem_perder_o_fundo():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra(perfis=[{"de": "06:00", "ate": "10:00", "dif_min": 40.0}], movimento_min=0, quadros_seguidos=1))
    v.processar(q, 0.0, 8 * 60)
    fundo = v.fundo
    assert v.processar(_com_pessoa(q), 2.0, 8 * 60)[1] is None          # manha: exige 40 graus
    _, d = v.processar(_com_pessoa(q), 4.0, 12 * 60)                    # meio-dia: regra normal
    assert d is not None and v.fundo is fundo


def test_quadro_corrompido_nao_entra():
    import json
    info = {"jpegPicWidth": 2, "jpegPicHeight": 1, "temperatureDataLength": 4}
    for lixo in (2.5e38, float("nan"), -48.5 - 1000):
        corpo = _multipart(json.dumps({"JpegPictureWithAppendData": info}).encode(), b"\xff\xd8", array("f", [30.0, lixo]).tobytes())
        with pytest.raises(T.QuadroCorrompido):
            T.ler_quadro(corpo, "multipart/form-data; boundary=boundary")


def test_mancha_que_parou_nao_alarma_de_novo():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra(intervalo_alertas_s=0))
    v.processar(q, 0.0)
    andando = [_com_pessoa(q, x0=170 + 4 * n) for n in range(4)]
    assert any(_rodar(v, q, andando))
    parado = [_com_pessoa(q, x0=182)] * 40
    disparos = [v.processar(f, 100.0 + 2 * n)[1] for n, f in enumerate(parado)]
    assert not any(disparos[8:])      # depois da janela de movimento, para


def test_fundo_acompanha_a_cena_quando_le_devagar():
    q = _quadro("quadro1")
    v = T.Vigia(T.Regra())
    v.processar(q, 0.0)
    frio = T.Quadro(W, H, array("f", [t - 10 for t in q.temps]))
    for n in range(1, 21):                       # 20 min lendo 1 vez por minuto
        v.processar(frio, 60.0 * n)
    assert abs(v.fundo.valores[5000] - frio.temps[5000]) < 0.5
    assert v.processar(frio, 60.0 * 21 + 2)[0] == []
