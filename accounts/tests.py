from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from canvas_sync.models import Course

from .models import StudentProfile

User = get_user_model()


class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='existing-user',
            email='existing@example.com',
            password='StrongPass123!',
        )

    def test_signup_creates_user_profile_and_logs_user_in(self):
        response = self.client.post(
            reverse('accounts:signup'),
            {
                'username': 'new-user',
                'email': 'new@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )

        self.assertRedirects(response, reverse('dashboard'))
        new_user = User.objects.get(username='new-user')
        self.assertTrue(new_user.check_password('StrongPass123!'))
        self.assertTrue(new_user.is_authenticated)
        self.assertTrue(StudentProfile.objects.filter(user=new_user).exists())

    def test_duplicate_username_is_rejected(self):
        response = self.client.post(
            reverse('accounts:signup'),
            {
                'username': self.user.username,
                'email': 'different@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A user with that username already exists.')

    def test_password_mismatch_is_rejected(self):
        response = self.client.post(
            reverse('accounts:signup'),
            {
                'username': 'mismatch-user',
                'email': 'mismatch@example.com',
                'password1': 'StrongPass123!',
                'password2': 'DifferentPass123!',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The two password fields didn’t match.')

    def test_valid_login_redirects_to_dashboard(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': self.user.username, 'password': 'StrongPass123!'},
        )

        self.assertRedirects(response, reverse('dashboard'))

    def test_invalid_login_does_not_authenticate(self):
        response = self.client.post(
            reverse('accounts:login'),
            {'username': self.user.username, 'password': 'wrong-password'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_logout_requires_post_and_ends_session(self):
        self.client.force_login(self.user)

        get_response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, 'You are signed out')
        self.assertFalse(post_response.wsgi_request.user.is_authenticated)

    def test_protected_pages_redirect_anonymous_users_to_login(self):
        for url in (reverse('dashboard'), reverse('accounts:profile')):
            response = self.client.get(url)
            self.assertRedirects(
                response,
                f'{reverse("accounts:login")}?next={url}',
            )


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='profile-user',
            email='profile@example.com',
            password='StrongPass123!',
        )
        self.client.force_login(self.user)

    def test_profile_page_loads_for_authenticated_user(self):
        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your profile')
        self.assertContains(response, 'Study preferences')
        self.assertContains(response, reverse('dashboard'))
        self.assertContains(
            response,
            reverse('canvas_sync:connection'),
        )

    def test_profile_updates_account_and_preferences(self):
        response = self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': 'Updated',
                'last_name': 'Student',
                'email': 'updated@example.com',
                'timezone': 'America/New_York',
                'preferred_session_minutes': 45,
                'break_minutes': 10,
                'daily_study_goal_minutes': 90,
                'notifications_enabled': 'on',
                'due_soon_days': 14,
            },
        )

        self.assertRedirects(response, reverse('accounts:profile'))
        self.user.refresh_from_db()
        profile = self.user.student_profile
        self.assertEqual(self.user.first_name, 'Updated')
        self.assertEqual(self.user.email, 'updated@example.com')
        self.assertEqual(profile.timezone, 'America/New_York')
        self.assertEqual(profile.preferred_session_minutes, 45)
        self.assertEqual(profile.due_soon_days, 14)

    def test_profile_updates_visible_courses(self):
        visible_course = Course.objects.create(
            user=self.user,
            canvas_course_id=1,
            name='Visible course',
        )
        hidden_course = Course.objects.create(
            user=self.user,
            canvas_course_id=2,
            name='Hidden course',
        )

        response = self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': '',
                'last_name': '',
                'email': 'profile@example.com',
                'timezone': 'UTC',
                'preferred_session_minutes': 30,
                'break_minutes': 5,
                'daily_study_goal_minutes': 60,
                'notifications_enabled': 'on',
                'due_soon_days': 7,
                'visible_course_ids': [str(visible_course.pk)],
            },
        )

        self.assertRedirects(response, reverse('accounts:profile'))
        visible_course.refresh_from_db()
        hidden_course.refresh_from_db()
        self.assertTrue(visible_course.is_visible)
        self.assertFalse(hidden_course.is_visible)

    def test_invalid_preferences_are_rejected(self):
        response = self.client.post(
            reverse('accounts:profile'),
            {
                'first_name': '',
                'last_name': '',
                'email': 'profile@example.com',
                'timezone': 'UTC',
                'preferred_session_minutes': 0,
                'break_minutes': 5,
                'daily_study_goal_minutes': 90,
                'notifications_enabled': 'on',
                'due_soon_days': 0,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ensure this value is greater than or equal to 1.')

    def test_profile_page_uses_request_user_profile(self):
        other_user = User.objects.create_user(
            username='other-user',
            password='StrongPass123!',
        )

        response = self.client.get(reverse('accounts:profile'))

        self.assertEqual(response.context['user_form'].instance, self.user)
        self.assertEqual(response.context['profile_form'].instance.user, self.user)
        self.assertNotEqual(response.context['profile_form'].instance.user, other_user)
