"""Galeria dos relatorios: toda foto no mesmo quadro 16:9, sem cortar a imagem."""
from PIL import Image

from app.services import recorder_pdf_report as R


def _salvar(tmp_path, nome, tamanho, cor=(200, 30, 30)):
    caminho = tmp_path / nome
    Image.new("RGB", tamanho, cor).save(caminho, "JPEG")
    return caminho


def test_fotos_de_proporcoes_diferentes_saem_no_mesmo_quadro(tmp_path):
    largura_pt = 183
    tamanhos = set()
    for nome, tam in (("16x9.jpg", (1920, 1080)), ("4x3.jpg", (1280, 960)),
                      ("retrato.jpg", (720, 1280)), ("pequena.jpg", (160, 90))):
        buf = R._foto_padronizada(_salvar(tmp_path, nome, tam), largura_pt)
        assert buf is not None
        with Image.open(buf) as im:
            tamanhos.add(im.size)
    assert len(tamanhos) == 1
    w, h = tamanhos.pop()
    assert abs(h / w - R.PROPORCAO_FOTO) < 0.01


def test_foto_4x3_nao_e_cortada_sobra_vira_faixa_preta(tmp_path):
    buf = R._foto_padronizada(_salvar(tmp_path, "4x3.jpg", (1280, 960)), 183)
    with Image.open(buf) as im:
        w, h = im.size
        assert max(im.getpixel((2, h // 2))) < 20          # borda lateral: faixa preta
        assert im.getpixel((w // 2, 2))[0] > 150            # topo: imagem inteira, sem corte
        assert im.getpixel((w // 2, h - 3))[0] > 150        # base: idem


def test_arquivo_que_nao_e_imagem_devolve_none(tmp_path):
    ruim = tmp_path / "x.jpg"
    ruim.write_bytes(b"isto nao e jpeg")
    assert R._foto_padronizada(ruim, 183) is None
