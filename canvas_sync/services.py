from datetime import timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

import requests
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Assignment, CanvasConnection, Course, RubricCriterion


SYNC_FAILURE_MESSAGE = "Canvas sync failed. Check your Canvas connection."


class CanvasSyncError(Exception):
    """A safe error for invalid or unusable Canvas API responses."""


def _require_list(value, field_name):
    if not isinstance(value, list):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name} list.")
    return value


def _require_object(value, field_name):
    if not isinstance(value, dict):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name}.")
    return value


def _require_id(value, field_name):
    if isinstance(value, bool):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name} ID.")
    try:
        identifier = int(value)
    except (TypeError, ValueError):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name} ID.") from None
    if identifier < 1:
        raise CanvasSyncError(f"Canvas returned an invalid {field_name} ID.")
    return identifier


def _optional_text(value, field_name):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name}.")
    return value


def _optional_decimal(value, field_name):
    if value is None:
        return None
    if isinstance(value, bool):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name}.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise CanvasSyncError(f"Canvas returned an invalid {field_name}.") from None


def _optional_due_at(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise CanvasSyncError("Canvas returned an invalid assignment due date.")
    due_at = parse_datetime(value)
    if due_at is None:
        raise CanvasSyncError("Canvas returned an invalid assignment due date.")
    if timezone.is_naive(due_at):
        due_at = timezone.make_aware(due_at, datetime_timezone.utc)
    return due_at


class CanvasAPIClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
            }
        )

    def get(self, endpoint, params=None):
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        response = self.session.get(
            url,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError:
            raise CanvasSyncError("Canvas returned invalid JSON.") from None

    def get_active_courses(self):
        return self.get(
            "courses",
            params={
                "enrollment_state": "active",
                "per_page": 100,
            },
        )

    def get_course_assignments(self, course_id):
        return self.get(
            f"courses/{course_id}/assignments",
            params={
                "per_page": 100,
            },
        )

    def sync_user_data(self, user):
        try:
            courses_data = _require_list(
                self.get_active_courses(),
                "courses",
            )

            for course_data in courses_data:
                course_data = _require_object(course_data, "course")
                course_id = _require_id(course_data.get("id"), "course")
                term_data = course_data.get("term")
                if term_data is None:
                    term_name = ""
                else:
                    term_name = _optional_text(
                        _require_object(term_data, "course term").get("name"),
                        "course term name",
                    )

                course, _ = Course.objects.update_or_create(
                    user=user,
                    canvas_course_id=course_id,
                    defaults={
                        "name": _optional_text(
                            course_data.get("name"),
                            "course name",
                        ),
                        "course_code": _optional_text(
                            course_data.get("course_code"),
                            "course code",
                        ),
                        "term": term_name,
                        "is_active": True,
                    },
                )

                assignments_data = _require_list(
                    self.get_course_assignments(course.canvas_course_id),
                    "assignments",
                )
                for assignment_data in assignments_data:
                    assignment_data = _require_object(
                        assignment_data,
                        "assignment",
                    )
                    assignment_id = _require_id(
                        assignment_data.get("id"),
                        "assignment",
                    )
                    rubric_data = assignment_data.get("rubric")
                    if rubric_data is None:
                        rubric_data = []
                    rubric_data = _require_list(rubric_data, "rubric")

                    assignment, _ = Assignment.objects.update_or_create(
                        course=course,
                        canvas_assignment_id=assignment_id,
                        defaults={
                            "title": _optional_text(
                                assignment_data.get("name"),
                                "assignment name",
                            ),
                            "description": _optional_text(
                                assignment_data.get("description"),
                                "assignment description",
                            ),
                            "due_at": _optional_due_at(
                                assignment_data.get("due_at")
                            ),
                            "points_possible": _optional_decimal(
                                assignment_data.get("points_possible"),
                                "assignment points",
                            ),
                            "submission_url": _optional_text(
                                assignment_data.get("html_url"),
                                "assignment submission URL",
                            ),
                            "sync_status": Assignment.SyncStatus.SUCCESS,
                            "sync_error_message": "",
                        },
                    )

                    for criterion_data in rubric_data:
                        criterion_data = _require_object(
                            criterion_data,
                            "rubric criterion",
                        )
                        RubricCriterion.objects.update_or_create(
                            assignment=assignment,
                            title=_optional_text(
                                criterion_data.get("description"),
                                "rubric criterion description",
                            ),
                            defaults={
                                "description": _optional_text(
                                    criterion_data.get("long_description"),
                                    "rubric criterion long description",
                                ),
                                "points": _optional_decimal(
                                    criterion_data.get("points"),
                                    "rubric criterion points",
                                ),
                            },
                        )

            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.SUCCESS,
                sync_error_message="",
                last_synchronized_at=timezone.now(),
            )

        except (requests.RequestException, CanvasSyncError):
            Assignment.objects.filter(course__user=user).update(
                sync_status=Assignment.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )
            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )
            raise
