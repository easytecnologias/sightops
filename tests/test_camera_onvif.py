"""Usuario ONVIF de camera Hikvision (app/services/camera_onvif.py), contra uma
camera simulada com o XML lido de verdade numa IPC-B121H-L (172.16.45.101,
INTERBLOCOS, 26/10/2026). Nada sai para a rede."""
import re

import pytest

from app.services import camera_onvif as O

NS = "http://www.hikvision.com/ver20/XMLSchema"


class CameraFalsa:
    def __init__(self):
        self.onvif = False
        self.cgi = False
        self.usuarios = {}           # id -> (nome, perfil)
        self.escritas = []

    def integrate(self):
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Integrate version="2.0" xmlns="{NS}">\n'
                f'<CGI>\n<enable>{str(self.cgi).lower()}</enable>\n<certificateType>digest</certificateType>\n</CGI>\n'
                f'<ONVIF>\n<enable>{str(self.onvif).lower()}</enable>\n</ONVIF>\n<ISAPI>\n<enable>true</enable>\n</ISAPI>\n</Integrate>\n')

    def lista(self):
        corpo = "".join(f"<User><id>{i}</id><userName>{n}</userName><userType>{p}</userType></User>"
                        for i, (n, p) in sorted(self.usuarios.items()))
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<UserList version="2.0" xmlns="{NS}">\n{corpo}</UserList>\n'

    def ok(self):
        return 200, "<ResponseStatus><statusCode>1</statusCode></ResponseStatus>"

    def get(self, url, user, senha, timeout=None):
        if senha != "certa":
            return 401, ""
        if url.endswith("/Integrate"):
            return 200, self.integrate()
        if url.endswith("/ONVIF/users"):
            return 200, self.lista()
        if url.endswith("/capabilities"):
            return 200, '<UserCap><passwordLen min="1" max="16"/></UserCap>'
        return 404, ""

    def put(self, url, user, senha, corpo, timeout=None):
        self.escritas.append(("PUT", url, corpo))
        if url.endswith("/Integrate"):
            self.onvif = "<ONVIF>\n<enable>true</enable>" in corpo
            self.cgi = "<CGI>\n<enable>true</enable>" in corpo
            return self.ok()
        uid = int(url.rsplit("/", 1)[1])
        self.usuarios[uid] = (re.search(r"<userName>(.*?)<", corpo).group(1), re.search(r"<userType>(.*?)<", corpo).group(1))
        return self.ok()

    def post(self, url, user, senha, corpo, content_type=None, timeout=None):
        self.escritas.append(("POST", url, corpo))
        uid = int(re.search(r"<id>(\d+)</id>", corpo).group(1))
        self.usuarios[uid] = (re.search(r"<userName>(.*?)<", corpo).group(1), re.search(r"<userType>(.*?)<", corpo).group(1))
        return self.ok()

    def delete(self, url, user, senha, timeout=None):
        self.escritas.append(("DELETE", url, ""))
        self.usuarios.pop(int(url.rsplit("/", 1)[1]), None)
        return self.ok()


@pytest.fixture
def cam(monkeypatch):
    c = CameraFalsa()
    monkeypatch.setattr(O, "_base", lambda host, porta, conector: f"http://10.209.205.{host.rsplit('.', 1)[1]}")
    monkeypatch.setattr(O, "_pedir", c.get)
    monkeypatch.setattr(O, "_put", c.put)
    monkeypatch.setattr(O, "_postar", c.post)
    monkeypatch.setattr(O, "_apagar", c.delete)
    return c


def test_le_estado_da_camera_real(cam):
    r = O.ler("172.16.45.101", "admin", "certa")
    assert r["onvif_ligado"] is False and r["usuarios"] == [] and r["senha_max"] == 16
    assert r["_ns"] == NS


def test_senha_de_admin_errada_vira_mensagem_clara(cam):
    with pytest.raises(ValueError, match="recusou usuario e senha"):
        O.ler("172.16.45.101", "admin", "errada")


def test_ligar_mexe_so_no_bloco_onvif(cam):
    r = O.ligar("172.16.45.101", "admin", "certa", True)
    assert r["onvif_ligado"] is True and cam.cgi is False      # CGI continua como estava
    assert "<ISAPI>\n<enable>true</enable>" in cam.escritas[0][2]


