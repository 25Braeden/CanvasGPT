from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.views.decorators.debug import sensitive_variables

from canvas_sync.models import CanvasConnection
from canvas_sync.token_crypto import (
    CanvasCredentialError, decrypt_token, encrypt_token, token_cipher,
)


class Command(BaseCommand):
    help = "Rotate saved Canvas credentials offline; read both keys from the environment."

    @sensitive_variables("current", "replacement", "rows", "stored", "token")
    def handle(self, *args, **options):
        try:
            current = token_cipher(settings.CANVAS_TOKEN_ENCRYPTION_KEY)
            replacement = token_cipher(settings.CANVAS_TOKEN_NEXT_ENCRYPTION_KEY)
            if settings.CANVAS_TOKEN_ENCRYPTION_KEY == settings.CANVAS_TOKEN_NEXT_ENCRYPTION_KEY:
                raise CommandError("The replacement Canvas key must differ from the current key.")
            with transaction.atomic():
                connections = CanvasConnection.objects.exclude(access_token_ciphertext="")
                rows = list(connections.order_by("pk").values_list("pk", "access_token_ciphertext"))
                for pk, stored in rows:
                    token = decrypt_token(stored, cipher=current)
                    connections.filter(pk=pk).update(
                        access_token_ciphertext=encrypt_token(token, cipher=replacement),
                    )
        except (CanvasCredentialError, DatabaseError):
            raise CommandError("Canvas key rotation failed. No credentials were changed. "
                               "Verify both keys and the database before retrying.") from None
        self.stdout.write(self.style.SUCCESS(f"Rotated {len(rows)} Canvas credential(s)."))
