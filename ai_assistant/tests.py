from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from canvas_sync.models import Assignment, Course

from .models import AIRequest, TaskItem

User = get_user_model()


class TaskItemModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='braeden', password='test-pass-123'
        )
        self.course = Course.objects.create(
            user=self.user, canvas_course_id=101, name='Software Engineering'
        )
        self.assignment = Assignment.objects.create(
            course=self.course, canvas_assignment_id=1001, title='Project Proposal'
        )

    def create_task(self, **kwargs):
        defaults = {
            'assignment': self.assignment,
            'user': self.user,
            'description': 'Draft outline',
            'estimated_minutes': 45,
            'order': 1,
        }
        defaults.update(kwargs)
        return TaskItem.objects.create(**defaults)

    def test_task_item_creation_with_proposal_defaults(self):
        task = self.create_task()
        self.assertEqual(task.description, 'Draft outline')
        self.assertEqual(task.estimated_minutes, 45)
        self.assertEqual(task.order, 1)
        self.assertFalse(task.is_completed)
        self.assertTrue(task.ai_generated)

    def test_manual_task_is_not_flagged_as_ai_generated(self):
        task = self.create_task(ai_generated=False)
        self.assertFalse(task.ai_generated)

    def test_default_estimate_and_order(self):
        task = TaskItem.objects.create(
            assignment=self.assignment,
            user=self.user,
            description='Quick review',
        )
        self.assertEqual(task.estimated_minutes, 30)
        self.assertEqual(task.order, 0)

    def test_checklist_orders_by_order_field(self):
        self.create_task(description='Third', order=3)
        self.create_task(description='First', order=1)
        self.create_task(description='Second', order=2)
        descriptions = list(TaskItem.objects.values_list('description', flat=True))
        self.assertEqual(descriptions, ['First', 'Second', 'Third'])

    def test_assignment_delete_cascades_to_task_items(self):
        self.create_task()
        self.assertEqual(TaskItem.objects.count(), 1)
        self.assignment.delete()
        self.assertEqual(TaskItem.objects.count(), 0)

    def test_user_delete_cascades_to_task_items(self):
        self.create_task()
        self.user.delete()
        self.assertEqual(TaskItem.objects.count(), 0)

    def test_task_item_str(self):
        task = self.create_task()
        self.assertEqual(str(task), 'Draft outline (Project Proposal)')


class AIRequestModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='braeden', password='test-pass-123'
        )

    def test_ai_request_creation_and_timestamp(self):
        before = timezone.now()
        request = AIRequest.objects.create(
            user=self.user,
            request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
            model_name='gpt-4o-mini',
            success=True,
        )
        self.assertTrue(request.success)
        self.assertEqual(request.model_name, 'gpt-4o-mini')
        self.assertGreaterEqual(request.requested_at, before)
        self.assertIsNotNone(request.pk)

    def test_ai_request_success_defaults_to_false(self):
        request = AIRequest.objects.create(
            user=self.user,
            request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
            model_name='gpt-4o-mini',
        )
        self.assertFalse(request.success)

    def test_invalid_request_type_rejected(self):
        request = AIRequest(
            user=self.user,
            request_type='not_a_real_type',
            model_name='gpt-4o-mini',
        )
        with self.assertRaises(ValidationError):
            request.full_clean()

    def test_user_delete_cascades_to_ai_requests(self):
        AIRequest.objects.create(
            user=self.user,
            request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
            model_name='gpt-4o-mini',
        )
        self.user.delete()
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_latest_requests_listed_first(self):
        first = AIRequest.objects.create(
            user=self.user,
            request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
            model_name='gpt-4o-mini',
        )
        second = AIRequest.objects.create(
            user=self.user,
            request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
            model_name='gpt-4o-mini',
        )
        self.assertEqual(list(AIRequest.objects.all()), [second, first])
