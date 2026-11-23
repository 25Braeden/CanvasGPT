from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

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

    def test_assignment_due_at_nine_is_past_due_later_that_morning(self):
        student_tz = ZoneInfo('America/Los_Angeles')
        self.user.student_profile.timezone = student_tz.key
        self.user.student_profile.save()
        due_at = datetime(2026, 10, 1, 9, tzinfo=student_tz)
        assignment = self.create_assignment('Due at nine', due_at)
        now = datetime(2026, 10, 1, 10, tzinfo=student_tz).astimezone(datetime_timezone.utc)

        with patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['past_due_assignments'], [assignment])
        self.assertEqual(response.context['due_soon_assignments'], [])

    def test_exact_deadline_boundary(self):
        due_at = datetime(2026, 10, 1, 9, tzinfo=datetime_timezone.utc)
        assignment = self.create_assignment('Deadline boundary', due_at)
        for offset, category in (
            (timedelta(microseconds=-1), 'due_soon_assignments'),
            (timedelta(), 'past_due_assignments'),
            (timedelta(microseconds=1), 'past_due_assignments'),
        ):
            with self.subTest(offset=offset):
                with patch('django.utils.timezone.now', return_value=due_at + offset):
                    response = self.client.get(reverse('dashboard'))
                self.assertEqual(response.context[category], [assignment])
                other = 'past_due_assignments' if category == 'due_soon_assignments' else 'due_soon_assignments'
                self.assertEqual(response.context[other], [])

    def test_due_soon_window_uses_student_local_date_across_utc_midnight(self):
        student_tz = ZoneInfo('America/Los_Angeles')
        self.user.student_profile.timezone = student_tz.key
        self.user.student_profile.save()
        # UTC is already October 2, but the student's local date is October 1.
        now = datetime(2026, 10, 2, 1, tzinfo=datetime_timezone.utc)
        earlier_today = self.create_assignment(
            'Earlier today', datetime(2026, 10, 1, 9, tzinfo=student_tz),
        )
        later_today = self.create_assignment(
            'Later today', datetime(2026, 10, 1, 23, tzinfo=student_tz),
        )
        window_end = self.create_assignment(
            'End of due soon window', datetime(2026, 10, 4, 23, 59, tzinfo=student_tz),
        )
        beyond_window = self.create_assignment(
            'Beyond due soon window', datetime(2026, 10, 5, 0, tzinfo=student_tz),
        )
        with patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['past_due_assignments'], [earlier_today])
        self.assertEqual(response.context['due_soon_assignments'], [later_today, window_end])
        self.assertEqual(response.context['due_later_assignments'], [beyond_window])

    def test_same_day_deadline_keeps_zero_points_and_no_due_date_categories(self):
        now = datetime(2026, 10, 1, 10, tzinfo=datetime_timezone.utc)
        zero_point = self.create_assignment('Zero-point overdue', now - timedelta(hours=1), points_possible=0)
        no_deadline = self.create_assignment('No deadline', None)
        with patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.context['zero_point_assignments'], [zero_point])
        self.assertEqual(response.context['due_later_assignments'], [no_deadline])
        self.assertEqual(response.context['past_due_assignments'], [])
        self.assertEqual(response.context['due_soon_assignments'], [])

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

    def create_connection(self, **kwargs):
        kwargs.setdefault("canvas_base_url", "https://example.instructure.com")
        kwargs.setdefault("access_token", "test-token")
        kwargs.setdefault("sync_status", CanvasConnection.SyncStatus.SUCCESS)
        return CanvasConnection.objects.create(user=self.user, **kwargs)

    def test_stale_sync_notice_offers_sync_now_button(self):
        self.create_connection(
            last_synchronized_at=timezone.now() - timedelta(hours=25),
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["sync_status"]["label"], "Sync may be stale")
        self.assertContains(response, "Sync now")
        self.assertContains(response, f'action="{reverse("canvas_sync:sync")}"')
        self.assertContains(
            response,
            f'<input type="hidden" name="next" value="{reverse("dashboard")}">',
            html=True,
        )

    def test_failed_sync_notice_offers_sync_now_button(self):
        self.create_connection(
            sync_status=CanvasConnection.SyncStatus.FAILED,
            sync_error_message="Canvas could not be reached.",
        )

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Sync now")

    def test_up_to_date_sync_notice_hides_sync_now_button(self):
        self.create_connection(last_synchronized_at=timezone.now())

        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Sync now")

    def test_sync_notice_without_connection_links_to_connection_page(self):
        response = self.client.get(reverse("dashboard"))

        self.assertNotContains(response, "Sync now")
        self.assertContains(response, reverse("canvas_sync:connection"))
        self.assertContains(response, "Connect Canvas")

    @patch("canvas_sync.views.CanvasAPIClient.sync_user_data")
    def test_sync_now_from_dashboard_returns_to_dashboard(self, mock_sync):
        self.create_connection(
            last_synchronized_at=timezone.now() - timedelta(hours=25),
        )

        response = self.client.post(
            reverse("canvas_sync:sync"),
            {"next": reverse("dashboard")},
            follow=True,
        )

        self.assertEqual(response.request["PATH_INFO"], reverse("dashboard"))
        self.assertContains(response, "Canvas data synced successfully.")
        mock_sync.assert_called_once_with(self.user)
