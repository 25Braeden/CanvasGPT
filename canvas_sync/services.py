import requests
from django.utils import timezone

from .models import Assignment, CanvasConnection, Course, RubricCriterion


SYNC_FAILURE_MESSAGE = "Canvas sync failed. Check your Canvas connection."


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
        return response.json()

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
            courses_data = self.get_active_courses()

            for course_data in courses_data:
                course, _ = Course.objects.update_or_create(
                    user=user,
                    canvas_course_id=course_data["id"],
                    defaults={
                        "name": course_data.get("name", ""),
                        "course_code": course_data.get("course_code", ""),
                        "term": course_data.get("term", {}).get("name", ""),
                        "is_active": True,
                    },
                )

                assignments_data = self.get_course_assignments(
                    course.canvas_course_id
                )

                for assignment_data in assignments_data:
                    assignment, _ = Assignment.objects.update_or_create(
                        course=course,
                        canvas_assignment_id=assignment_data["id"],
                        defaults={
                            "title": assignment_data.get("name", ""),
                            "description": (
                                assignment_data.get("description") or ""
                            ),
                            "due_at": assignment_data.get("due_at"),
                            "points_possible": assignment_data.get(
                                "points_possible"
                            ),
                            "submission_url": assignment_data.get(
                                "html_url",
                                "",
                            ),
                            "sync_status": Assignment.SyncStatus.SUCCESS,
                            "sync_error_message": "",
                        },
                    )

                    for criterion_data in assignment_data.get("rubric", []):
                        RubricCriterion.objects.update_or_create(
                            assignment=assignment,
                            title=criterion_data.get(
                                "description",
                                "",
                            ),
                            defaults={
                                "description": (
                                    criterion_data.get(
                                        "long_description"
                                    )
                                    or ""
                                ),
                                "points": criterion_data.get("points"),
                            },
                        )

            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.SUCCESS,
                sync_error_message="",
                last_synchronized_at=timezone.now(),
            )

        except requests.RequestException:
            Assignment.objects.filter(
                course__user=user
            ).update(
                sync_status=Assignment.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )
            CanvasConnection.objects.filter(user=user).update(
                sync_status=CanvasConnection.SyncStatus.FAILED,
                sync_error_message=SYNC_FAILURE_MESSAGE,
            )

            raise