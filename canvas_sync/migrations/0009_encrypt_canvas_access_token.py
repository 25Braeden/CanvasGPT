from django.conf import settings
from django.db import migrations
from django.views.decorators.debug import sensitive_variables

import canvas_sync.fields
from canvas_sync.token_crypto import encrypt_token, token_cipher


@sensitive_variables("rows", "token", "cipher")
def encrypt_tokens(apps, schema_editor):
    # At 0008 this column is plaintext. Installations that already ran the
    # original 0009 skip this migration and are upgraded by 0010 instead.
    model = apps.get_model("canvas_sync", "CanvasConnection")
    connections = model.objects.using(schema_editor.connection.alias)
    rows = list(connections.exclude(access_token="").values_list("pk", "access_token"))
    if rows:
        cipher = token_cipher(settings.CANVAS_TOKEN_ENCRYPTION_KEY)
        for pk, token in rows:
            connections.filter(pk=pk).update(access_token=encrypt_token(token, cipher=cipher))


class Migration(migrations.Migration):
    atomic = True
    dependencies = [
        ("canvas_sync", "0008_alter_rubriccriterion_canvas_rubric_criterion_id"),
    ]
    operations = [
        migrations.AlterField(
            model_name="canvasconnection",
            name="access_token",
            field=canvas_sync.fields.EncryptedTextField(),
        ),
        # Never roll back by writing tokens as plaintext. Restore from backup.
        migrations.RunPython(encrypt_tokens),
    ]
