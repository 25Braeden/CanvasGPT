"""Browser integration tests use only the offline demo or mocked results."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, Course, RubricCriterion
from planner.models import PlanSession, StudyPlan

from .demo import DEMO_MODEL_NAME
from .models import AIRequest, SuggestionDraft, TaskItem
from .services import GenerationFailure, SuggestionResult, TaskSuggestion


@override_settings(AI_SUGGESTIONS_MODE='demo', OPENAI_API_KEY='', OPENAI_MODEL='', OPENAI_TIMEOUT_SECONDS='invalid')
class DemoSuggestionViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='demo-owner')
        cls.other = User.objects.create_user(username='demo-other')
        course = Course.objects.create(user=cls.user, canvas_course_id=501, name='Demo')
        cls.assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=5001, title='Essay', description='Write an essay.',
        )
        other_course = Course.objects.create(user=cls.other, canvas_course_id=502, name='Other')
        cls.other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=5002, title='Not yours', description='Private',
        )
        cls.task = TaskItem.objects.create(
            assignment=cls.assignment, user=cls.user, description='Existing completed work',
            is_completed=True, estimated_minutes=25, order=4, ai_generated=False,
        )
        now = timezone.now()
        plan = StudyPlan.objects.create(user=cls.user, start_date=now.date(), end_date=now.date())
        PlanSession.objects.create(
            study_plan=plan, task_item=cls.task, scheduled_start=now,
            scheduled_end=now + timedelta(minutes=25), is_completed=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('ai_assistant:suggestions_generate', args=[self.assignment.pk])
        self.detail_url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])
        self.tasks_before = list(TaskItem.objects.order_by('pk').values())
        self.sessions_before = list(PlanSession.objects.order_by('pk').values())
        self.plans_before = list(StudyPlan.objects.order_by('pk').values())
        guard = patch('ai_assistant.services.OpenAI', side_effect=AssertionError('Live API forbidden'))
        self.sdk = guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.assertEqual(list(TaskItem.objects.order_by('pk').values()), self.tasks_before)
        self.assertEqual(list(PlanSession.objects.order_by('pk').values()), self.sessions_before)
        self.assertEqual(list(StudyPlan.objects.order_by('pk').values()), self.plans_before)
        self.sdk.assert_not_called()

    def test_assignment_page_has_labeled_demo_button_and_manual_form(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'Generate demo suggestions')
        self.assertContains(response, 'fixed example suggestions')
        self.assertContains(response, 'No API key is needed')
        self.assertContains(response, self.url)
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'data-suggestion-generation')
        self.assertContains(response, f'data-scroll-page="{self.url}"')
        self.assertContains(response, 'ai_assistant/suggestions.js')
        self.assertContains(response, 'Add task')
        self.assertNotContains(response, 'Demo suggestion preview')
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_demo_post_previews_suggestions_without_api_key_or_model(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['suggestion_result'].success)
        self.assertEqual(response.context['assignment'], self.assignment)
        self.assertContains(response, 'Demo suggestion preview')
        self.assertContains(response, f'data-scroll-page="{self.url}"')
        self.assertContains(response, 'accounts/preserve-scroll.js')
        self.assertContains(response, f'data-scroll-page="{self.detail_url}"', count=5)
        self.assertContains(response, 'Draft an outline or plan for the assignment.')
        self.assertContains(response, '30 min')
        self.assertContains(response, 'These suggestions are not in your checklist.')
        self.assertContains(response, 'Existing completed work')
        self.assertContains(response, 'task-row completed')
        self.assertContains(response, 'Add task')
        audit = AIRequest.objects.get()
        self.assertEqual(audit.model_name, DEMO_MODEL_NAME)
        self.assertEqual(audit.user, self.user)
        self.assertTrue(audit.success)

    def test_demo_with_rubric(self):
        RubricCriterion.objects.create(assignment=self.assignment, title='Evidence', description='Use sources')
        response = self.client.post(self.url)
        self.assertTrue(response.context['suggestion_result'].success)
        self.assertContains(response, 'Evidence')

    def test_draft_persists_on_assignment_get_without_generating_again(self):
        self.client.post(self.url)
        with patch('ai_assistant.drafts.generate_task_suggestions') as generate:
            response = self.client.get(self.detail_url)
            generate.assert_not_called()
        self.assertContains(response, 'Demo suggestion preview')
        self.assertContains(response, 'Draft saved until')
        self.assertEqual(SuggestionDraft.objects.get().status, SuggestionDraft.Status.PENDING)
        self.assertEqual(AIRequest.objects.count(), 1)

    def test_empty_source_has_safe_fallback_and_manual_creation(self):
        self.assignment.description = ''
        self.assignment.save(update_fields=['description'])
        response = self.client.post(self.url)
        self.assertEqual(response.context['suggestion_result'].failure, GenerationFailure.INVALID_INPUT)
        self.assertContains(response, 'You can still add checklist tasks manually.')
        self.assertContains(response, f'data-scroll-page="{self.url}"')
        self.assertContains(response, 'accounts/preserve-scroll.js')
        self.assertContains(response, 'Add task')
        self.assertContains(response, 'Existing completed work')
        self.assertNotContains(response, 'Demo suggestion preview')
        self.assertFalse(AIRequest.objects.get().success)

    def test_mocked_service_failures_render_safe_fallback(self):
        for failure in (
            GenerationFailure.TIMEOUT, GenerationFailure.API_ERROR,
            GenerationFailure.INVALID_OUTPUT, GenerationFailure.AUDIT_ERROR,
        ):
            with self.subTest(failure=failure), patch(
                'ai_assistant.drafts.generate_task_suggestions',
                return_value=SuggestionResult(failure=failure),
            ) as generate:
                response = self.client.post(self.url)
                generate.assert_called_once_with(assignment=self.assignment, user=self.user, demo=True)
                self.assertContains(response, 'You can still add checklist tasks manually.')
                self.assertContains(response, 'role="alert"')
                self.assertContains(response, 'Add task')
                self.assertNotContains(response, 'Demo suggestion preview')

    def test_suggestion_text_is_escaped(self):
        result = SuggestionResult(suggestions=(TaskSuggestion('<script>alert("x")</script>', 10),))
        with patch('ai_assistant.drafts.generate_task_suggestions', return_value=result):
            response = self.client.post(self.url)
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(')

    def test_get_is_not_allowed_and_does_not_audit(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_other_users_assignment_is_not_generated(self):
        url = reverse('ai_assistant:suggestions_generate', args=[self.other_assignment.pk])
        with patch('ai_assistant.drafts.generate_task_suggestions') as generate:
            self.assertEqual(self.client.post(url).status_code, 404)
            generate.assert_not_called()
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertEqual(AIRequest.objects.count(), 0)
        client.get(self.detail_url)
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.url, {'csrfmiddlewaretoken': token}).status_code, 200)
        self.assertTrue(AIRequest.objects.get().success)

    def test_ajax_returns_only_preview_markup(self):
        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        html = response.json()['html']
        self.assertIn('Demo suggestion preview', html)
        self.assertNotIn('<html', html)
        self.assertNotIn('Existing completed work', html)
        self.assertNotIn('<form', html)
        self.assertEqual(AIRequest.objects.count(), 1)
        self.assertTrue(AIRequest.objects.get().success)

    def test_ajax_safe_failure_is_a_preview_fragment(self):
        self.assignment.description = ''
        self.assignment.save(update_fields=['description'])
        response = self.client.post(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertIn('role="alert"', response.json()['html'])
        self.assertIn('manually', response.json()['html'])
        self.assertFalse(AIRequest.objects.get().success)

    def test_ajax_escapes_suggestion_text(self):
        result = SuggestionResult(suggestions=(TaskSuggestion('<script>alert("x")</script>', 10),))
        with patch('ai_assistant.drafts.generate_task_suggestions', return_value=result):
            response = self.client.post(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertIn('&lt;script&gt;', response.json()['html'])
        self.assertNotIn('<script>', response.json()['html'])

    def test_ajax_requires_csrf_and_ownership(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 403)
        other_url = reverse('ai_assistant:suggestions_generate', args=[self.other_assignment.pk])
        self.assertEqual(self.client.post(other_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 404)
        self.assertEqual(AIRequest.objects.count(), 0)

    @override_settings(OPENAI_API_KEY='fake-key-never-use', OPENAI_MODEL='gpt-4o-mini')
    def test_form_cannot_switch_demo_to_live_generation(self):
        response = self.client.post(self.url, {'demo': 'false', 'model': 'live-model'})
        self.assertTrue(response.context['suggestion_result'].success)
        self.assertEqual(AIRequest.objects.get().model_name, DEMO_MODEL_NAME)
