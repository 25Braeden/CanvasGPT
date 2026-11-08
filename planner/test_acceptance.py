import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai_assistant.models import TaskItem
from canvas_sync.models import Assignment, CanvasConnection, Course
from canvas_sync.services import CanvasAPIClient
from planner.models import AvailabilityBlock, StudyPlan


User = get_user_model()
UTC = datetime.timezone.utc


class OfflineMVPAcceptanceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="mvpstudent",
            password="test-password-123",
        )

        self.other_user = User.objects.create_user(
            username="otherstudent",
            password="test-password-123",
        )

        profile = self.user.student_profile
        profile.timezone = "UTC"
        profile.preferred_session_minutes = 30
        profile.break_minutes = 0
        profile.save()

        self.now = datetime.datetime(
            2026,
            11,
            4,
            12,
            0,
            tzinfo=UTC,
        )

        self.client.force_login(self.user)

    def sample_courses(self):
        return [
            {
                "id": 100,
                "name": "Software Engineering",
                "course_code": "CSC 3280",
                "term": {
                    "name": "Fall 2026",
                },
            }
        ]

    def sample_assignments(self):
        return [
            {
                "id": 200,
                "name": "MVP Assignment",
                "description": "Finish the CanvasGPT MVP.",
                "due_at": "2026-11-05T23:00:00Z",
                "points_possible": 100,
                "html_url": "https://example.com/assignment",
                "rubric": [],
            }
        ]

    def test_offline_mvp_workflow(self):
        response = self.client.post(
            reverse("canvas_sync:connection"),
            {
                "canvas_base_url": "https://example.instructure.com",
                "access_token": "test-token",
            },
        )

        self.assertRedirects(
            response,
            reverse("canvas_sync:connection"),
        )

        self.assertTrue(
            CanvasConnection.objects.filter(user=self.user).exists()
        )

        with patch.object(
            CanvasAPIClient,
            "get_active_courses",
            return_value=self.sample_courses(),
        ), patch.object(
            CanvasAPIClient,
            "get_course_assignments",
            return_value=self.sample_assignments(),
        ):
            response = self.client.post(
                reverse("canvas_sync:sync")
            )

        self.assertRedirects(
            response,
            reverse("canvas_sync:connection"),
        )

        self.assertEqual(
            Course.objects.filter(user=self.user).count(),
            1,
        )

        assignment = Assignment.objects.get(
            course__user=self.user,
            canvas_assignment_id=200,
        )

        self.assertEqual(
            assignment.title,
            "MVP Assignment",
        )

        response = self.client.post(
            reverse(
                "ai_assistant:task_add",
                args=[assignment.pk],
            ),
            {
                "description": "Finish MVP checklist",
                "estimated_minutes": 60,
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "canvas_sync:assignment_detail",
                args=[assignment.pk],
            ),
        )

        task = TaskItem.objects.get(
            assignment=assignment,
            user=self.user,
        )

        self.assertEqual(
            task.estimated_minutes,
            60,
        )

        response = self.client.post(
            reverse("planner:availability_add"),
            {
                "recurrence": "none",
                "date": "2026-11-04",
                "weekday": AvailabilityBlock.Weekday.WEDNESDAY,
                "start_time": "18:00",
                "end_time": "20:00",
            },
        )

        self.assertRedirects(
            response,
            reverse("planner:availability_list"),
        )

        self.assertEqual(
            AvailabilityBlock.objects.filter(
                user=self.user
            ).count(),
            1,
        )

        with patch(
            "planner.scheduling.timezone.now",
            return_value=self.now,
        ):
            response = self.client.post(
                reverse("planner:plan_generate")
            )

        self.assertRedirects(
            response,
            reverse("planner:plan_detail"),
        )

        first_plan = StudyPlan.objects.get(
            user=self.user,
            is_active=True,
        )

        first_sessions = list(
            first_plan.sessions.order_by("scheduled_start")
        )

        self.assertEqual(
            len(first_sessions),
            2,
        )

        for session in first_sessions:
            self.assertGreaterEqual(
                session.scheduled_start,
                datetime.datetime(
                    2026,
                    11,
                    4,
                    18,
                    0,
                    tzinfo=UTC,
                ),
            )

            self.assertLessEqual(
                session.scheduled_end,
                datetime.datetime(
                    2026,
                    11,
                    4,
                    20,
                    0,
                    tzinfo=UTC,
                ),
            )

            self.assertLessEqual(
                session.scheduled_end,
                assignment.due_at,
            )

        completed_session = first_sessions[0]

        response = self.client.post(
            reverse(
                "planner:session_toggle",
                args=[completed_session.pk],
            )
        )

        self.assertRedirects(
            response,
            reverse("planner:plan_detail"),
        )

        completed_session.refresh_from_db()

        self.assertTrue(
            completed_session.is_completed
        )

        with patch(
            "planner.scheduling.timezone.now",
            return_value=self.now,
        ):
            self.client.post(
                reverse("planner:plan_generate")
            )

        first_plan.refresh_from_db()

        self.assertFalse(
            first_plan.is_active
        )

        second_plan = StudyPlan.objects.get(
            user=self.user,
            is_active=True,
        )

        second_sessions = list(
            second_plan.sessions.order_by("scheduled_start")
        )

        self.assertEqual(
            len(second_sessions),
            2,
        )

        self.assertEqual(
            sum(
                session.is_completed
                for session in second_sessions
            ),
            1,
        )

        self.client.force_login(self.other_user)

        response = self.client.get(
            reverse(
                "canvas_sync:assignment_detail",
                args=[assignment.pk],
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )

        response = self.client.get(
            reverse("planner:plan_detail")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIsNone(
            response.context["plan"]
        )