from django.db import migrations

import canvas_sync.fields
from canvas_sync.fields import decrypt_value, encrypt_value


def _rewrite_tokens(apps, schema_editor, transform):
    # Raw SQL so the field's own encrypt/decrypt hooks don't interfere.
    table = apps.get_model("canvas_sync", "CanvasConnection")._meta.db_table
    connection = schema_editor.connection
    quoted_table = connection.ops.quote_name(table)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT id, access_token FROM {quoted_table}")
        rows = cursor.fetchall()
        for pk, token in rows:
            new_token = transform(token)
            if new_token is not None and new_token != token:
                cursor.execute(
                    f"UPDATE {quoted_table} SET access_token = %s WHERE id = %s",
                    [new_token, pk],
                )


def encrypt_tokens(apps, schema_editor):
    def transform(token):
        if not token or decrypt_value(token) is not None:
            return None  # empty or already encrypted
        return encrypt_value(token)

    _rewrite_tokens(apps, schema_editor, transform)


def decrypt_tokens(apps, schema_editor):
    def transform(token):
        return decrypt_value(token) if token else None

    _rewrite_tokens(apps, schema_editor, transform)


class Migration(migrations.Migration):

    dependencies = [
        ("canvas_sync", "0008_alter_rubriccriterion_canvas_rubric_criterion_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="canvasconnection",
            name="access_token",
            field=canvas_sync.fields.EncryptedTextField(),
        ),
        migrations.RunPython(encrypt_tokens, decrypt_tokens),
    ]
