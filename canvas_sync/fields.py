"""Field reference retained for historical migration 0009 only."""

from django.db import models


class EncryptedTextField(models.TextField):
    pass
