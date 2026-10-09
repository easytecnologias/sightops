"""Classifica os trechos com movimento da Investigacao: pessoa, veiculo ou so movimento.

O gravador so diz "houve movimento"; em camera de rua isso e quase tudo (carro,
farol, chuva). Aqui um detector de objetos olha quadros do trecho e diz o que
havia nele.

Modelo: YOLOX (Megvii, licenca Apache 2.0 -- uso comercial livre). O YOLO11 da
Ultralytics, usado nos testes de agosto, e AGPL: num SaaS obrigaria a abrir o
codigo ou comprar licenca. O ONNX roda pelo OpenCV DNN que ja esta na imagem.
O arquivo do modelo NAO vai no git nem na imagem: fica no volume de dados
(DATA_DIR/modelos), que sobrevive a recreate; deploy/modelos/baixar-yolox.sh
baixa e confere o sha256.

Servidor (Xeon E-2224, sem GPU): o gargalo nao e a rede neural, e tirar o
quadro do gravador (cada RTSP de playback leva 1,5-2 s e o gravador aceita
poucas sessoes). Por isso: 1 quadro por trecho curto, 2 nos longos.

Filtro de objeto fixo: macacao pendurado, extintor e boneco viram "pessoa"
sempre no MESMO lugar (aprendido em 08/2026 na oficina de Perucaba). Caixa que
se repete no mesmo ponto em muitos trechos espalhados no tempo e cenario.
"""
from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from app.core.paths import DATA_DIR

MODELO_DIR = Path(os.getenv("SIGHTOPS_MODELOS_DIR") or (DATA_DIR / "modelos"))
# yolox_m: medido no servidor em 09/10/2026 -- 609 ms/quadro (s: 224 ms). O "s"
# perdia o homem no centro da academia da SIERRA (nota 0,33); o "m" acha (0,38)
# e tambem quem esta na esteira (0,44). Tirar o quadro do gravador ja leva ~2 s,
# entao a diferenca de tempo quase nao aparece.
MODELO_PADRAO = os.getenv("SIGHTOPS_DETECTOR", "yolox_m")
# Lado da entrada de cada modelo (como foram exportados pela Megvii).
_ENTRADA = {"yolox_nano": 416, "yolox_tiny": 416, "yolox_s": 640, "yolox_m": 640, "yolox_l": 640}

PESSOA = {0}
VEICULO = {1, 2, 3, 5, 7}  # bicicleta, carro, moto, onibus, caminhao (COCO)
NOME_CLASSE = {0: "pessoa", 1: "bicicleta", 2: "carro", 3: "moto", 5: "onibus", 7: "caminhao"}
# Pessoa e o que se procura: corte mais baixo. Veiculo erra mais (aparelho de
# academia vira "bicicleta"), corte mais alto.
CONF_PESSOA = float(os.getenv("SIGHTOPS_DETECTOR_CONF_PESSOA", "0.30"))
CONF_VEICULO = float(os.getenv("SIGHTOPS_DETECTOR_CONF_VEICULO", "0.40"))
CONF_MIN = min(CONF_PESSOA, CONF_VEICULO)
NMS_IOU = 0.45


@dataclass
class Deteccao:
    classe: str
    conf: float
    # caixa normalizada (0..1) para desenhar sobre a foto em qualquer tamanho
    x1: float
    y1: float
    x2: float
    y2: float
    fixo: bool = False

    @property
    def tipo(self) -> str:
        return "pessoa" if self.classe == "pessoa" else "veiculo"


class Detector:
    def __init__(self, nome: str = MODELO_PADRAO, pasta: Path = MODELO_DIR):
        import cv2

        arq = Path(pasta) / f"{nome}.onnx"
        if not arq.exists():
            raise FileNotFoundError(f"modelo {arq} nao encontrado -- rode deploy/modelos/baixar-yolox.sh")
        self.nome = nome
        self.lado = _ENTRADA.get(nome, 640)
        self._cv2 = cv2
        self._net = cv2.dnn.readNetFromONNX(str(arq))
        self._lock = threading.Lock()  # cv2.dnn.Net nao e thread-safe
        self._grade, self._passos = self._grades(self.lado)

    @staticmethod
    def _grades(lado: int):
        grades, passos = [], []
        for s in (8, 16, 32):
            n = lado // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            g = np.stack((xv, yv), 2).reshape(-1, 2)
            grades.append(g)
            passos.append(np.full((g.shape[0], 1), s))
        return np.concatenate(grades, 0).astype(np.float32), np.concatenate(passos, 0).astype(np.float32)

    def _preparar(self, img: np.ndarray):
        """Letterbox igual ao demo oficial do YOLOX: BGR, fundo 114, sem normalizar.

        Conferido em 09/10/2026: o modo antigo (RGB normalizado pelo ImageNet)
        zera as deteccoes destes ONNX -- eles esperam a imagem crua.
        """
        h, w = img.shape[:2]
        r = min(self.lado / h, self.lado / w)
        nw, nh = int(w * r), int(h * r)
        tela = np.full((self.lado, self.lado, 3), 114, dtype=np.uint8)
        tela[:nh, :nw] = self._cv2.resize(img, (nw, nh), interpolation=self._cv2.INTER_LINEAR)
        return np.ascontiguousarray(tela.transpose(2, 0, 1)[None], dtype=np.float32), r

    def detectar(self, img: np.ndarray) -> List[Deteccao]:
        if img is None or img.size == 0:
            return []
        blob, r = self._preparar(img)
        with self._lock:
            self._net.setInput(blob)
            saida = self._net.forward()
        return decodificar(saida, r, img.shape[1], img.shape[0], self._grade, self._passos)


