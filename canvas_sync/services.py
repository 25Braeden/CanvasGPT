from datetime import timezone as datetime_timezone
from decimal import Decimal, InvalidOperation

import requests
from django.db import DatabaseError, transaction
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


def _optional_id(value, field_name):
    if value is None:
        return None
    return _require_id(value, field_name)


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
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def _get_response(self, url, params=None):
        response = self.session.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response

    def _get_json(self, url, params=None):
        response = self._get_response(url, params)
        try:
            return response, response.json()
        except ValueError:
            raise CanvasSyncError("Canvas returned invalid JSON.") from None

    def get(self, endpoint, params=None):
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        _, data = self._get_json(url, params)
        return data

    def get_paginated(self, endpoint, params=None):
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        page_params = params
        seen_urls = set()
        results = []

        while url:
            if url in seen_urls:
                raise CanvasSyncError("Canvas returned an invalid pagination link.")
            seen_urls.add(url)
            response, page_data = self._get_json(url, page_params)
            results.extend(_require_list(page_data, "paginated response"))
            page_params = None

            links = response.links or {}
            if not isinstance(links, dict):
                raise CanvasSyncError("Canvas returned an invalid pagination link.")
            next_link = links.get("next")
            if next_link is None:
                url = None
            elif isinstance(next_link, dict) and isinstance(next_link.get("url"), str):
                url = next_link["url"]
            else:
                raise CanvasSyncError("Canvas returned an invalid pagination link.")

        return results

    def get_active_courses(self):
        return self.get_paginated(
            "courses",
            params={"enrollment_state": "active", "per_page": 100},
        )

    def get_course_assignments(self, course_id):
        return self.get_paginated(
            f"courses/{course_id}/assignments",
            params={"per_page": 100},
        )

    def _fetch_sync_data(self):
        courses = []
        for course_data in _require_list(self.get_active_courses(), "courses"):
            course_data = _require_object(course_data, "course")
            term_data = course_data.get("term")
            if term_data is None:
                term_name = ""
            else:
                term_name = _optional_text(
                    _require_object(term_data, "course term").get("name"),
                    "course term name",
                )

            course = {
                "id": _require_id(course_data.get("id"), "course"),
                "name": _optional_text(course_data.get("name"), "course name"),
                "course_code": _optional_text(
                    course_data.get("course_code"),
                    "course code",
                ),
                "term": term_name,
                "assignments": [],
            }
            for assignment_data in _require_list(
                self.get_course_assignments(course["id"]),
                "assignments",
            ):
                assignment_data = _require_object(assignment_data, "assignment")
                assignment = {
                    "id": _require_id(assignment_data.get("id"), "assignment"),
                    "title": _optional_text(
                        assignment_data.get("name"),
                        "assignment name",
                    ),
                    "description": _optional_text(
                        assignment_data.get("description"),
                        "assignment description",
                    ),
                    "due_at": _optional_due_at(assignment_data.get("due_at")),
                    "points_possible": _optional_decimal(
                        assignment_data.get("points_possible"),
                        "assignment points",
                    ),
                    "submission_url": _optional_text(
                        assignment_data.get("html_url"),
                        "assignment submission URL",
                    ),
                    "rubric": [],
                }
                rubric_data = assignment_data.get("rubric")
                if rubric_data is None:
                    rubric_data = []
                for criterion_data in _require_list(rubric_data, "rubric"):
                    criterion_data = _require_object(
                        criterion_data,
                        "rubric criterion",
                    )
                    assignment["rubric"].append(
                        {
                            "id": _optional_id(
                                criterion_data.get("id"),
                                "rubric criterion",
                            ),
                            "title": _optional_text(
                                criterion_data.get("description"),
                                "rubric criterion description",
                            ),
                            "description": _optional_text(
                                criterion_data.get("long_description"),
                                "rubric criterion long description",
                            ),
                            "points": _optional_decimal(
                                criterion_data.get("points"),
                                "rubric criterion points",
                            ),
                        }
                    )
                course["assignments"].append(assignment)
            courses.append(course)
        return courses

    def _import_sync_data(self, user, courses_data):
        with transaction.atomic():
            Course.objects.filter(user=user).update(is_active=False)
            for course_data in courses_data:
                course, _ = Course.objects.update_or_create(
                    user=user,
                    canvas_course_id=course_data["id"],
                    defaults={
                        "name": course_data["name"],
                        "course_code": course_data["course_code"],
                        "term": course_data["term"],
                        "is_active": True,
                    },
                )
                seen_assignment_ids = []
                for assignment_data in course_data["assignments"]:
                    assignment, _ = Assignment.objects.update_or_create(
                        course=course,
                        canvas_assignment_id=assignment_data["id"],
                        defaults={
                            "title": assignment_data["title"],
                            "description": assignment_data["description"],
                            "due_at": assignment_data["due_at"],
                            "points_possible": assignment_data["points_possible"],
                            "submission_url": assignment_data["submission_url"],
                            "sync_status": Assignment.SyncStatus.SUCCESS,
                            "sync_error_message": "",
                            "is_active": True,
                        },
                    )
                    seen_assignment_ids.append(assignment.pk)
                    seen_criterion_ids = []
                    for criterion_data in assignment_data["rubric"]:
                        defaults = {
                            "title": criterion_data["title"],
                            "description": criterion_data["description"],
                            "points": criterion_data["points"],
                        }
                        if criterion_data["id"] is not None:
                            criterion, _ = RubricCriterion.objects.update_or_create(
                                assignment=assignment,
                                canvas_rubric_criterion_id=criterion_data["id"],
                                defaults=defaults,
                            )
                        else:
                            criterion = (
                                RubricCriterion.objects.filter(
                                    assignment=assignment,
                                    canvas_rubric_criterion_id__isnull=True,
                                    title=criterion_data["title"],
                                )
                                .order_by("pk")
                                .first()
                            )
                            if criterion is None:
                                criterion = RubricCriterion.objects.create(
                                    assignment=assignment,
                                    **defaults,
                                )
                            else:
                                for field, value in defaults.items():
                                    setattr(criterion, field, value)
                                criterion.save(update_fields=defaults.keys())
                        seen_criterion_ids.append(criterion.pk)
                    RubricCriterion.objects.filter(assignment=assignment).exclude(
                        pk__in=seen_criterion_ids
                    ).delete()
                Assignment.objects.filter(course=course).exclude(
                    pk__in=seen_assignment_ids
                ).update(is_active=False)

    def sync_user_data(self, user):
        try:
            courses_data = self._fetch_sync_data()
            self._import_sync_data(user, courses_data)
            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.SUCCESS,
                sync_error_message="",
                last_synchronized_at=timezone.now(),
            )
        except (requests.RequestException, CanvasSyncError, DatabaseError):
            Assignment.objects.filter(course__user=user).update(
                sync_status=Assignment.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )
            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )
            raise
