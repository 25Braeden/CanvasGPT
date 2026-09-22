from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Assignment, CanvasConnection, Course, RubricCriterion


class CanvasModelTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username='amaan',
            password='testpassword123'
        )

        self.connection = CanvasConnection.objects.create(
            user=self.user,
            canvas_base_url='https://flsouthern.instructure.com',
            access_token='test-token'
        )

        self.course = Course.objects.create(
            user=self.user,
            canvas_course_id=12345,
            name='Software Engineering',
            course_code='CSC 3400',
            term='Fall 2026'
        )

        self.assignment = Assignment.objects.create(
            course=self.course,
            canvas_assignment_id=67890,
            title='Project 1',
            description='Test assignment',
            points_possible=100
        )

        self.criterion = RubricCriterion.objects.create(
            assignment=self.assignment,
            title='Code Quality',
            description='Code should be readable.',
            points=20
        )

    def test_canvas_connection_string(self):
        self.assertEqual(
            str(self.connection),
            "amaan's Canvas connection"
        )

    def test_course_string(self):
        self.assertEqual(str(self.course), 'Software Engineering')

    def test_assignment_string(self):
        self.assertEqual(str(self.assignment), 'Project 1')

    def test_rubric_criterion_string(self):
        self.assertEqual(str(self.criterion), 'Code Quality')

    def test_course_belongs_to_user(self):
        self.assertEqual(self.course.user, self.user)

    def test_assignment_belongs_to_course(self):
        self.assertEqual(self.assignment.course, self.course)

    def test_rubric_belongs_to_assignment(self):
        self.assertEqual(self.criterion.assignment, self.assignment)

    def test_canvas_connection_belongs_to_user(self):
        self.assertEqual(self.connection.user, self.user)