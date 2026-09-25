# ws_scan_test.py
# ROTA DE TESTE PARA SUBSTITUIR TEMPORARIAMENTE A SUA /ws/scan ATUAL
#
# Como usar:
# 1. Localize no seu projeto o arquivo onde hoje existe o `@router.websocket("/ws/scan")`.
# 2. Faça um backup desse arquivo.
# 3. Substitua o conteúdo pela função abaixo (ajuste apenas o nome do `router`
#    se no seu projeto ele tiver outro nome).
# 4. NÃO MUDE o path `/ws/scan`, assim o seu frontend atual continua funcionando.
#
# Depois do teste, é só voltar o arquivo original.

import asyncio
import logging
from fastapi import WebSocket, WebSocketDisconnect, APIRouter

logger = logging.getLogger(__name__)

# Se no seu projeto já existir um `router = APIRouter()` nesse arquivo, 
# aproveite o mesmo e REMOVA esta linha:
router = APIRouter()


@router.websocket("/ws/scan")
async def ws_scan(websocket: WebSocket):
    """Rota de teste para o WS.

    Ao conectar, envia 5 mensagens JSON (type=test, step=0..4),
    com intervalo de 1 segundo entre elas, e depois fecha.

    Se o seu frontend já estiver ouvindo /ws/scan, você deve ver
    essas mensagens chegar na aba *Network → Socket → scan → Messages*.
    """
    await websocket.accept()
    logger.info("WS /ws/scan conectado (TESTE SIMPLES)")

    try:
        for i in range(5):
            msg = {"type": "test", "step": i}
            logger.info("WS SEND: %s", msg)
            await websocket.send_json(msg)
            await asyncio.sleep(1)

        await websocket.close()
        logger.info("WS /ws/scan fechado (fim do teste simples)")

    except WebSocketDisconnect:
        logger.info("WS /ws/scan: cliente desconectou")