def test_preparar_para_gravador_liga_e_cria(cam):
    r = O.preparar_para_gravador("172.16.45.101", "admin", "certa", "onvif", "Senha123", "administrator")
    assert r["onvif_ligado"] and r["usuarios"] == [{"id": "1", "nome": "onvif", "perfil": "administrator"}]
    assert r["passos"] == ["ONVIF ligado", "usuario onvif criado"]
    post = next(e for e in cam.escritas if e[0] == "POST")
    assert f'xmlns="{NS}"' in post[2]                            # o namespace da propria camera


def test_preparar_de_novo_so_atualiza_o_usuario(cam):
    O.preparar_para_gravador("172.16.45.101", "admin", "certa", "onvif", "Senha123")
    cam.escritas.clear()
    r = O.preparar_para_gravador("172.16.45.101", "admin", "certa", "onvif", "Outra456", "operator")
    assert r["passos"] == ["usuario onvif atualizado"]
    assert [e[0] for e in cam.escritas] == ["PUT"] and cam.escritas[0][1].endswith("/users/1")
    assert cam.usuarios[1] == ("onvif", "operator")


def test_senha_onvif_maior_que_a_camera_aceita(cam):
    with pytest.raises(ValueError, match="1 a 16"):
        O.criar_usuario("172.16.45.101", "admin", "certa", "onvif", "x" * 17)
    assert cam.escritas == []


def test_nome_com_caractere_estranho_nao_vai(cam):
    with pytest.raises(ValueError, match="nome do usuario"):
        O.criar_usuario("172.16.45.101", "admin", "certa", "on vif<", "abc")


def test_apagar(cam):
    O.preparar_para_gravador("172.16.45.101", "admin", "certa", "onvif", "Senha123")
    r = O.apagar_usuario("172.16.45.101", "admin", "certa", "1")
    assert r["usuarios"] == []


def test_camera_sem_onvif_pelo_isapi(cam, monkeypatch):
    monkeypatch.setattr(O, "_pedir", lambda *a, **k: (404, ""))
    with pytest.raises(ValueError, match="nao tem ONVIF"):
        O.ler("10.0.0.5", "admin", "certa")


# ----- rota /api/deployments/camera-onvif: isolamento (revisor, 26/10/2026)

def _rota(monkeypatch, linha, payload, chamadas=None):
    from fastapi import HTTPException
    from app.api.endpoints import cameras as C
    from app.api.endpoints import deployments as D
    from app.services import recorder_canais as RC
    monkeypatch.setattr(C, "_camera_row_for_ip", lambda ip, cid="": linha)
    monkeypatch.setattr(RC, "senha_da_camera", lambda mac, site, u, s: ("admin", s or ("salva-" + mac if mac else "")))
    vistos = chamadas if chamadas is not None else []
    monkeypatch.setattr(O, "ler", lambda ip, u, s, cid="", porta=None: vistos.append((ip, u, s, cid, porta)) or {"onvif_ligado": False, "usuarios": []})
    try:
        return D.api_deployments_camera_onvif(payload, request=None)
    except HTTPException as e:
        return e


def test_rota_recusa_ip_fora_do_inventario_do_cliente(monkeypatch):
    r = _rota(monkeypatch, None, {"acao": "ler", "ip": "10.208.3.7", "connector_id": "", "senha": "chute"})
    assert getattr(r, "status_code", None) == 404


def test_rota_usa_conector_e_mac_do_inventario_nao_do_pedido(monkeypatch):
    vistos = []
    linha = {"ip": "172.16.45.101", "mac": "e0:ca:3c:b6:7a:0d", "site": "INTERBLOCOS", "remote_connector_id": "conector-do-cliente"}
    r = _rota(monkeypatch, linha, {"acao": "ler", "ip": "172.16.45.101", "connector_id": "conector-de-outro",
                                   "mac": "mac-de-outro", "porta": 8443}, vistos)
    assert r["ok"] is True
    assert vistos == [("172.16.45.101", "admin", "salva-e0:ca:3c:b6:7a:0d", "conector-do-cliente", None)]


def test_rota_recusa_ip_virtual_sem_conector(monkeypatch):
    r = _rota(monkeypatch, {"ip": "10.209.205.101"}, {"acao": "ler", "ip": "10.209.205.101", "senha": "x"})
    assert getattr(r, "status_code", None) == 400
