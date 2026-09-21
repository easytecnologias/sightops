"""Cifra simetrica para segredos operacionais guardados no banco.

Existe por causa do cadastro de OLT: pra tela de ONU virar uma lista suspensa
em vez de um formulario de senha, a senha da OLT precisa ficar no servidor. Em
texto puro isso seria pior que o problema que resolve -- um backup do banco
vazaria a senha de acesso as OLTs de todos os clientes de uma vez.

Escopo: segredo que o sistema precisa **reapresentar** a um equipamento (OLT,
e no futuro DVR/switch). Senha de usuario NAO passa por aqui -- aquilo e hash
com sal em auth_store, que e o certo justamente por nao ser reversivel.

A chave vem de SIGHTOPS_SECRET_KEY. Sem ela, uma e gerada e guardada em
DATA_DIR/secret.key na primeira execucao, pra instalacao nova funcionar sem
configuracao. Isso e conveniencia de bootstrap, nao o modo recomendado: a
chave fica ao lado do banco que ela protege, entao quem leva o volume leva os
dois. Em producao, defina SIGHTOPS_SECRET_KEY no ambiente.

Perder a chave torna as senhas cifradas irrecuperaveis -- por isso o arquivo
gerado entra no backup junto com o banco, ou nao adianta ter backup.
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.paths import DATA_DIR

logger = logging.getLogger("app.crypto")

_KEY_ENV = "SIGHTOPS_SECRET_KEY"
_KEY_FILENAME = "secret.key"

# Prefixo do texto cifrado. Serve pra distinguir valor ja cifrado de valor
# cru que por algum caminho antigo tenha sido gravado direto na coluna --
# sem ele, decifrar um valor cru falharia de um jeito dificil de diagnosticar.
_PREFIX = "enc:v1:"

_fernet: Optional[Fernet] = None


class CryptoError(RuntimeError):
    pass


def _key_path() -> Path:
    return DATA_DIR / _KEY_FILENAME


def _normalize_key(raw: str) -> bytes:
    """Aceita tanto uma chave Fernet pronta quanto uma frase qualquer.

    Exigir formato Fernet valido no .env seria uma pegadinha: o operador poe
    uma senha comum, o servico quebra no start com erro de base64 e ninguem
    entende. Frase livre e derivada por SHA-256 pro formato certo.
    """
    import hashlib

    value = str(raw or "").strip()
    if not value:
        raise CryptoError("chave vazia")
    try:
        candidate = value.encode("utf-8")
        Fernet(candidate)  # valida formato
        return candidate
    except Exception:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


def _load_or_create_key() -> bytes:
    from_env = str(os.getenv(_KEY_ENV) or "").strip()
    if from_env:
        return _normalize_key(from_env)

    path = _key_path()
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return _normalize_key(content)

    key = Fernet.generate_key()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(key.decode("utf-8"), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        # Windows/dev: chmod nao se aplica. Nao e motivo pra falhar.
        pass
    logger.warning(
        "%s nao definida: chave gerada em %s. Inclua este arquivo no backup -- "
        "sem ele as senhas cifradas nao voltam.",
        _KEY_ENV,
        path,
    )
    return key


def _cipher() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def reset_cache() -> None:
    """Esquece a chave em memoria. Usado por teste que troca a chave."""
    global _fernet
    _fernet = None


def is_encrypted(value: str) -> bool:
    return str(value or "").startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """Cifra. String vazia continua vazia -- 'sem senha' nao vira segredo."""
    text = str(plaintext or "")
    if not text:
        return ""
    token = _cipher().encrypt(text.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt(ciphertext: str) -> str:
    """Decifra. Valor sem o prefixo volta como veio.

    O passthrough cobre linha gravada antes desta camada existir; nao e
    silenciamento de erro. Token com prefixo que nao decifra levanta
    CryptoError, porque ai a causa provavel e chave trocada -- e isso o
    operador precisa saber, nao descobrir por senha errada na OLT.
    """
    value = str(ciphertext or "")
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return value
    token = value[len(_PREFIX):]
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CryptoError(
            "nao foi possivel decifrar o segredo: a chave atual nao e a que cifrou "
            f"este valor (confira {_KEY_ENV} ou {_key_path()})"
        ) from exc
