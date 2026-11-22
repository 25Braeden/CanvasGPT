import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


logger = logging.getLogger(__name__)


def _fernet():
    """Build the cipher from CANVAS_TOKEN_ENCRYPTION_KEY, or SECRET_KEY if unset."""
    secret = settings.CANVAS_TOKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_value(value):
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(value):
    """Return the plain text, or None if the value can't be decrypted."""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


class EncryptedTextField(models.TextField):
    """A text field stored encrypted in the database and plain in Python.

    Encryption is randomized, so filtering on this field will not match.
    """

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        decrypted = decrypt_value(value)
        if decrypted is None:
            # Wrong or rotated key: behave as if no token is saved so the
            # user is prompted to re-enter it instead of the page crashing.
            logger.warning("Could not decrypt a stored %s value.", self.name)
            return ""
        return decrypted

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return encrypt_value(value)
