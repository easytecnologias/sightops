"""Testa o servico de streams do go2rtc: registro idempotente, desregistro e
a varredura que remove streams sem espectador. Usa um FakeResponse para
simular o go2rtc sem rede.

Confirmado testando o go2rtc real em producao (versao 1.9.14), lendo o
codigo fonte dele quando precisou:
- GET /api/streams ignora qualquer parametro -- sempre devolve a lista
  inteira. O FakeResponse abaixo reproduz isso de proposito, para o teste
  continuar valendo se alguem tentar "otimizar" o registro para filtrar do
  lado do servidor.
- DELETE /api/streams identifica o stream a remover pelo parametro `src`,
  NAO `name` (apesar do PUT usar `name` para a mesma coisa -- API
  inconsistente do proprio go2rtc). Mandar `name=` no DELETE nao da erro,
  so nao remove nada -- foi um bug real desta branch, so descoberto
  testando contra producao depois do deploy inicial. O fake_delete abaixo
  so aceita `src=`, de proposito, para pegar uma regressao se alguem
  voltar a usar `name=`.

Roda direto: python scripts/sightops_live_stream_service_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import requests
    from app.services import live_stream_service as svc

    chamadas: list[dict[str, Any]] = []
    estado_streams: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self, status_code: int, body: Any):
            self.status_code = status_code
            self._body = body
            self.text = body if isinstance(body, str) else ""

        def json(self) -> Any:
            return self._body

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        chamadas.append({"metodo": "GET", "url": url, **kwargs})
        # go2rtc real ignora ?name= no GET -- sempre devolve tudo.
        return FakeResponse(200, dict(estado_streams))

    def fake_put(url: str, **kwargs: Any) -> FakeResponse:
        chamadas.append({"metodo": "PUT", "url": url, **kwargs})
        params = kwargs.get("params") or {}
        estado_streams[params["name"]] = {"producers": [{"url": params["src"]}], "consumers": None}
        return FakeResponse(200, {})

    def fake_delete(url: str, **kwargs: Any) -> FakeResponse:
        chamadas.append({"metodo": "DELETE", "url": url, **kwargs})
        params = kwargs.get("params") or {}
        # go2rtc real so remove pelo parametro `src` -- de proposito NAO
        # olha `name` aqui, pra pegar regressao se o codigo voltar a mandar
        # o parametro errado.
        estado_streams.pop(params.get("src"), None)
        return FakeResponse(200, {})

    original_get, original_put, original_delete = requests.get, requests.put, requests.delete
    requests.get = fake_get
    requests.put = fake_put
    requests.delete = fake_delete
    try:
        # --- registrar pela primeira vez: GET (checa) + PUT (cria) ---
        chamadas.clear()
        name = svc.register_stream(
            ip="10.10.9.85", user="admin", password="segredo123",
            subtype=1, vendor="Intelbras", model="VIP-1230",
        )
        assert name == "cam_10_10_9_85_1", name
        assert [c["metodo"] for c in chamadas] == ["GET", "PUT"], chamadas
        assert "10.10.9.85:554/cam/realmonitor?channel=1&subtype=1" in estado_streams[name]["producers"][0]["url"]

        # --- registrar de novo, MESMA camera/qualidade/credencial: idempotente, SEM PUT ---
        chamadas.clear()
        svc.register_stream(
            ip="10.10.9.85", user="admin", password="segredo123",
            subtype=1, vendor="Intelbras", model="VIP-1230",
        )
        assert [c["metodo"] for c in chamadas] == ["GET"], (
            f"registro repetido com os mesmos dados nao deveria fazer PUT de novo: {chamadas}"
        )

        # --- mesma camera, credencial DIFERENTE: fonte mudou, registra de novo ---
        chamadas.clear()
        svc.register_stream(
            ip="10.10.9.85", user="admin", password="outra-senha",
            subtype=1, vendor="Intelbras", model="VIP-1230",
        )
        assert [c["metodo"] for c in chamadas] == ["GET", "PUT"], (
            f"credencial mudou, deveria ter re-registrado: {chamadas}"
        )

        # --- go2rtc 1.9.14 as vezes cria o stream mas devolve HTTP 400
        # (bug real confirmado em producao: erro de YAML interno num
        # round-trip que roda DEPOIS de ja ter salvo) -- register_stream
        # tem que confirmar pelo estado real antes de desistir ---
        estado_streams.clear()
        chamadas.clear()

        def fake_put_go2rtc_bug(url: str, **kwargs: Any) -> FakeResponse:
            chamadas.append({"metodo": "PUT", "url": url, **kwargs})
            params = kwargs.get("params") or {}
            # cria o stream de verdade (como o go2rtc realmente faz)...
            estado_streams[params["name"]] = {"producers": [{"url": params["src"]}], "consumers": None}
            # ...mas devolve erro, como o bug real observado
            return FakeResponse(400, "")

        requests.put = fake_put_go2rtc_bug
        name_bug = svc.register_stream(
            ip="10.10.9.99", user="admin", password="segredo999",
            subtype=1, vendor="Intelbras", model="VIP-1230",
        )
        assert name_bug == "cam_10_10_9_99_1", "deveria ter tratado como sucesso mesmo com HTTP 400"
        assert name_bug in estado_streams, "o stream deveria ter sido criado de verdade"
        requests.put = fake_put

        # --- PUT que falha DE VERDADE (nao cria nada) continua levantando erro ---
        chamadas.clear()

        def fake_put_falha_de_verdade(url: str, **kwargs: Any) -> FakeResponse:
            chamadas.append({"metodo": "PUT", "url": url, **kwargs})
            return FakeResponse(500, "erro interno de verdade")

        requests.put = fake_put_falha_de_verdade
        erro_levantado = False
        try:
            svc.register_stream(
                ip="10.10.9.98", user="admin", password="x",
                subtype=1, vendor="Intelbras", model="VIP-1230",
            )
        except RuntimeError:
            erro_levantado = True
        assert erro_levantado, "PUT que falha de verdade (sem criar o stream) tem que levantar erro"
        assert "cam_10_10_9_98_1" not in estado_streams
        requests.put = fake_put

        # --- HD (subtype=0) e SD (subtype=1) da mesma camera sao streams DIFERENTES ---
        name_hd = svc.register_stream(
            ip="10.10.9.85", user="admin", password="outra-senha",
            subtype=0, vendor="Intelbras", model="VIP-1230",
        )
        assert name_hd == "cam_10_10_9_85_0", name_hd
        assert name_hd != name, "HD e SD tem que ser streams separados no go2rtc"

        # --- fabricante Hikvision usa caminho RTSP diferente (Streaming/Channels) ---
        name_hik = svc.register_stream(
            ip="10.10.9.90", user="admin", password="x",
            subtype=1, vendor="Hikvision", model="DS-2CD1021G0-I",
        )
        assert "/Streaming/Channels/102" in estado_streams[name_hik]["producers"][0]["url"], estado_streams[name_hik]

        # --- desregistrar: DELETE com o nome certo, idempotente (nao existir nao e erro) ---
        chamadas.clear()
        svc.unregister_stream(ip="10.10.9.85", subtype=1)
        assert len(chamadas) == 1 and chamadas[0]["metodo"] == "DELETE", chamadas
        assert chamadas[0]["params"] == {"src": "cam_10_10_9_85_1"}, (
            f"DELETE do go2rtc usa o parametro 'src', nao 'name': {chamadas}"
        )
        assert "cam_10_10_9_85_1" not in estado_streams
        svc.unregister_stream(ip="10.10.9.85", subtype=1)  # de novo, nao pode quebrar

        # --- varredura remove so quem nao tem espectador (consumers vazio/None) ---
        estado_streams.clear()
        estado_streams["cam_1_2_3_4_1"] = {"producers": [{"url": "x"}], "consumers": None}
        estado_streams["cam_5_6_7_8_1"] = {"producers": [{"url": "y"}], "consumers": []}
        estado_streams["cam_9_9_9_9_1"] = {"producers": [{"url": "z"}], "consumers": [{"user_agent": "chrome"}]}
        estado_streams["outra_coisa_nao_camera"] = {"producers": [{"url": "w"}], "consumers": None}
        removidos = svc.reap_idle_streams()
        assert set(removidos) == {"cam_1_2_3_4_1", "cam_5_6_7_8_1"}, removidos
        assert "cam_9_9_9_9_1" in estado_streams, "stream com espectador nao pode ser removido"
        assert "outra_coisa_nao_camera" in estado_streams, "so mexe em streams cam_*, nao em outras entradas do go2rtc"

        # --- caminho RTSP por fabricante (migrado de maintenance.py, mesmo comportamento) ---
        assert svc._stream_rtsp_path_for_camera(vendor="Hikvision", model="DS-2CD1021G0-I", subtype=1) == "/Streaming/Channels/102"
        assert svc._stream_rtsp_path_for_camera(vendor="Intelbras", model="VIPC-1230-B-G2", subtype=1) == "/cam/realmonitor?channel=1&subtype=1"
        assert svc._stream_rtsp_path_for_camera(vendor="", model="IPC-B121H-L", subtype=0) == "/Streaming/Channels/101"
    finally:
        requests.get, requests.put, requests.delete = original_get, original_put, original_delete

    print("live_stream_service: registro idempotente, HD/SD separados, desregistro e varredura de ociosos ok")


if __name__ == "__main__":
    main()
