"""Escuta ao vivo dos leitores: reconhece o aviso de passagem e abre/fecha uma
escuta por leitor ativo. Sem rede: a thread e falsa."""
from app.services import access_control_escuta as E


def test_aviso_de_passagem_e_so_a_linha_do_evento():
    assert E.e_aviso_de_passagem(b"Code=AccessControl;action=Pulse;index=0;data={}")
    assert E.e_aviso_de_passagem(b"Code=_DoorFace_;action=Pulse;index=0;data={")      # rosto (SS 3542)
    assert E.e_aviso_de_passagem(b"Code=DoorStatus;action=Pulse;index=0;data={")      # porta abriu
    assert not E.e_aviso_de_passagem(b"Code=VideoMotion;action=Start;index=0;data={")
    assert not E.e_aviso_de_passagem(b"Code=ScreenSaver;action=Pulse;index=0;data={")
    assert not E.e_aviso_de_passagem(b"Heartbeat")
    assert not E.e_aviso_de_passagem(b"--myboundary")
    assert not E.e_aviso_de_passagem(b"Content-Type: text/plain")


class _Falsa:
    criadas = []

    def __init__(self, tenant, device_id):
        import threading
        self.tenant, self.device_id = tenant, device_id
        self.parar = threading.Event()
        self.ligada, self.avisos, self.viva = True, 0, True
        _Falsa.criadas.append(self)

    def start(self):
        pass

    def is_alive(self):
        return self.viva and not self.parar.is_set()


def test_reconciliar_abre_fecha_e_refaz():
    E.parar_todas()
    _Falsa.criadas = []
    r = E.reconciliar({"cli-a": ["l1", "l2"], "cli-b": ["l3"]}, fabrica=_Falsa)
    assert r["leitores"] == 3 and len(_Falsa.criadas) == 3
    # leitor l2 saiu, l1 morreu: l2 fecha, l1 e refeita, l3 continua a mesma
    l1, l2, l3 = _Falsa.criadas
    l1.viva = False
    r = E.reconciliar({"cli-a": ["l1"], "cli-b": ["l3"]}, fabrica=_Falsa)
    assert r["leitores"] == 2 and l2.parar.is_set() and len(_Falsa.criadas) == 4
    assert {(e.tenant, e.device_id) for e in _Falsa.criadas[3:]} == {("cli-a", "l1")}
    assert not l3.parar.is_set()
    E.parar_todas()
    assert l3.parar.is_set()
