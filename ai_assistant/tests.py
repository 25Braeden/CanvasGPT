from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
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


class ChecklistViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', password='test-pass-123')
        self.other = User.objects.create_user(username='intruder', password='test-pass-123')
        self.course = Course.objects.create(
            user=self.user, canvas_course_id=201, name='Databases'
        )
        self.assignment = Assignment.objects.create(
            course=self.course, canvas_assignment_id=2001, title='ER Diagram'
        )
        other_course = Course.objects.create(
            user=self.other, canvas_course_id=202, name='Networks'
        )
        self.other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=2002, title='Packet Lab'
        )
        self.client.force_login(self.user)
        self.detail_url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])

    def make_task(self, description='Task', order=0, **kwargs):
        kwargs.setdefault('assignment', self.assignment)
        kwargs.setdefault('user', self.user)
        return TaskItem.objects.create(description=description, order=order, **kwargs)

    def order_of(self):
        return list(
            TaskItem.objects.filter(assignment=self.assignment).values_list(
                'description', flat=True
            )
        )

    # Display
    def test_detail_page_lists_tasks_in_order(self):
        self.make_task('Second', order=1)
        self.make_task('First', order=0)
        response = self.client.get(self.detail_url)
        self.assertEqual(
            [t.description for t in response.context['task_items']], ['First', 'Second']
        )
        content = response.content.decode()
        self.assertLess(content.index('First'), content.index('Second'))

    def test_completed_tasks_visible_and_distinct(self):
        self.make_task('Done thing', is_completed=True)
        self.make_task('Open thing', order=1)
        content = self.client.get(self.detail_url).content.decode()
        self.assertIn('Done thing', content)
        self.assertEqual(content.count('task-row completed'), 1)
        self.assertIn('Mark incomplete', content)
        self.assertIn('Mark complete', content)

    def test_detail_hides_other_users_tasks(self):
        self.make_task('Mine')
        TaskItem.objects.create(
            assignment=self.assignment, user=self.other, description='Not mine'
        )
        content = self.client.get(self.detail_url).content.decode()
        self.assertIn('Mine', content)
        self.assertNotIn('Not mine', content)

    # Add
    def test_add_task(self):
        response = self.client.post(
            reverse('ai_assistant:task_add', args=[self.assignment.pk]),
            {'description': '  Write intro  ', 'estimated_minutes': 20},
        )
        self.assertRedirects(response, self.detail_url)
        task = TaskItem.objects.get()
        self.assertEqual(task.description, 'Write intro')
        self.assertEqual(task.estimated_minutes, 20)
        self.assertEqual(task.user, self.user)
        self.assertFalse(task.ai_generated)

    def test_add_appends_to_end(self):
        self.make_task('A', order=0)
        self.make_task('B', order=5)
        self.client.post(
            reverse('ai_assistant:task_add', args=[self.assignment.pk]),
            {'description': 'C', 'estimated_minutes': 10},
        )
        self.assertEqual(self.order_of(), ['A', 'B', 'C'])

    def test_add_validation_errors(self):
        url = reverse('ai_assistant:task_add', args=[self.assignment.pk])
        for data in (
            {'description': '', 'estimated_minutes': 10},
            {'description': '   ', 'estimated_minutes': 10},
            {'description': 'x', 'estimated_minutes': 0},
            {'description': 'x', 'estimated_minutes': -5},
            {'description': 'x', 'estimated_minutes': ''},
            {'description': 'x' * 501, 'estimated_minutes': 10},
        ):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 400, data)
            self.assertTrue(response.context['task_form'].errors, data)
        self.assertEqual(TaskItem.objects.count(), 0)

    def test_add_to_other_users_assignment_rejected(self):
        response = self.client.post(
            reverse('ai_assistant:task_add', args=[self.other_assignment.pk]),
            {'description': 'Sneaky', 'estimated_minutes': 10},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(TaskItem.objects.count(), 0)

    # Edit
    def test_edit_task(self):
        task = self.make_task('Old')
        url = reverse('ai_assistant:task_edit', args=[task.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'description': 'New', 'estimated_minutes': 90})
        self.assertRedirects(response, self.detail_url)
        task.refresh_from_db()
        self.assertEqual((task.description, task.estimated_minutes), ('New', 90))

    def test_edit_validation_errors(self):
        task = self.make_task('Keep')
        response = self.client.post(
            reverse('ai_assistant:task_edit', args=[task.pk]),
            {'description': '', 'estimated_minutes': 0},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('description', response.context['form'].errors)
        self.assertIn('estimated_minutes', response.context['form'].errors)
        task.refresh_from_db()
        self.assertEqual(task.description, 'Keep')

    # Delete
    def test_delete_task(self):
        task = self.make_task()
        response = self.client.post(reverse('ai_assistant:task_delete', args=[task.pk]))
        self.assertRedirects(response, self.detail_url)
        self.assertFalse(TaskItem.objects.exists())

    def test_delete_requires_post(self):
        task = self.make_task()
        response = self.client.get(reverse('ai_assistant:task_delete', args=[task.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(TaskItem.objects.exists())

    # Complete / incomplete
    def test_toggle_completion(self):
        task = self.make_task()
        url = reverse('ai_assistant:task_toggle', args=[task.pk])
        self.client.post(url)
        task.refresh_from_db()
        self.assertTrue(task.is_completed)
        self.client.post(url)
        task.refresh_from_db()
        self.assertFalse(task.is_completed)

    # Reorder
    def test_move_up_and_down(self):
        a = self.make_task('A', order=0)
        b = self.make_task('B', order=1)
        c = self.make_task('C', order=2)
        self.client.post(reverse('ai_assistant:task_move', args=[c.pk, 'up']))
        self.assertEqual(self.order_of(), ['A', 'C', 'B'])
        self.client.post(reverse('ai_assistant:task_move', args=[a.pk, 'down']))
        self.assertEqual(self.order_of(), ['C', 'A', 'B'])

    def test_move_at_edges_is_noop(self):
        a = self.make_task('A', order=0)
        b = self.make_task('B', order=1)
        self.client.post(reverse('ai_assistant:task_move', args=[a.pk, 'up']))
        self.client.post(reverse('ai_assistant:task_move', args=[b.pk, 'down']))
        self.assertEqual(self.order_of(), ['A', 'B'])

    def test_move_handles_duplicate_orders(self):
        self.make_task('A', order=0)
        b = self.make_task('B', order=0)
        self.client.post(reverse('ai_assistant:task_move', args=[b.pk, 'up']))
        self.assertEqual(self.order_of(), ['B', 'A'])

    def test_move_invalid_direction_is_noop(self):
        task = self.make_task()
        response = self.client.post(
            reverse('ai_assistant:task_move', args=[task.pk, 'sideways'])
        )
        self.assertRedirects(response, self.detail_url)

    # Ownership and authentication
    def test_other_users_task_actions_rejected(self):
        task = self.make_task('Mine', order=0)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse('ai_assistant:task_edit', args=[task.pk])).status_code, 404
        )
        for name, args, data in (
            ('task_edit', [task.pk], {'description': 'Hacked', 'estimated_minutes': 1}),
            ('task_delete', [task.pk], {}),
            ('task_toggle', [task.pk], {}),
            ('task_move', [task.pk, 'down'], {}),
        ):
            response = self.client.post(reverse(f'ai_assistant:{name}', args=args), data)
            self.assertEqual(response.status_code, 404, name)
        task.refresh_from_db()
        self.assertEqual(task.description, 'Mine')
        self.assertFalse(task.is_completed)

    def test_task_on_foreign_assignment_rejected(self):
        # A task whose user is the requester but sits on someone else's assignment.
        task = TaskItem.objects.create(
            assignment=self.other_assignment, user=self.user, description='Odd'
        )
        response = self.client.post(reverse('ai_assistant:task_toggle', args=[task.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_redirected_to_login(self):
        task = self.make_task()
        self.client.logout()
        for name, args in (
            ('task_add', [self.assignment.pk]),
            ('task_edit', [task.pk]),
            ('task_delete', [task.pk]),
            ('task_toggle', [task.pk]),
            ('task_move', [task.pk, 'up']),
        ):
            response = self.client.post(reverse(f'ai_assistant:{name}', args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn('/accounts/login/', response['Location'])
        self.assertTrue(TaskItem.objects.filter(pk=task.pk).exists())