def decodificar(saida: np.ndarray, r: float, w: int, h: int, grade: np.ndarray, passos: np.ndarray,
                conf_min: float = CONF_MIN) -> List[Deteccao]:
    """Saida crua do YOLOX (1, N, 85) -> deteccoes de pessoa/veiculo com NMS por classe."""
    import cv2

    p = saida.reshape(-1, saida.shape[-1]).astype(np.float32)
    xy = (p[:, :2] + grade) * passos
    wh = np.exp(np.clip(p[:, 2:4], -10, 10)) * passos
    pontos = p[:, 4:5] * p[:, 5:]
    classe = pontos.argmax(1)
    conf = pontos[np.arange(len(classe)), classe]
    corte = np.where(np.isin(classe, list(PESSOA)), max(conf_min, CONF_PESSOA), max(conf_min, CONF_VEICULO))
    manter = (conf >= corte) & np.isin(classe, list(PESSOA | VEICULO))
    if not manter.any():
        return []
    xy, wh, classe, conf = xy[manter], wh[manter], classe[manter], conf[manter]
    caixas = np.concatenate([xy - wh / 2, wh], 1) / r  # x, y, w, h na imagem original
    escolhidos = cv2.dnn.NMSBoxesBatched(caixas.tolist(), conf.tolist(), classe.tolist(), conf_min, NMS_IOU)
    saida_det = []
    for i in np.array(escolhidos).reshape(-1):
        # float() puro: numpy.float32 quebra o json.dumps do cache (visto na prova real).
        x, y, bw, bh = (float(v) for v in caixas[i])
        saida_det.append(Deteccao(NOME_CLASSE.get(int(classe[i]), "veiculo"), round(float(conf[i]), 3),
                                  round(max(0.0, x / w), 4), round(max(0.0, y / h), 4),
                                  round(min(1.0, (x + bw) / w), 4), round(min(1.0, (y + bh) / h), 4)))
    return sorted(saida_det, key=lambda d: -d.conf)


def _iou(a: Deteccao, b: Deteccao) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    uniao = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter
    return inter / uniao if uniao > 0 else 0.0


def marcar_fixos(por_trecho: Dict[str, List[Deteccao]], instantes: Dict[str, float],
                 iou_min: float = 0.6, repeticoes: int = 5, espalhado_s: float = 600) -> int:
    """Marca como `fixo` a caixa que aparece no mesmo lugar em muitos trechos.

    por_trecho: chave do trecho -> deteccoes; instantes: chave -> epoch do quadro.
    Pessoa de verdade anda; objeto pendurado fica. Devolve quantas foram marcadas.
    """
    todas = [(k, d) for k, ds in por_trecho.items() for d in ds if d.classe == "pessoa"]
    marcadas = 0
    for k, d in todas:
        if d.fixo:
            continue
        iguais = [(k2, d2) for k2, d2 in todas if _iou(d, d2) >= iou_min]
        trechos = {k2 for k2, _ in iguais}
        tempos = [instantes.get(k2, 0) for k2 in trechos]
        if len(trechos) >= repeticoes and tempos and max(tempos) - min(tempos) >= espalhado_s:
            for _, d2 in iguais:
                if not d2.fixo:
                    d2.fixo = True
                    marcadas += 1
    return marcadas


def rotulo(dets: Sequence[Deteccao]) -> str:
    """Rotulo do trecho: pessoa vence veiculo; sem nada (ou so fixo) e 'movimento'."""
    validas = [d for d in dets if not d.fixo]
    if any(d.classe == "pessoa" for d in validas):
        return "pessoa"
    if validas:
        return "veiculo"
    return "movimento"


def como_dict(dets: Sequence[Deteccao]) -> List[dict]:
    return [asdict(d) for d in dets]


_detector: Optional[Detector] = None
_detector_lock = threading.Lock()


def detector() -> Detector:
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = Detector()
        return _detector
