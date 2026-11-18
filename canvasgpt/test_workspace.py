from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from canvas_sync.models import Assignment, Course


class DetailsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.details = []

    def handle_starttag(self, tag, attrs):
        if tag == 'details':
            self.details.append(dict(attrs))


class WorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username='workspace-user', password='StrongPass123!',
        )
        course = Course.objects.create(
            user=cls.user, canvas_course_id=101, name='Workspace Course',
        )
        cls.assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=201,
            title='Workspace assignment',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_dashboard_starts_centered_with_right_pane_hidden(self):
        response = self.client.get(reverse('dashboard'))
        self.assertTemplateUsed(response, '_dashboard_panel.html')
        self.assertFalse(response.context['workspace_panel_open'])
        self.assertContains(response, '<main class="workspace">')
        self.assertContains(response, 'aria-label="Selected page" hidden')
        self.assertNotContains(response, 'Your profile')
        self.assertContains(response, 'Workspace assignment')

    def test_profile_navigation_opens_right_pane(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertTrue(response.context['workspace_panel_open'])
        self.assertContains(response, '<main class="workspace panel-open">')
        self.assertNotContains(response, 'aria-label="Selected page" hidden')
        self.assertTemplateUsed(response, 'accounts/_profile_content.html')
        content = response.content.decode()
        left = content.index('class="workspace-dashboard"')
        right = content.index('class="workspace-content"')
        self.assertLess(left, content.index('Workspace assignment'))
        self.assertLess(content.index('Workspace assignment'), right)
        self.assertLess(right, content.index('Your profile'))
        self.assertContains(
            response,
            f'<form method="post" action="{reverse("accounts:profile")}">',
        )

    def test_dashboard_link_returns_to_centered_layout(self):
        self.client.get(reverse('planner:plan_detail'))
        response = self.client.get(reverse('dashboard'))
        self.assertFalse(response.context['workspace_panel_open'])
        self.assertContains(response, 'aria-label="Selected page" hidden')

    def test_panel_animation_is_sequenced_and_contained(self):
        response = self.client.get(reverse('accounts:profile'))
        self.assertContains(response, 'animation-delay: 0ms;')
        self.assertContains(response, 'panel-slide-in 300ms ease-out 350ms both')
        self.assertContains(response, 'panel-slide-out 250ms ease-in both')
        self.assertContains(response, '::view-transition-image-pair(workspace-panel)')
        self.assertContains(response, 'overflow: clip;')
        self.assertContains(response, 'isolation: isolate;')

    def test_recentering_waits_for_right_panel_to_leave(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'animation-delay: 250ms;')

    def test_other_pages_keep_dashboard_and_render_selected_page(self):
        for name in (
            'accounts:profile', 'planner:plan_detail',
            'planner:availability_list', 'planner:availability_add',
            'canvas_sync:connection',
        ):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['workspace_panel_open'])
                self.assertContains(response, '<main class="workspace panel-open">')
                self.assertTemplateUsed(response, '_dashboard_panel.html')
                self.assertContains(response, 'Workspace assignment')
                self.assertContains(response, 'aria-label="Selected page"')
                self.assertContains(response, 'class="workspace-dashboard"', count=1)

    def test_assignment_detail_opens_in_right_pane(self):
        response = self.client.get(reverse(
            'canvas_sync:assignment_detail', args=[self.assignment.pk],
        ))
        self.assertTemplateUsed(response, '_dashboard_panel.html')
        self.assertTemplateUsed(response, 'canvas_sync/assignment_detail.html')
        self.assertContains(response, 'class="workspace-content"')

    def test_only_due_soon_starts_open_without_saved_preferences(self):
        response = self.client.get(reverse('dashboard'))
        parser = DetailsParser()
        parser.feed(response.content.decode())
        self.assertEqual(len(parser.details), 4)
        self.assertEqual(
            [attrs['data-dashboard-section'] for attrs in parser.details if 'open' in attrs],
            ['due-soon'],
        )
        self.assertContains(response, f'data-dashboard-user="{self.user.pk}"')
        self.assertContains(response, '/static/accounts/dashboard-sections.js')

    def test_dashboard_does_not_show_other_users_assignments(self):
        other = get_user_model().objects.create_user(username='other-student')
        course = Course.objects.create(
            user=other, canvas_course_id=102, name='Private Course',
        )
        Assignment.objects.create(
            course=course, canvas_assignment_id=202, title='Private assignment',
        )
        response = self.client.get(reverse('accounts:profile'))
        self.assertNotContains(response, 'Private assignment')
        self.assertNotContains(response, 'Private Course')

    def test_public_pages_do_not_render_workspace(self):
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'class="workspace-dashboard"')
        self.client.logout()
        response = self.client.get(reverse('accounts:login'))
        self.assertNotContains(response, 'class="workspace-dashboard"')

    def test_profile_save_refreshes_dashboard_preferences(self):
        response = self.client.post(reverse('accounts:profile'), {
            'first_name': 'Updated', 'last_name': 'Student',
            'email': 'updated@example.com', 'timezone': 'UTC',
            'preferred_session_minutes': 45, 'break_minutes': 10,
            'daily_study_goal_minutes': 90, 'due_soon_days': 14,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'next 14 days')
        self.assertContains(response, 'Your profile')
        self.assertTemplateUsed(response, '_dashboard_panel.html')
