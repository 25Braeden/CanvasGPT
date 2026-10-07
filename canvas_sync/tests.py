from datetime import timedelta
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from canvasgpt.views import get_dashboard_sync_status

from .models import Assignment, CanvasConnection, Course, RubricCriterion
from .services import CanvasAPIClient, CanvasSyncError
from .views import get_assignment_sync_status


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


class AssignmentSyncStatusTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="status-user",
            password="testpassword123",
        )
        self.course = Course.objects.create(
            user=self.user,
            canvas_course_id=1,
            name="Status Course",
        )
        self.assignment = Assignment.objects.create(
            course=self.course,
            canvas_assignment_id=1,
            title="Status Assignment",
        )

    def test_recent_assignment_is_up_to_date(self):
        status = get_assignment_sync_status(self.assignment)

        self.assertEqual(status["level"], "success")
        self.assertEqual(status["label"], "Up to date")

    def test_stale_assignment_has_warning(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            last_synchronized_at=timezone.now() - timedelta(hours=25)
        )
        self.assignment.refresh_from_db()

        status = get_assignment_sync_status(self.assignment)

        self.assertEqual(status["level"], "warning")
        self.assertEqual(status["label"], "Sync may be stale")

    def test_failed_assignment_uses_stored_error_message(self):
        self.assignment.sync_status = Assignment.SyncStatus.FAILED
        self.assignment.sync_error_message = "Canvas connection needs attention."
        self.assignment.save()

        status = get_assignment_sync_status(self.assignment)

        self.assertEqual(status["level"], "error")
        self.assertEqual(status["label"], "Sync failed")
        self.assertEqual(
            status["message"],
            "Canvas connection needs attention.",
        )

    def test_assignment_without_timestamp_is_not_synced(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            last_synchronized_at=None
        )
        self.assignment.refresh_from_db()

        status = get_assignment_sync_status(self.assignment)

        self.assertEqual(status["level"], "warning")
        self.assertEqual(status["label"], "Not synced yet")


