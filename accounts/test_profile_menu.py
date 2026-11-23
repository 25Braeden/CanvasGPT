from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ProfileAvatarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='avatar-user', password='StrongPass123!', first_name='Chris',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_shared_avatar_links_directly_to_profile(self):
        for name in ('home', 'dashboard', 'accounts:profile', 'planner:plan_detail'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertTemplateUsed(response, 'accounts/_profile_menu.html')
                self.assertContains(response, 'class="profile-avatar"', count=1)
                self.assertContains(response, 'aria-label="View profile for Chris"')
                self.assertContains(response, f'class="profile-avatar" href="{reverse("accounts:profile")}"')
                self.assertNotContains(response, 'Signed in as')
                self.assertNotContains(response, 'data-profile-menu')
                self.assertNotContains(response, '/static/accounts/profile-menu.js')
                self.assertContains(response, '/static/accounts/profile-menu.css')

    def test_username_is_used_when_first_name_is_empty(self):
        self.user.first_name = ''
        self.user.save()
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'View profile for avatar-user')

    def test_logout_remains_available_on_profile_page(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, f'method="post" action="{reverse("accounts:logout")}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, '<button type="submit">Log out</button>')
        self.assertTrue(response.context['workspace_panel_open'])

    def test_anonymous_users_have_no_profile_avatar(self):
        self.client.logout()
        for name in ('home', 'accounts:login'):
            response = self.client.get(reverse(name))
            self.assertNotContains(response, 'class="profile-avatar"')
