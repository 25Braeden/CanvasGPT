from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .forms import StudentProfileForm


class ReducedMotionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='motion-user', password='StrongPass123!',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def save_preferences(self, enabled):
        data = {
            'first_name': '', 'last_name': '', 'email': 'motion@example.com',
            'timezone': 'UTC', 'preferred_session_minutes': 30,
            'break_minutes': 5, 'daily_study_goal_minutes': 60,
            'due_soon_days': 7, 'dark_mode_enabled': 'on',
        }
        if enabled:
            data['reduced_motion_enabled'] = 'on'
        return self.client.post(reverse('accounts:profile'), data, follow=True)

    def test_defaults_off_and_appears_directly_after_dark_mode(self):
        self.assertFalse(self.user.student_profile.reduced_motion_enabled)
        fields = list(StudentProfileForm().fields)
        self.assertEqual(fields[fields.index('dark_mode_enabled') + 1], 'reduced_motion_enabled')
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, 'Reduced motion')
        self.assertContains(response, 'name="reduced_motion_enabled"')

    def test_enabling_is_saved_and_disables_view_transitions(self):
        response = self.save_preferences(True)
        self.user.student_profile.refresh_from_db()
        self.assertTrue(self.user.student_profile.reduced_motion_enabled)
        self.assertTrue(self.user.student_profile.dark_mode_enabled)
        self.assertContains(response, '<html lang="en" class="reduced-motion">')
        self.assertContains(response, '@view-transition { navigation: none; }')
        for name in ('dashboard', 'planner:plan_detail', 'home'):
            with self.subTest(page=name):
                page = self.client.get(reverse(name))
                self.assertContains(page, '<html lang="en" class="reduced-motion">')

    def test_unchecking_restores_normal_motion_without_changing_dark_mode(self):
        self.save_preferences(True)
        response = self.save_preferences(False)
        self.user.student_profile.refresh_from_db()
        self.assertFalse(self.user.student_profile.reduced_motion_enabled)
        self.assertTrue(self.user.student_profile.dark_mode_enabled)
        self.assertNotContains(response, '<html lang="en" class="reduced-motion">')
        self.assertContains(response, '@view-transition { navigation: auto; }')
        # The saved profile preference takes priority over browser/OS settings.
        self.assertNotContains(response, '@media (prefers-reduced-motion: reduce)')
        home = self.client.get(reverse('home'))
        self.assertNotContains(home, '@media (prefers-reduced-motion: reduce)')

    def test_anonymous_pages_still_respect_browser_motion_settings(self):
        self.client.logout()
        for name in ('home', 'accounts:login'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, '@media (prefers-reduced-motion: reduce)')

    def test_preference_does_not_affect_another_user(self):
        self.save_preferences(True)
        other = get_user_model().objects.create_user(username='normal-motion-user')
        self.client.force_login(other)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, '<html lang="en" class="reduced-motion">')
        self.assertContains(response, '@view-transition { navigation: auto; }')
