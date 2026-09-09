"""Symmetric encryption for integration secrets kept in the database.

SMTP / IMAP passwords and the Entra client secret are entered in the Settings UI
and stored encrypted. The key lives only in the ``CRM_SECRETS_KEY`` environment
variable (a Fernet key), never in the database, so database dumps and the ZIP
export carry only opaque ciphertext.

Without the key the non-secret parts of each integration still work and the UI
shows a notice; secret fields cannot be saved.
"""
import os

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:v1:"


def _fernet():
    key = (os.environ.get("CRM_SECRETS_KEY") or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        return None


def secrets_available():
    """True when a usable ``CRM_SECRETS_KEY`` is configured."""
    return _fernet() is not None


def encrypt(plaintext):
    plaintext = plaintext or ""
    if not plaintext:
        return ""
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError("CRM_SECRETS_KEY is not set")
    return _PREFIX + fernet.encrypt(plaintext.encode()).decode()


def decrypt(token):
    token = token or ""
    if not token.startswith(_PREFIX):
        return ""
    fernet = _fernet()
    if fernet is None:
        return ""
    try:
        return fernet.decrypt(token[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""


def looks_encrypted(value):
    return bool(value) and value.startswith(_PREFIX)
