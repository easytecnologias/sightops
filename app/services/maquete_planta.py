"""Maquete 3D -- leitura da planta (PDF vetorial exportado do CAD).

Do PDF sai, para cada desenho de planta baixa achado na prancha:
- paredes: retangulos em metros (x0, y0, x1, y1), com origem no canto do desenho;
- vaos: buracos curtos na parede (porta) e os perto de um rotulo J1..J9 (janela);
- rotulos: "APTO 01", "LOJA 2"... para mostrar na maquete;
- textura: o proprio desenho (sem as cotas vermelhas) para forrar o piso.

Como acha a parede: CAD exporta parede como contorno grosso + hachura de linhas
finas cinza. Com hachura, a parede e onde a hachura e densa (fecha e abre a
mascara). Sem hachura, usa o traco preto mais grosso que se repete (contorno) e
fecha o espaco entre as duas linhas do contorno.

PDF escaneado (so imagem, sem vetor) nao tem o que ler aqui: erro explicando.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

try:  # PyMuPDF
    import fitz  # type: ignore
except Exception:  # pragma: no cover - so falta se a imagem nao tiver o pacote
    fitz = None

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

PX = 2.0          # pixels por ponto PDF na mascara
CELULA_M = 0.05   # celula da grade de paredes (5 cm)
MAX_TEXTURA = 4096
ROTULO_RE = re.compile(r"^(APTO|AP|LOJA|SALA|BLOCO|CASA|UNID)$", re.I)
JANELA_RE = re.compile(r"^J\d{1,2}$")
ESCALA_RE = re.compile(r"\b1\s*[/:]\s*(\d{2,3})\b")


class PlantaInvalida(ValueError):
    pass


def _exigir_libs() -> None:
    if fitz is None or cv2 is None:
        raise PlantaInvalida("Leitura de planta indisponível neste servidor (falta PyMuPDF/OpenCV).")


def _segmentos(desenhos: List[Dict[str, Any]], M: Any, filtro) -> List[Tuple[Any, Any]]:
    out = []
    for dr in desenhos:
        if not filtro(dr):
            continue
        for it in dr["items"]:
            op = it[0]
            if op == "l":
                out.append((it[1] * M, it[2] * M))
            elif op in ("re", "qu"):
                q = (fitz.Quad(it[1]) if op == "re" else it[1]).transform(M)
                out += [(q.ul, q.ur), (q.ur, q.lr), (q.lr, q.ll), (q.ll, q.ul)]
            elif op == "c":
                out.append((it[1] * M, it[4] * M))
    return out


def _cor(dr: Dict[str, Any]) -> Tuple[float, float, float]:
    c = dr.get("color") or (0, 0, 0)
    return (float(c[0]), float(c[1]), float(c[2])) if len(c) >= 3 else (float(c[0]),) * 3


def _largura(dr: Dict[str, Any]) -> float:
    return round(float(dr.get("width") or 0), 2)


def _raster(segs, W: int, H: int, esp: int = 1) -> np.ndarray:
    m = np.zeros((H, W), np.uint8)
    for a, b in segs:
        cv2.line(m, (int(a.x * PX), int(a.y * PX)), (int(b.x * PX), int(b.y * PX)), 255, esp)
    return m


def _k(n: float) -> np.ndarray:
    n = max(1, int(round(n)))
    return cv2.getStructuringElement(cv2.MORPH_RECT, (n, n))


def _mascara_paredes(desenhos: List[Dict[str, Any]], M: Any, W: int, H: int, pt_por_m: float) -> Tuple[np.ndarray, str]:
    if len(desenhos) < 50:
        raise PlantaInvalida("Este PDF não tem desenho vetorial (parece escaneado ou foto). "
                             "Envie o PDF exportado do CAD.")

    def eh_hachura(dr):
        r, g, b = _cor(dr)
        return _largura(dr) <= 0.2 and abs(r - g) < 0.05 and abs(g - b) < 0.05 and 0.3 <= r <= 0.75

    def eh_preto(dr):
        return max(_cor(dr)) < 0.2

    hachura = [dr for dr in desenhos if eh_hachura(dr)]
    larguras = Counter(_largura(dr) for dr in desenhos if eh_preto(dr) and _largura(dr) >= 0.7)
    grossa = max(larguras, key=lambda w: (larguras[w] >= 80, w)) if larguras else None
    contorno = _raster(_segmentos(desenhos, M, lambda dr: grossa is not None and eh_preto(dr) and _largura(dr) == grossa), W, H)
    esp_parede_px = 0.15 * pt_por_m * PX  # parede tipica de 15 cm

    if len(hachura) >= 200:
        h = _raster(_segmentos(hachura, M, lambda dr: True), W, H)
        wall = cv2.morphologyEx(h, cv2.MORPH_CLOSE, _k(esp_parede_px * 0.35))
        wall = cv2.morphologyEx(wall, cv2.MORPH_OPEN, _k(esp_parede_px * 0.5))
        wall = cv2.bitwise_or(wall, cv2.bitwise_and(cv2.dilate(wall, _k(3)), contorno))
        modo = "hachura"
    elif grossa is not None:
        wall = cv2.morphologyEx(contorno, cv2.MORPH_CLOSE, _k(esp_parede_px * 1.3))
        wall = cv2.morphologyEx(wall, cv2.MORPH_OPEN, _k(esp_parede_px * 0.45))
        modo = "contorno"
    else:
        raise PlantaInvalida("Não achei paredes neste PDF (sem hachura nem contorno grosso).")
    return wall, modo


def _escala(p: Any) -> int:
    achados = Counter(int(m.group(1)) for m in ESCALA_RE.finditer(p.get_text() or ""))
    for den, _ in achados.most_common():
        if 20 <= den <= 200:
            return den
    return 50


def _linhas_texto(p: Any, M: Any) -> List[Dict[str, Any]]:
    """Palavras ja na orientacao da folha (pagina girada vira coordenada visivel)."""
    out = []
    for x0, y0, x1, y1, t, blk, ln, wn in p.get_text("words"):
        q = fitz.Rect(x0, y0, x1, y1) * M
        out.append({"t": t, "r": q, "k": (blk, ln), "n": wn})
    return out


def _titulos(palavras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Titulos 'PLANTA BAIXA | TERREO' -> nome curto + posicao."""
    out = []
    por_linha: Dict[Any, List[Dict[str, Any]]] = {}
    for w in palavras:
        por_linha.setdefault(w["k"], []).append(w)
    for ws in por_linha.values():
        ws.sort(key=lambda w: w["n"])
        for i, w in enumerate(ws):
            if w["t"].upper() != "PLANTA":
                continue
            partes, r = [], fitz.Rect(w["r"])
            for w2 in ws[i + 1:i + 12]:
                tt = w2["t"]
                if tt.upper() == "PLANTA" or tt.lower().startswith("esc"):
                    break
                partes.append(tt)
                r |= w2["r"]
            nome = " ".join(partes)
            nome = re.sub(r"(?i)^baixa\s*", "", nome)
            nome = re.sub(r"(?i)[_\s]*(cotas|layout|humanizada)\b.*$", "", nome)
            nome = nome.replace("|", " ").replace("_", " ").strip(" -.")
            nome = re.sub(r"\s+", " ", nome)
            if nome and not re.search(r"(?i)cobert", nome):
                out.append({"nome": nome.title(), "r": r})
    return out