class AssignmentDetailPageTests(TestCase):
    fixtures = ["assignment_detail.json"]

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.get(pk=9001)
        self.assignment = Assignment.objects.get(pk=9001)
        self.client.force_login(self.user)

    def detail_url(self):
        return reverse(
            "canvas_sync:assignment_detail",
            args=[self.assignment.pk],
        )

    def test_displays_fixture_backed_synchronized_assignment_details(self):
        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canvas Integration Project")
        self.assertContains(response, "Software Engineering — CSC 3400")
        self.assertContains(
            response,
            "Build and document a Canvas API integration.",
        )
        self.assertContains(response, "Oct 15, 2026, 11:59 PM")
        self.assertContains(response, "100.00")
        self.assertContains(
            response,
            "https://example.instructure.com/courses/50001/assignments/60001",
        )
        self.assertContains(response, "Implementation quality")
        self.assertContains(response, "Documentation")

    def test_displays_no_due_date_fallback(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(due_at=None)

        response = self.client.get(self.detail_url())

        self.assertContains(response, "No due date provided")

    def test_displays_no_rubric_fallback(self):
        self.assignment.rubric_criteria.all().delete()

        response = self.client.get(self.detail_url())

        self.assertContains(
            response,
            "No rubric criteria were synchronized for this assignment.",
        )

    def test_displays_recent_sync_status(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            sync_status=Assignment.SyncStatus.SUCCESS,
            sync_error_message="",
            last_synchronized_at=timezone.now(),
        )

        response = self.client.get(self.detail_url())

        self.assertEqual(
            response.context["assignment_sync_status"]["label"],
            "Up to date",
        )
        self.assertContains(response, "Canvas sync: Up to date")

    def test_displays_stale_sync_status(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            sync_status=Assignment.SyncStatus.SUCCESS,
            last_synchronized_at=timezone.now() - timedelta(hours=25),
        )

        response = self.client.get(self.detail_url())

        self.assertEqual(
            response.context["assignment_sync_status"]["label"],
            "Sync may be stale",
        )
        self.assertContains(response, "Canvas sync: Sync may be stale")

    def test_displays_failed_sync_status_and_safe_error(self):
        CanvasConnection.objects.create(
            user=self.user,
            canvas_base_url="https://example.instructure.com",
            access_token="canvas-token-secret",
        )
        Assignment.objects.filter(pk=self.assignment.pk).update(
            sync_status=Assignment.SyncStatus.FAILED,
            sync_error_message="Canvas sync failed. Check your Canvas connection.",
        )

        response = self.client.get(self.detail_url())

        self.assertEqual(
            response.context["assignment_sync_status"]["label"],
            "Sync failed",
        )
        self.assertContains(
            response,
            "Canvas sync failed. Check your Canvas connection.",
        )
        self.assertNotContains(response, "canvas-token-secret")

    def test_displays_missing_timestamp_status(self):
        Assignment.objects.filter(pk=self.assignment.pk).update(
            sync_status=Assignment.SyncStatus.SUCCESS,
            last_synchronized_at=None,
        )

        response = self.client.get(self.detail_url())

        self.assertEqual(
            response.context["assignment_sync_status"]["label"],
            "Not synced yet",
        )
        self.assertContains(response, "Canvas sync: Not synced yet")

    def test_logged_out_user_is_redirected_to_login(self):
        self.client.logout()

        response = self.client.get(self.detail_url())

        self.assertRedirects(
            response,
            f'{reverse("accounts:login")}?next={self.detail_url()}',
        )

    def test_user_cannot_access_another_users_assignment(self):
        User = get_user_model()
        other_user = User.objects.create_user(
            username="other-student",
            password="testpassword123",
        )
        self.client.force_login(other_user)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.status_code, 404)


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

    def test_canvas_ids_are_unique_per_parent_record(self):
        course = Course.objects.create(
            user=self.user,
            canvas_course_id=12345,
            name="Course",
        )
        Assignment.objects.create(
            course=course,
            canvas_assignment_id=67890,
            title="Assignment",
        )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Course.objects.create(
                    user=self.user,
                    canvas_course_id=12345,
                    name="Duplicate Course",
                )

        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Assignment.objects.create(
                    course=course,
                    canvas_assignment_id=67890,
                    title="Duplicate Assignment",
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

    def test_connection_form_does_not_prefill_saved_credentials(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("canvas_sync:connection"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"]["canvas_base_url"].value(),
            "",
        )
        self.assertNotContains(response, self.connection.access_token)

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
        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.sync_status,
            CanvasConnection.SyncStatus.SUCCESS,
        )
        self.assertEqual(self.connection.sync_error_message, "")
        self.assertIsNotNone(self.connection.last_synchronized_at)

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_rubric_criterion_id_updates_renamed_criterion(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = [
            {
                **self.sample_assignments()[0],
                "rubric": [
                    {
                        "id": 900,
                        "description": "Original title",
                        "long_description": "Original description",
                        "points": 20,
                    }
                ],
            }
        ]
        self.client_api.sync_user_data(self.user)
        mock_assignments.return_value[0]["rubric"][0]["description"] = (
            "Renamed title"
        )

        self.client_api.sync_user_data(self.user)

        criteria = RubricCriterion.objects.filter(
            assignment__canvas_assignment_id=200
        )
        self.assertEqual(criteria.count(), 1)
        self.assertEqual(criteria.get().title, "Renamed title")
        self.assertEqual(criteria.get().canvas_rubric_criterion_id, 900)

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_same_named_rubric_criteria_keep_distinct_canvas_ids(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = [
            {
                **self.sample_assignments()[0],
                "rubric": [
                    {"id": 900, "description": "Quality", "points": 10},
                    {"id": 901, "description": "Quality", "points": 20},
                ],
            }
        ]

        self.client_api.sync_user_data(self.user)

        criteria = RubricCriterion.objects.filter(
            assignment__canvas_assignment_id=200
        ).order_by("canvas_rubric_criterion_id")
        self.assertEqual(criteria.count(), 2)
        self.assertEqual(
            list(criteria.values_list("canvas_rubric_criterion_id", flat=True)),
            [900, 901],
        )

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_network_failure_does_not_partially_import_data(
        self,
        mock_courses,
        mock_assignments,
    ):
        existing_course = Course.objects.create(
            user=self.user,
            canvas_course_id=100,
            name="Original course name",
        )
        mock_courses.return_value = self.sample_courses()
        mock_assignments.side_effect = requests.ConnectionError()

        with self.assertRaises(requests.RequestException):
            self.client_api.sync_user_data(self.user)

        existing_course.refresh_from_db()
        self.assertEqual(existing_course.name, "Original course name")
        self.assertTrue(existing_course.is_active)

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
        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.sync_status,
            CanvasConnection.SyncStatus.FAILED,
        )
        self.assertEqual(
            self.connection.sync_error_message,
            "Canvas sync failed. Check your Canvas connection.",
        )

    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_first_sync_failure_has_dashboard_error_state(
        self,
        mock_courses,
    ):
        mock_courses.side_effect = requests.ConnectionError()

        with self.assertRaises(requests.RequestException):
            self.client_api.sync_user_data(self.user)

        self.connection.refresh_from_db()
        sync_status = get_dashboard_sync_status([], self.connection)

        self.assertEqual(sync_status["level"], "error")
        self.assertEqual(sync_status["label"], "Sync failed")
        self.assertNotIn(self.connection.access_token, sync_status["message"])

    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_malformed_courses_response_sets_failure_status(
        self,
        mock_courses,
    ):
        mock_courses.return_value = {"id": 100}

        with self.assertRaises(CanvasSyncError):
            self.client_api.sync_user_data(self.user)

        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.sync_status,
            CanvasConnection.SyncStatus.FAILED,
        )
        self.assertEqual(
            self.connection.sync_error_message,
            "Canvas sync failed. Check your Canvas connection.",
        )

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_missing_assignment_id_sets_failure_status(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = self.sample_courses()
        mock_assignments.return_value = [{"name": "Missing ID"}]

        with self.assertRaises(CanvasSyncError):
            self.client_api.sync_user_data(self.user)

        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.sync_status,
            CanvasConnection.SyncStatus.FAILED,
        )

    @patch.object(CanvasAPIClient, "get_course_assignments")
    @patch.object(CanvasAPIClient, "get_active_courses")
    def test_null_optional_canvas_values_are_imported_safely(
        self,
        mock_courses,
        mock_assignments,
    ):
        mock_courses.return_value = [
            {
                "id": 100,
                "name": "Test Course",
                "course_code": None,
                "term": None,
            }
        ]
        mock_assignments.return_value = [
            {
                "id": 200,
                "name": "Test Assignment",
                "description": None,
                "due_at": None,
                "points_possible": None,
                "html_url": None,
                "rubric": None,
            }
        ]

        self.client_api.sync_user_data(self.user)

        course = Course.objects.get(user=self.user, canvas_course_id=100)
        assignment = Assignment.objects.get(
            course=course,
            canvas_assignment_id=200,
        )
        self.assertEqual(course.term, "")
        self.assertEqual(course.course_code, "")
        self.assertEqual(assignment.description, "")
        self.assertEqual(assignment.submission_url, "")

    def test_invalid_json_raises_safe_sync_error(self):
        response = Mock()
        response.json.side_effect = ValueError("not JSON")
        self.client_api.session.get = Mock(return_value=response)

        with self.assertRaises(CanvasSyncError):
            self.client_api.get("courses")

    def test_paginated_courses_are_combined(self):
        first_response = Mock()
        first_response.json.return_value = [{"id": 100}]
        first_response.links = {
            "next": {
                "url": "https://example.instructure.com/api/v1/courses?page=2"
            }
        }
        second_response = Mock()
        second_response.json.return_value = [{"id": 101}]
        second_response.links = {}
        self.client_api.session.get = Mock(
            side_effect=[first_response, second_response]
        )

        courses = self.client_api.get_active_courses()

        self.assertEqual(courses, [{"id": 100}, {"id": 101}])
        self.assertEqual(self.client_api.session.get.call_count, 2)
        self.assertEqual(
            self.client_api.session.get.call_args_list[1].args[0],
            "https://example.instructure.com/api/v1/courses?page=2",
        )
        self.assertIsNone(
            self.client_api.session.get.call_args_list[1].kwargs["params"]
        )

    def test_paginated_assignments_are_combined(self):
        first_response = Mock()
        first_response.json.return_value = [{"id": 200}]
        first_response.links = {
            "next": {
                "url": (
                    "https://example.instructure.com/api/v1/courses/100/"
                    "assignments?page=2"
                )
            }
        }
        second_response = Mock()
        second_response.json.return_value = [{"id": 201}]
        second_response.links = {}
        self.client_api.session.get = Mock(
            side_effect=[first_response, second_response]
        )

        assignments = self.client_api.get_course_assignments(100)

        self.assertEqual(assignments, [{"id": 200}, {"id": 201}])
        self.assertEqual(self.client_api.session.get.call_count, 2)

    @patch.object(CanvasAPIClient, "sync_user_data")
    def test_sync_view_reports_success_and_supports_repeat_sync(self, mock_sync):
        self.client.force_login(self.user)

        first_response = self.client.post(
            reverse("canvas_sync:sync"),
            follow=True,
        )
        second_response = self.client.post(
            reverse("canvas_sync:sync"),
            follow=True,
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertContains(first_response, "Canvas data synced successfully.")
        self.assertEqual(mock_sync.call_count, 2)
        for call in mock_sync.call_args_list:
            self.assertEqual(call.args, (self.user,))

    @patch.object(CanvasAPIClient, "sync_user_data")
    def test_sync_view_handles_malformed_response_error(self, mock_sync):
        mock_sync.side_effect = CanvasSyncError("private response details")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("canvas_sync:sync"),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Canvas sync failed. Check your Canvas URL and access token.",
        )
        self.assertNotContains(response, "private response details")