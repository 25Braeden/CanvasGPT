"""Authenticated encryption for saved Canvas credentials."""

import base64
import binascii

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


TOKEN_PREFIX = "fernet:v1:"
KEY_ERROR = "Canvas credential encryption is unavailable. Contact your administrator."
TOKEN_ERROR = "The saved Canvas access token could not be read. Re-enter it or contact your administrator."


class CanvasCredentialError(Exception):
    """An error whose message is safe to display to a student."""


@sensitive_variables("key")
def token_cipher(key):
    try:
        encoded = key.encode("ascii")
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded) != encoded:
            raise ValueError
        return Fernet(encoded)
    except (AttributeError, ValueError, binascii.Error):
        raise CanvasCredentialError(KEY_ERROR) from None


@sensitive_variables("token", "cipher")
def encrypt_token(token, *, cipher=None):
    cipher = cipher if cipher is not None else token_cipher(settings.CANVAS_TOKEN_ENCRYPTION_KEY)
    return TOKEN_PREFIX + cipher.encrypt(token.encode()).decode("ascii")


@sensitive_variables("stored", "cipher")
def decrypt_token(stored, *, cipher=None):
    cipher = cipher if cipher is not None else token_cipher(settings.CANVAS_TOKEN_ENCRYPTION_KEY)
    if not stored.startswith(TOKEN_PREFIX):
        raise CanvasCredentialError(TOKEN_ERROR)
    try:
        token = cipher.decrypt(stored[len(TOKEN_PREFIX):].encode("ascii")).decode()
    except (InvalidToken, UnicodeError):
        raise CanvasCredentialError(TOKEN_ERROR) from None
    if not token:
        raise CanvasCredentialError(TOKEN_ERROR)
    return token