def _caixas(mask: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """mascara -> retangulos (x0, y0, x1, y1) em celulas, juntando faixas iguais."""
    H, W = mask.shape
    runs: Dict[Tuple[int, int], int] = {}
    out = []
    for y in range(H):
        row = mask[y] > 0
        cur = {}
        x = 0
        while x < W:
            if row[x]:
                x0 = x
                while x < W and row[x]:
                    x += 1
                cur[(x0, x)] = runs.pop((x0, x), y)
            else:
                x += 1
        for (x0, x1), y0 in runs.items():
            out.append((x0, y0, x1, y))
        runs = cur
    for (x0, x1), y0 in runs.items():
        out.append((x0, y0, x1, H))
    return out


def _curtos(m: np.ndarray, eixo: int, lim: int) -> np.ndarray:
    a = (m > 0) if eixo == 0 else (m > 0).T
    o = np.zeros_like(a)
    for j in range(a.shape[1]):
        col = a[:, j]
        i = 0
        n = len(col)
        while i < n:
            if col[i]:
                k = i
                while k < n and col[k]:
                    k += 1
                if k - i <= lim:
                    o[i:k, j] = True
                i = k
            else:
                i += 1
    o = o if eixo == 0 else o.T
    return o.astype(np.uint8) * 255


def _vaos(g: np.ndarray) -> np.ndarray:
    v = np.zeros_like(g)
    for ker, eixo in ((np.ones((1, 36), np.uint8), 0), (np.ones((36, 1), np.uint8), 1)):
        c = cv2.morphologyEx(g, cv2.MORPH_CLOSE, ker)
        v |= _curtos(cv2.subtract(c, g), eixo, 7)
    n, lab, st, _ = cv2.connectedComponentsWithStats(v)
    out = np.zeros_like(v)
    for i in range(1, n):
        _, _, ww, hh, a = st[i]
        if min(ww, hh) <= 7 and max(ww, hh) >= 10 and a >= 0.6 * ww * hh:
            out[lab == i] = 255
    return out


def ler_planta(pdf: bytes, pasta_saida: Path) -> Dict[str, Any]:
    """Le o PDF e grava as texturas em pasta_saida. Devolve os pavimentos achados."""
    _exigir_libs()
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        raise PlantaInvalida("Arquivo não é um PDF válido.")
    if doc.page_count < 1:
        raise PlantaInvalida("PDF vazio.")
    pasta_saida.mkdir(parents=True, exist_ok=True)
    pisos: List[Dict[str, Any]] = []
    escala_final = 50
    modos = set()
    for pno in range(min(doc.page_count, 6)):
        p = doc[pno]
        M = p.rotation_matrix
        rect = p.rect
        W, H = int(rect.width * PX) + 1, int(rect.height * PX) + 1
        den = _escala(p)
        escala_final = den
        pt_por_m = 72 / 0.0254 / den
        m_por_pt = 1 / pt_por_m
        try:
            wall, modo = _mascara_paredes(p.get_drawings(), M, W, H, pt_por_m)
        except PlantaInvalida:
            if pno == 0 and doc.page_count == 1:
                raise
            continue
        modos.add(modo)
        # tira pedacos pequenos (texto, simbolo)
        n, lab, st, _ = cv2.connectedComponentsWithStats(wall)
        limpa = np.zeros_like(wall)
        area_min = (0.15 * pt_por_m * PX) ** 2 * 4
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] > area_min:
                limpa[lab == i] = 255
        wall = limpa
        # cada desenho da prancha: paredes proximas (ate 1,5 m) formam um grupo
        grupos = cv2.dilate(wall, _k(1.5 * pt_por_m * PX))
        n, lab, st, _ = cv2.connectedComponentsWithStats(grupos)
        palavras = _linhas_texto(p, M)
        titulos = _titulos(palavras)
        regioes = []
        for i in range(1, n):
            x, y, ww, hh, _ = st[i]
            if ww / PX * m_por_pt < 3 or hh / PX * m_por_pt < 3:
                continue
            sub = wall[y:y + hh, x:x + ww] * (lab[y:y + hh, x:x + ww] == i)
            if int((sub > 0).sum()) < area_min * 6:
                continue
            ys, xs = np.nonzero(sub)
            regioes.append((x + xs.min(), y + ys.min(), x + xs.max(), y + ys.max(), sub[ys.min():ys.max() + 1, xs.min():xs.max() + 1]))
        regioes.sort(key=lambda r: (r[0], r[1]))
        for (x0, y0, x1, y1, sub) in regioes:
            cell = CELULA_M * pt_por_m * PX
            gw, gh = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
            g = (cv2.resize(sub, (gw, gh), interpolation=cv2.INTER_AREA) > 110).astype(np.uint8) * 255
            vk = _vaos(g)
            org = (x0 / PX, y0 / PX)  # pt da folha
            largura, prof = round(float(gw * CELULA_M), 2), round(float(gh * CELULA_M), 2)
            m = lambda b: [round(float(b[k]) * CELULA_M, 3) for k in range(4)]
            area = fitz.Rect(org[0], org[1], org[0] + largura * pt_por_m, org[1] + prof * pt_por_m)
            dentro = [w for w in palavras if area.contains(w["r"])]
            janelas = [((w["r"].x0 + w["r"].x1) / 2 - org[0], (w["r"].y0 + w["r"].y1) / 2 - org[1], w["t"])
                       for w in dentro if JANELA_RE.match(w["t"])]
            vaos = []
            for b in _caixas(vk):
                cx = (b[0] + b[2]) / 2 * CELULA_M * pt_por_m
                cy = (b[1] + b[3]) / 2 * CELULA_M * pt_por_m
                tipo = "porta"
                for jx, jy, jt in janelas:
                    if abs(jx - cx) < 0.8 * pt_por_m and abs(jy - cy) < 0.8 * pt_por_m:
                        tipo = jt.upper()
                vaos.append(m(b) + [tipo])
            rotulos = []
            ordenadas = sorted(dentro, key=lambda w: (w["k"], w["n"]))
            for j, w in enumerate(ordenadas):
                if ROTULO_RE.match(w["t"]) and j + 1 < len(ordenadas):
                    w2 = ordenadas[j + 1]
                    if re.fullmatch(r"\d{1,4}[A-Z]?", w2["t"]) and w2["k"] == w["k"]:
                        cx = ((w["r"].x0 + w2["r"].x1) / 2 - org[0]) * m_por_pt
                        cy = ((w["r"].y0 + w["r"].y1) / 2 - org[1]) * m_por_pt
                        rotulos.append([round(float(cx), 2), round(float(cy), 2), f"{w['t'].upper()} {w2['t']}"])
            # nome: titulo logo abaixo do desenho, na mesma faixa horizontal
            nome = ""
            melhor = None
            for t in titulos:  # titulo logo abaixo, comecando na faixa do desenho
                r = t["r"]
                if area.x0 - area.width * 0.5 <= r.x0 <= area.x1 and area.y1 - 20 <= r.y0 <= area.y1 + 400:
                    d = (r.y0 - area.y1) + abs(r.x0 - area.x0) * 0.3
                    if melhor is None or d < melhor:
                        melhor, nome = d, t["nome"]
            idx = len(pisos)
            # textura: o desenho, sem as cotas em vermelho
            zoom = min(MAX_TEXTURA / max(area.width, area.height), 300 / 72)
            # clip e na folha ja girada (page.rect), o mesmo sistema das palavras
            pm = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=area, alpha=False)
            img = np.frombuffer(pm.samples, np.uint8).reshape(pm.h, pm.w, pm.n)[:, :, :3].copy()
            R_, G_, B_ = (img[:, :, k].astype(int) for k in range(3))
            img[(R_ - G_ > 60) & (R_ - B_ > 60)] = 255
            arq = f"piso_{idx}.jpg"
            cv2.imwrite(str(pasta_saida / arq), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 72])
            pisos.append({
                "id": f"p{idx}", "nome": nome or f"Pavimento {idx + 1}", "pagina": pno + 1,
                "largura": largura, "profundidade": prof,
                "paredes": [m(b) for b in _caixas(g)], "vaos": vaos, "rotulos": rotulos,
                "textura": arq,
            })
    if not pisos:
        raise PlantaInvalida("Não achei nenhuma planta baixa neste PDF.")
    # terreo/subsolo primeiro; o resto na ordem da folha
    def peso(pv):
        n = pv["nome"].lower()
        return 0 if "subsolo" in n else 1 if ("térreo" in n or "terreo" in n) else 2
    pisos.sort(key=peso)
    return {"escala": f"1/{escala_final}", "modo": "+".join(sorted(modos)), "pisos": pisos}

