from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import StudentProfile
from .models import CanvasConnection
from .services import CanvasAPIClient, CanvasSyncError


class CanvasAvatarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='avatar-student')
        cls.connection = CanvasConnection.objects.create(
            user=cls.user, canvas_base_url='https://canvas.example.com',
            access_token='private-api-token',
        )

    def setUp(self):
        self.api = CanvasAPIClient(self.connection.canvas_base_url, self.connection.access_token)
        courses_patch = patch.object(self.api, 'get_active_courses', return_value=[])
        courses_patch.start()
        self.addCleanup(courses_patch.stop)

    def saved_avatar(self):
        return StudentProfile.objects.get(user=self.user).canvas_avatar_url

    def test_profile_endpoint_uses_server_side_authorization(self):
        response = Mock()
        response.json.return_value = {'avatar_url': 'https://cdn.example.com/avatar.png'}
        with patch.object(self.api.session, 'get', return_value=response) as get:
            profile = self.api.get_profile()
        get.assert_called_once_with(
            'https://canvas.example.com/api/v1/users/self/profile', params=None, timeout=15,
        )
        self.assertEqual(self.api.session.headers['Authorization'], 'Bearer private-api-token')
        self.assertEqual(profile['avatar_url'], 'https://cdn.example.com/avatar.png')

    def test_successful_sync_saves_only_current_users_avatar(self):
        other = get_user_model().objects.create_user(username='other-avatar-student')
        url = 'https://cdn.example.com/avatar.png'
        with patch.object(self.api, 'get_profile', return_value={'avatar_url': url}) as profile:
            self.api.sync_user_data(self.user)
        profile.assert_called_once_with()
        self.assertEqual(self.saved_avatar(), url)
        self.assertEqual(StudentProfile.objects.get(user=other).canvas_avatar_url, '')
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.sync_status, CanvasConnection.SyncStatus.SUCCESS)

    def test_missing_picture_clears_old_avatar(self):
        for value in (None, '', 123):
            with self.subTest(avatar=value):
                StudentProfile.objects.filter(user=self.user).update(
                    canvas_avatar_url='https://cdn.example.com/old.png',
                )
                with patch.object(self.api, 'get_profile', return_value={'avatar_url': value}):
                    self.api.sync_user_data(self.user)
                self.assertEqual(self.saved_avatar(), '')

    def test_profile_failure_preserves_avatar_and_coursework_sync_success(self):
        url = 'https://cdn.example.com/old.png'
        StudentProfile.objects.filter(user=self.user).update(canvas_avatar_url=url)
        for error in (requests.ConnectionError(), requests.HTTPError(), CanvasSyncError('bad JSON')):
            with self.subTest(error=type(error).__name__):
                with patch.object(self.api, 'get_profile', side_effect=error):
                    self.api.sync_user_data(self.user)
                self.assertEqual(self.saved_avatar(), url)
                self.connection.refresh_from_db()
                self.assertEqual(self.connection.sync_status, CanvasConnection.SyncStatus.SUCCESS)

    def test_unsafe_urls_and_access_tokens_are_never_stored(self):
        for url in (
            'javascript:alert(1)', 'data:image/png;base64,abc', '//cdn.example.com/a.png',
            'http://cdn.example.com/a.png', 'https://user:password@cdn.example.com/a.png',
            'https://cdn.example.com/a.png?access_token=secret',
            'https://cdn.example.com/a.png?access_token=',
            'https://cdn.example.com/private-api-token.png',
            'https://cdn.example.com/private%2Dapi%2Dtoken.png',
            'https://cdn.example.com/a\n.png',
            'https://cdn.example.com/' + 'a' * 2048,
        ):
            with self.subTest(url=url):
                with patch.object(self.api, 'get_profile', return_value={'avatar_url': url}):
                    self.api.sync_user_data(self.user)
                self.assertEqual(self.saved_avatar(), '')

    def test_malformed_profile_is_rejected(self):
        with patch.object(self.api, 'get', return_value=[]):
            with self.assertRaises(CanvasSyncError):
                self.api.get_profile()

    def test_picture_renders_on_home_and_app_without_exposing_api_token(self):
        StudentProfile.objects.filter(user=self.user).update(
            canvas_avatar_url='https://cdn.example.com/avatar.png',
        )
        self.client.force_login(self.user)
        for name in ('home', 'dashboard', 'accounts:profile'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'src="https://cdn.example.com/avatar.png"')
                self.assertContains(response, 'referrerpolicy="no-referrer"')
                self.assertContains(response, '/static/accounts/profile-avatar.js')
                self.assertNotContains(response, 'private-api-token')
                self.assertContains(response, '<span aria-hidden="true">A</span>')

    def test_no_avatar_shows_initial_without_image(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, '<span aria-hidden="true">A</span>')
        self.assertNotContains(response, 'data-profile-avatar>')
