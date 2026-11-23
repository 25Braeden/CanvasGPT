import base64
import hashlib

import requests
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ai_assistant.models import TaskItem
from planner.models import PlanSession, StudyPlan

from .models import Assignment, CanvasConnection, Course
from .test_support import TEST_TOKEN_KEY, ciphertext_for_test
from .token_crypto import CanvasCredentialError, decrypt_token


@override_settings(CANVAS_TOKEN_ENCRYPTION_KEY=TEST_TOKEN_KEY)
class CanvasCredentialTests(TestCase):
    TOKEN = "1234~private-canvas-token"
    URL = "https://example.instructure.com"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="credential-owner")
        cls.connection = CanvasConnection.objects.create(
            user=cls.user, canvas_base_url=cls.URL,
            access_token_ciphertext=ciphertext_for_test(cls.TOKEN),
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.connection_url = reverse("canvas_sync:connection")
        self.sync_url = reverse("canvas_sync:sync")
        self.disconnect_url = reverse("canvas_sync:disconnect")

    def raw_token(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT access_token FROM canvas_sync_canvasconnection WHERE id = %s", [self.connection.pk])
            return cursor.fetchone()[0]

    def save(self, token, url=None):
        return self.client.post(self.connection_url, {
            "canvas_base_url": url or self.URL, "access_token": token,
        }, follow=True)

    @patch("canvas_sync.views.CanvasAPIClient")
    def test_new_and_replacement_tokens_are_encrypted_and_used_for_sync(self, client):
        CanvasConnection.objects.filter(pk=self.connection.pk).delete()
        for token in (self.TOKEN, "replacement-canvas-token"):
            response = self.save(token)
            self.assertContains(response, "Canvas connection saved successfully.")
            self.connection = CanvasConnection.objects.get(user=self.user)
            raw = self.raw_token()
            self.assertNotIn(token, raw)
            self.assertNotContains(response, token)
            self.assertNotContains(response, raw)
            self.assertEqual(self.connection.access_token_ciphertext, raw)
            self.assertEqual(decrypt_token(raw), token)
            self.client.post(self.sync_url)
            client.assert_called_with(self.URL, token)

    @patch("canvas_sync.views.decrypt_token", side_effect=AssertionError("unexpected decrypt"))
    def test_blank_update_and_page_load_do_not_decrypt(self, _decrypt):
        raw = self.raw_token()
        response = self.save("", self.URL + "/")
        self.assertContains(response, "Canvas connection saved successfully.")
        self.assertEqual(self.raw_token(), raw)

    def test_blank_update_cannot_move_saved_token_to_a_different_origin(self):
        response = self.save("", "https://different.example.test")
        self.assertContains(response, "Enter a token for the new Canvas address.")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.canvas_base_url, self.URL)

    def test_insecure_canvas_address_is_rejected(self):
        response = self.save(self.TOKEN, "http://example.instructure.com")
        self.assertContains(response, "Enter a valid HTTPS Canvas URL.")
        self.assertNotContains(response, self.TOKEN)

    @patch("canvas_sync.views.CanvasAPIClient")
    def test_missing_and_invalid_keys_fail_closed(self, client):
        raw = self.raw_token()
        for key in ("", "not-a-fernet-key"):
            with self.subTest(key=key), override_settings(CANVAS_TOKEN_ENCRYPTION_KEY=key):
                self.assertContains(self.save("replacement"), "credential encryption is unavailable")
                self.assertContains(self.client.post(self.sync_url, follow=True), "credential encryption is unavailable")
                self.assertEqual(self.raw_token(), raw)
        client.assert_not_called()

    @patch("canvas_sync.views.CanvasAPIClient")
    def test_wrong_key_and_plaintext_are_not_used(self, client):
        with override_settings(CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")):
            self.assertContains(self.client.post(self.sync_url, follow=True), "saved Canvas access token could not be read")
        CanvasConnection.objects.filter(pk=self.connection.pk).update(access_token_ciphertext=self.TOKEN)
        response = self.client.post(self.sync_url, follow=True)
        self.assertContains(response, "saved Canvas access token could not be read")
        self.assertNotContains(response, self.TOKEN)
        client.assert_not_called()
        self.assertContains(self.save(self.TOKEN), "Canvas connection saved successfully.")
        self.assertEqual(decrypt_token(self.raw_token()), self.TOKEN)

    @patch("canvas_sync.services.CanvasAPIClient.sync_user_data")
    def test_sync_logs_do_not_include_exception_details(self, sync):
        sync.side_effect = requests.ConnectionError(self.TOKEN)
        with self.assertLogs("canvas_sync.views", level="WARNING") as logs:
            response = self.client.post(self.sync_url, follow=True)
        self.assertContains(response, "Canvas could not be reached")
        self.assertNotContains(response, self.TOKEN)
        self.assertNotIn(self.TOKEN, "\n".join(logs.output))
        self.assertIsNone(logs.records[0].exc_info)

    def test_admin_hides_token_and_ciphertext(self):
        admin_user = get_user_model().objects.create_superuser(username="credential-admin")
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:canvas_sync_canvasconnection_change", args=[self.connection.pk]))
        self.assertNotContains(response, self.TOKEN)
        self.assertNotContains(response, self.raw_token())

    def test_disconnect_requires_login_post_csrf_and_confirmation(self):
        self.assertEqual(Client().post(self.disconnect_url, {"confirm": "yes"}).status_code, 302)
        self.assertEqual(self.client.get(self.disconnect_url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.disconnect_url, {"confirm": "yes"}).status_code, 403)
        csrf_client.get(self.connection_url)
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value
        response = csrf_client.post(self.disconnect_url, {"csrfmiddlewaretoken": token}, follow=True)
        self.assertContains(response, "Confirm that you want to disconnect Canvas.")
        self.assertTrue(CanvasConnection.objects.filter(pk=self.connection.pk).exists())
        response = csrf_client.post(self.disconnect_url, {"csrfmiddlewaretoken": token, "confirm": "yes"}, follow=True)
        self.assertContains(response, "Canvas disconnected.")
        self.assertFalse(CanvasConnection.objects.filter(pk=self.connection.pk).exists())

    @patch("canvas_sync.views.CanvasAPIClient")
    def test_disconnect_is_scoped_and_preserves_planning_data(self, client):
        other_user = get_user_model().objects.create_user(username="other-credential-owner")
        other = CanvasConnection.objects.create(
            user=other_user, canvas_base_url=self.URL,
            access_token_ciphertext=ciphertext_for_test("other-token"),
        )
        course = Course.objects.create(user=self.user, canvas_course_id=10, name="Course")
        assignment = Assignment.objects.create(course=course, canvas_assignment_id=20, title="Assignment")
        task = TaskItem.objects.create(user=self.user, assignment=assignment, description="Study")
        now = timezone.now()
        plan = StudyPlan.objects.create(user=self.user, start_date=now.date(), end_date=now.date())
        session = PlanSession.objects.create(study_plan=plan, task_item=task, scheduled_start=now, scheduled_end=now + timedelta(minutes=30))
        response = self.client.post(self.disconnect_url, {"confirm": "yes", "connection_id": other.pk}, follow=True)
        self.assertContains(response, "assignments, checklist tasks, and study plans remain")
        self.assertContains(response, "Approved Integrations")
        self.assertFalse(CanvasConnection.objects.filter(user=self.user).exists())
        for obj in (other, course, assignment, task, plan, session):
            obj.refresh_from_db()
        self.assertContains(self.client.post(self.sync_url, follow=True), "Save your Canvas connection before syncing.")
        client.assert_not_called()
        self.save(self.TOKEN)
        self.client.post(self.sync_url)
        client.assert_called_once_with(self.URL, self.TOKEN)

    def test_rotate_reencrypts_with_next_key(self):
        next_key = Fernet.generate_key().decode("ascii")
        with override_settings(CANVAS_TOKEN_NEXT_ENCRYPTION_KEY=next_key):
            call_command("rotate_canvas_token_key", stdout=StringIO())
        raw = self.raw_token()
        with self.assertRaises(CanvasCredentialError):
            decrypt_token(raw)
        with override_settings(CANVAS_TOKEN_ENCRYPTION_KEY=next_key):
            self.assertEqual(decrypt_token(raw), self.TOKEN)

    def test_rotate_rolls_back_on_unreadable_row(self):
        raw = self.raw_token()
        other_user = get_user_model().objects.create_user(username="bad-credential-owner")
        CanvasConnection.objects.create(user=other_user, canvas_base_url=self.URL, access_token_ciphertext="broken")
        with override_settings(CANVAS_TOKEN_NEXT_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii")):
            with self.assertRaisesMessage(CommandError, "No credentials were changed"):
                call_command("rotate_canvas_token_key", stdout=StringIO())
        self.assertEqual(self.raw_token(), raw)

    def run_data_migration(self, name):
        loader = MigrationLoader(connection)
        key = ("canvas_sync", name)
        migration = loader.get_migration(*key)
        operation = next(op for op in migration.operations if hasattr(op, "code"))
        with transaction.atomic():
            operation.code(loader.project_state(key, at_end=False).apps, connection.schema_editor())

    def test_plaintext_migration_requires_key_and_encrypts_existing_value(self):
        CanvasConnection.objects.filter(pk=self.connection.pk).update(access_token_ciphertext=self.TOKEN)
        name = "0009_encrypt_canvas_access_token"
        with override_settings(CANVAS_TOKEN_ENCRYPTION_KEY=""):
            with self.assertRaises(CanvasCredentialError):
                self.run_data_migration(name)
        self.assertEqual(self.raw_token(), self.TOKEN)
        self.run_data_migration(name)
        self.assertNotIn(self.TOKEN, self.raw_token())
        self.assertEqual(decrypt_token(self.raw_token()), self.TOKEN)

    def test_legacy_ciphertext_upgrade_rejects_wrong_key_and_rolls_back(self):
        secret = "legacy-test-secret"
        legacy_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        raw = Fernet(legacy_key).encrypt(self.TOKEN.encode()).decode("ascii")
        CanvasConnection.objects.filter(pk=self.connection.pk).update(access_token_ciphertext=raw)
        name = "0010_explicit_canvas_token_ciphertext"
        with override_settings(CANVAS_TOKEN_LEGACY_SECRET="wrong-secret"):
            with self.assertRaises(CanvasCredentialError):
                self.run_data_migration(name)
        self.assertEqual(self.raw_token(), raw)
        other_user = get_user_model().objects.create_user(username="bad-legacy-owner")
        other = CanvasConnection.objects.create(user=other_user, canvas_base_url=self.URL, access_token_ciphertext="broken")
        with override_settings(CANVAS_TOKEN_LEGACY_SECRET=secret):
            with self.assertRaises(CanvasCredentialError):
                self.run_data_migration(name)
            self.assertEqual(self.raw_token(), raw)
            other.delete()
            self.run_data_migration(name)
        self.assertEqual(decrypt_token(self.raw_token()), self.TOKEN)
