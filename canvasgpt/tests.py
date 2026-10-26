from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, CanvasConnection, Course


class DashboardAssignmentSectionsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="dashboard-user",
            password="StrongPass123!",
        )
        self.user.student_profile.due_soon_days = 3
        self.user.student_profile.save()
        self.client.force_login(self.user)
        self.course = Course.objects.create(
            user=self.user,
            canvas_course_id=1,
            name="Test Course",
        )

    def create_assignment(self, title, due_at, points_possible=None):
        return Assignment.objects.create(
            course=self.course,
            canvas_assignment_id=Assignment.objects.count() + 1,
            title=title,
            due_at=due_at,
            points_possible=points_possible,
        )

    def test_dashboard_groups_assignments_by_due_date(self):
        now = timezone.now()
        past_due = self.create_assignment("Past due", now - timedelta(days=1))
        due_soon = self.create_assignment("Due soon", now + timedelta(days=2))
        due_later = self.create_assignment("Due later", now + timedelta(days=4))
        no_due_date = self.create_assignment("No due date", None)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["past_due_assignments"]),
            [past_due],
        )
        self.assertEqual(
            list(response.context["due_soon_assignments"]),
            [due_soon],
        )
        self.assertEqual(
            list(response.context["due_later_assignments"]),
            [no_due_date, due_later],
        )
        self.assertContains(
            response,
            "<summary>Due soon <span>(1)</span></summary>",
            html=False,
        )
        self.assertContains(
            response,
            "<summary>Due later <span>(2)</span></summary>",
            html=False,
        )
        self.assertContains(
            response,
            "<summary>Past due <span>(1)</span></summary>",
            html=False,
        )
        self.assertContains(response, "<details", html=False)

    def test_dashboard_groups_zero_point_assignments_separately(self):
        now = timezone.now()
        past_due = self.create_assignment(
            "Zero-point past due",
            now - timedelta(days=1),
            points_possible=0,
        )
        due_soon = self.create_assignment(
            "Zero-point due soon",
            now + timedelta(days=1),
            points_possible=0,
        )
        due_later = self.create_assignment(
            "Zero-point due later",
            now + timedelta(days=4),
            points_possible=0,
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(
            list(response.context["zero_point_assignments"]),
            [past_due, due_soon, due_later],
        )
        self.assertEqual(list(response.context["past_due_assignments"]), [])
        self.assertEqual(list(response.context["due_soon_assignments"]), [])
        self.assertEqual(list(response.context["due_later_assignments"]), [])
        self.assertContains(
            response,
            "<summary>Zero-point assignments <span>(3)</span></summary>",
            html=False,
        )
        self.assertContains(response, "<span>0.00 pts</span>", count=3, html=True)

    def test_recent_successful_connection_overrides_old_assignment_failure(self):
        assignment = self.create_assignment(
            "Previously failed assignment",
            timezone.now() + timedelta(days=1),
        )
        Assignment.objects.filter(pk=assignment.pk).update(
            sync_status=Assignment.SyncStatus.FAILED,
            sync_error_message="Old sync failure",
        )
        CanvasConnection.objects.create(
            user=self.user,
            canvas_base_url="https://example.instructure.com",
            access_token="test-token",
            sync_status=CanvasConnection.SyncStatus.SUCCESS,
            last_synchronized_at=timezone.now(),
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["sync_status"]["level"], "success")
        self.assertEqual(response.context["sync_status"]["label"], "Up to date")
        self.assertNotContains(response, "Old sync failure")

    def test_dashboard_excludes_assignments_from_hidden_courses(self):
        hidden_course = Course.objects.create(
            user=self.user,
            canvas_course_id=2,
            name="Hidden Course",
            is_visible=False,
        )
        hidden_assignment = Assignment.objects.create(
            course=hidden_course,
            canvas_assignment_id=2,
            title="Hidden assignment",
            due_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(reverse("dashboard"))

        displayed_assignments = (
            list(response.context["due_soon_assignments"])
            + list(response.context["due_later_assignments"])
            + list(response.context["past_due_assignments"])
            + list(response.context["zero_point_assignments"])
        )
        self.assertNotIn(hidden_assignment, displayed_assignments)
        self.assertNotContains(response, hidden_assignment.title)
