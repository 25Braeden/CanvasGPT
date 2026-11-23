from cryptography.fernet import Fernet

from .token_crypto import encrypt_token


TEST_TOKEN_KEY = Fernet.generate_key().decode("ascii")


def ciphertext_for_test(token):
    return encrypt_token(token, cipher=Fernet(TEST_TOKEN_KEY))
