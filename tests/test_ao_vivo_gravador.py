"""Ao vivo de gravador: fonte direta primeiro (sem recodificar), ffmpeg so de reserva.

Medido no iMHDX 7032 da VITAL (27/10/2026): o canal vem em H.265; com so a
fonte ffmpeg todo ao vivo de gravador era recodificado no servidor."""
from __future__ import annotations

from app.services import live_stream_service as L


class Go2rtcFalso(object):
    def __init__(self, streams=None):
        self.streams = streams or {}
        self.chamadas = []

    def get(self, url, timeout=0, **kw):
        return _Resp(200, {n: {"producers": [{"url": u} for u in fs]} for n, fs in self.streams.items()})

    def put(self, url, params=None, timeout=0):
        self.chamadas.append(("PUT", params))
        nome = next(v for k, v in params if k == "name")
        self.streams.setdefault(nome, []).extend(v for k, v in params if k == "src")
        return _Resp(200, {})

    def delete(self, url, params=None, timeout=0):
        self.chamadas.append(("DELETE", params))
        self.streams.pop(params["src"], None)
        return _Resp(200, {})


class _Resp(object):
    def __init__(self, status, corpo):
        self.status_code, self._corpo, self.text = status, corpo, ""

    def json(self):
        return self._corpo


def _registrar(monkeypatch, falso):
    monkeypatch.setattr(L, "requests", falso)
    monkeypatch.setattr(L, "marcar_dono", lambda nome: None)
    return L.register_recorder_stream(host="10.211.198.227", user="admin", password="s3nh@", canal=1, alta=False)


def test_direto_primeiro_e_ffmpeg_de_reserva(monkeypatch):
    falso = Go2rtcFalso()
    nome = _registrar(monkeypatch, falso)
    fontes = falso.streams[nome]
    assert fontes[0].startswith("rtsp://admin:s3nh%40@10.211.198.227:554/") and "subtype=1" in fontes[0]
    assert fontes[1] == "ffmpeg:%s#video=h264" % nome


def test_registro_antigo_so_ffmpeg_e_trocado_sem_acumular(monkeypatch):
    nome = L.recorder_stream_name("10.211.198.227", 1, False)
    falso = Go2rtcFalso({nome: ["ffmpeg:rtsp://admin:x@10.211.198.227:554/cam/realmonitor?channel=1&subtype=1#video=h264"]})
    _registrar(monkeypatch, falso)
    assert [c[0] for c in falso.chamadas] == ["DELETE", "PUT"]
    assert len(falso.streams[nome]) == 2 and falso.streams[nome][0].startswith("rtsp://")


def test_ja_certo_nao_derruba_quem_assiste(monkeypatch):
    falso = Go2rtcFalso()
    _registrar(monkeypatch, falso)
    falso.chamadas.clear()
    _registrar(monkeypatch, falso)
    assert falso.chamadas == []
