from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Assignment, CanvasConnection, Course, RubricCriterion
from .services import CanvasAPIClient


class CanvasModelTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="amaan",
            password="testpassword123",
        )

        self.connection = CanvasConnection.objects.create(
            user=self.user,
            canvas_base_url="https://flsouthern.instructure.com",
            access_token="test-token",
        )

        self.course = Course.objects.create(
            user=self.user,
            canvas_course_id=12345,
            name="Software Engineering",
            course_code="CSC 3400",
            term="Fall 2026",
        )

        self.assignment = Assignment.objects.create(
            course=self.course,
            canvas_assignment_id=67890,
            title="Project 1",
            description="Test assignment",
            points_possible=100,
        )

        self.criterion = RubricCriterion.objects.create(
            assignment=self.assignment,
            title="Code Quality",
            description="Code should be readable.",
            points=20,
        )

    def test_canvas_connection_string(self):
        self.assertEqual(
            str(self.connection),
            "amaan's Canvas connection",
        )

    def test_course_string(self):
        self.assertEqual(
            str(self.course),
            "Software Engineering",
        )

    def test_assignment_string(self):
        self.assertEqual(
            str(self.assignment),
            "Project 1",
        )

    def test_rubric_criterion_string(self):
        self.assertEqual(
            str(self.criterion),
            "Code Quality",
        )

    def test_course_belongs_to_user(self):
        self.assertEqual(
            self.course.user,
            self.user,
        )

    def test_assignment_belongs_to_course(self):
        self.assertEqual(
            self.assignment.course,
            self.course,
        )

    def test_rubric_belongs_to_assignment(self):
        self.assertEqual(
            self.criterion.assignment,
            self.assignment,
        )

    def test_canvas_connection_belongs_to_user(self):
        self.assertEqual(
            self.connection.user,
            self.user,
        )


class CanvasSyncTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="syncuser",
            password="testpassword123",
        )

        self.connection = CanvasConnection.objects.create(
            user=self.user,
            canvas_base_url="https://example.instructure.com",
            access_token="test-token",
        )

        self.client_api = CanvasAPIClient(
            self.connection.canvas_base_url,
            self.connection.access_token,
        )

    def sample_courses(self):
        return [
            {
                "id": 100,
                "name": "Test Course",
                "course_code": "TEST 101",
                "term": {
                    "name": "Fall 2026",
                },
            }
        ]

    def sample_assignments(self):
        return [
            {
                "id": 200,
                "name": "Test Assignment",
                "description": "Assignment description",
                "due_at": None,
                "points_possible": 100,
                "html_url": "https://example.com/assignment",
                "rubric": [
                    {
                        "description": "Code Quality",
                        "long_description": "Code should be readable.",
                        "points": 20,
                    }
                ],
            }
        ]

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_successful_sync(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = self.sample_assignments()

        self.client_api.sync_user_data(self.user)

        self.assertEqual(
            Course.objects.filter(user=self.user).count(),
            1,
        )
        self.assertEqual(
            Assignment.objects.count(),
            1,
        )
        self.assertEqual(
            RubricCriterion.objects.count(),
            1,
        )

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_repeated_sync_does_not_duplicate(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = self.sample_assignments()

        self.client_api.sync_user_data(self.user)
        self.client_api.sync_user_data(self.user)

        self.assertEqual(
            Course.objects.filter(user=self.user).count(),
            1,
        )
        self.assertEqual(
            Assignment.objects.count(),
            1,
        )
        self.assertEqual(
            RubricCriterion.objects.count(),
            1,
        )

    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_invalid_credentials_raises_request_error(
        self,
        mock_courses,
    ):
        mock_courses.side_effect = requests.RequestException(
            "Invalid Canvas credentials"
        )

        with self.assertRaises(requests.RequestException):
            self.client_api.sync_user_data(self.user)

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_user_data_isolation(
        self,
        mock_courses,
        mock_assignments,
    ):
        User = get_user_model()

        other_user = User.objects.create_user(
            username="otheruser",
            password="testpassword123",
        )

        mock_courses.return_value = [
            {
                "id": 300,
                "name": "Other User Course",
                "course_code": "OTHER 101",
                "term": {
                    "name": "Fall 2026",
                },
            }
        ]

        mock_assignments.return_value = []

        other_client = CanvasAPIClient(
            "https://example.instructure.com",
            "other-token",
        )

        other_client.sync_user_data(other_user)

        self.assertEqual(
            Course.objects.filter(user=other_user).count(),
            1,
        )
        self.assertEqual(
            Course.objects.filter(user=self.user).count(),
            0,
        )

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_successful_sync_sets_success_status(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = self.sample_assignments()

        self.client_api.sync_user_data(self.user)

        assignment = Assignment.objects.get(
            canvas_assignment_id=200
        )

        self.assertEqual(
            assignment.sync_status,
            Assignment.SyncStatus.SUCCESS,
        )
        self.assertEqual(
            assignment.sync_error_message,
            "",
        )

    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_failed_sync_sets_failure_status(
        self,
        mock_courses,
    ):
        course = Course.objects.create(
            user=self.user,
            canvas_course_id=400,
            name="Existing Course",
            course_code="TEST 400",
            term="Fall 2026",
        )

        assignment = Assignment.objects.create(
            course=course,
            canvas_assignment_id=500,
            title="Existing Assignment",
            description="Existing assignment",
            points_possible=100,
            sync_status=Assignment.SyncStatus.SUCCESS,
            sync_error_message="",
        )

        mock_courses.side_effect = requests.RequestException(
            "Private API failure details"
        )

        with self.assertRaises(requests.RequestException):
            self.client_api.sync_user_data(self.user)

        assignment.refresh_from_db()

        self.assertEqual(
            assignment.sync_status,
            Assignment.SyncStatus.FAILED,
        )

        self.assertEqual(
            assignment.sync_error_message,
            "Canvas sync failed. Check your Canvas connection.",
        )

        self.assertNotIn(
            self.connection.access_token,
            assignment.sync_error_message,
        )