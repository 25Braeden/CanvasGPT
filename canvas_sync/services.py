import requests

from .models import Assignment, Course, RubricCriterion

class CanvasAPIClient:
    def __init__(self, base_url, access_token):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()

        self.session.headers.update({
            "Authorization": f"Bearer {access_token}"
        })

    def get(self, endpoint, params=None):
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"

        response = self.session.get(
            url,
            params=params,
            timeout=15
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

            assignments_data = self.get_course_assignments(course.canvas_course_id)

            for assignment_data in assignments_data:
                assignment, _ = Assignment.objects.update_or_create(
                    course=course,
                    canvas_assignment_id=assignment_data["id"],
                    defaults={
                        "title": assignment_data.get("name", ""),
                        "description": assignment_data.get("description") or "",
                        "due_at": assignment_data.get("due_at"),
                        "points_possible": assignment_data.get("points_possible"),
                        "submission_url": assignment_data.get("html_url", ""),
                    },
                )

                for criterion_data in assignment_data.get("rubric", []):
                    RubricCriterion.objects.update_or_create(
                        assignment=assignment,
                        title=criterion_data.get("description", ""),
                        defaults={
                            "description": criterion_data.get("long_description") or "",
                            "points": criterion_data.get("points"),
                        },
                    )