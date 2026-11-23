import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations, models
from django.views.decorators.debug import sensitive_variables

from canvas_sync.token_crypto import (
    TOKEN_PREFIX, CanvasCredentialError, decrypt_token, encrypt_token, token_cipher,
)


@sensitive_variables("rows", "stored", "legacy_secret", "legacy", "token", "cipher")
def upgrade_legacy_tokens(apps, schema_editor):
    model = apps.get_model("canvas_sync", "CanvasConnection")
    connections = model.objects.using(schema_editor.connection.alias)
    rows = list(connections.exclude(access_token="").order_by("pk").values_list("pk", "access_token"))
    if not rows:
        return
    cipher = token_cipher(settings.CANVAS_TOKEN_ENCRYPTION_KEY)
    legacy = None
    for pk, stored in rows:
        if stored.startswith(TOKEN_PREFIX):
            decrypt_token(stored, cipher=cipher)
            continue
        if legacy is None:
            legacy_secret = settings.CANVAS_TOKEN_LEGACY_SECRET
            if not legacy_secret:
                raise CanvasCredentialError("Set CANVAS_TOKEN_LEGACY_SECRET to upgrade existing Canvas ciphertext.")
            legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(legacy_secret.encode()).digest()))
        try:
            token = legacy.decrypt(stored.encode("ascii")).decode()
        except (InvalidToken, UnicodeError):
            raise CanvasCredentialError("Legacy Canvas ciphertext could not be decrypted. No credentials were changed.") from None
        if not token:
            raise CanvasCredentialError("An empty legacy Canvas credential could not be upgraded.")
        connections.filter(pk=pk).update(access_token=encrypt_token(token, cipher=cipher))


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("canvas_sync", "0009_encrypt_canvas_access_token")]
    operations = [
        migrations.RunPython(upgrade_legacy_tokens),
        # Same physical TEXT column; give the ORM attribute an explicit name.
        migrations.SeparateDatabaseAndState(state_operations=[
            migrations.RemoveField(model_name="canvasconnection", name="access_token"),
            migrations.AddField(
                model_name="canvasconnection", name="access_token_ciphertext",
                field=models.TextField(db_column="access_token", editable=False),
            ),
        ]),
    ]
