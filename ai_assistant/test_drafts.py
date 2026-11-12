"""Draft lifecycle tests use demo responses or injected provider mocks only."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, Course

from .drafts import current_suggestion_draft, generate_suggestion_draft
from .models import AIRequest, SuggestionDraft, TaskItem
from .services import GenerationFailure, SuggestionResult, TaskSuggestion


@override_settings(AI_SUGGESTIONS_MODE='demo', OPENAI_API_KEY='')
class SuggestionDraftTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='draft-owner')
        cls.other = User.objects.create_user(username='draft-other')
        cls.course = Course.objects.create(user=cls.user, canvas_course_id=801, name='Course')
        cls.assignment = Assignment.objects.create(
            course=cls.course, canvas_assignment_id=8001, title='Essay', description='Write an essay.',
        )
        cls.second_assignment = Assignment.objects.create(
            course=cls.course, canvas_assignment_id=8002, title='Second', description='Research.',
        )
        other_course = Course.objects.create(user=cls.other, canvas_course_id=802, name='Other')
        cls.other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=8003, title='Other', description='Private.',
        )
        TaskItem.objects.create(
            assignment=cls.assignment, user=cls.user, description='Keep completed work',
            is_completed=True, order=5, estimated_minutes=40,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])
        self.generate_url = reverse('ai_assistant:suggestions_generate', args=[self.assignment.pk])
        self.original_tasks = list(TaskItem.objects.values())
        guard = patch('ai_assistant.services.OpenAI', side_effect=AssertionError('Live API forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.assertEqual(list(TaskItem.objects.values()), self.original_tasks)

    def generate(self, **kwargs):
        return generate_suggestion_draft(**{'assignment': self.assignment, 'user': self.user, **kwargs})

    def make_draft(self, **kwargs):
        return SuggestionDraft.objects.create(**{
            'assignment': self.assignment, 'user': self.user,
            'suggestions': [{'description': 'Outline', 'estimated_minutes': 30}],
            'generation_mode': 'demo', 'model_name': 'demo-task-suggestions', **kwargs,
        })

    def test_generation_saves_validated_content_and_metadata_only(self):
        before = timezone.now()
        draft, result = self.generate()
        self.assertTrue(result.success)
        self.assertEqual(draft.assignment, self.assignment)
        self.assertEqual(draft.user, self.user)
        self.assertEqual(draft.status, SuggestionDraft.Status.PENDING)
        self.assertEqual(draft.generation_mode, 'demo')
        self.assertEqual(draft.model_name, 'demo-task-suggestions')
        self.assertGreaterEqual(draft.created_at, before)
        self.assertAlmostEqual((draft.expires_at - draft.created_at).total_seconds(), 86400, delta=2)
        self.assertEqual(draft.validated_suggestions, result.suggestions)
        self.assertEqual(draft.selected_indices, list(range(len(result.suggestions))))
        self.assertEqual(draft.revision, 1)
        self.assertEqual(set(draft.suggestions[0]), {'description', 'estimated_minutes'})
        self.assertNotIn('Write an essay.', str(draft.suggestions))
        self.assertEqual(AIRequest.objects.count(), 1)
        self.assertFalse(any(field.name in {'prompt', 'response', 'suggestions'} for field in AIRequest._meta.fields))

    def test_successful_regeneration_supersedes_only_the_previous_pending_draft(self):
        first, _ = self.generate()
        unrelated = self.make_draft(assignment=self.second_assignment)
        second, result = self.generate()
        first.refresh_from_db()
        unrelated.refresh_from_db()
        self.assertTrue(result.success)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.status, SuggestionDraft.Status.SUPERSEDED)
        self.assertEqual(second.status, SuggestionDraft.Status.PENDING)
        self.assertEqual(unrelated.status, SuggestionDraft.Status.PENDING)
        self.assertEqual(current_suggestion_draft(assignment=self.assignment, user=self.user), second)

    def test_generation_failure_preserves_existing_draft(self):
        original = self.make_draft()
        for failure in (GenerationFailure.TIMEOUT, GenerationFailure.API_ERROR, GenerationFailure.INVALID_OUTPUT):
            with self.subTest(failure=failure), patch(
                'ai_assistant.drafts.generate_task_suggestions', return_value=SuggestionResult(failure=failure),
            ):
                draft, result = self.generate()
                self.assertIsNone(draft)
                self.assertEqual(result.failure, failure)
                original.refresh_from_db()
                self.assertEqual(original.status, SuggestionDraft.Status.PENDING)
                self.assertEqual(SuggestionDraft.objects.count(), 1)

    def test_storage_failure_rolls_back_replacement(self):
        original = self.make_draft()
        with patch('ai_assistant.drafts.SuggestionDraft.objects.create', side_effect=DatabaseError('private')):
            draft, result = self.generate()
        self.assertIsNone(draft)
        self.assertEqual(result.failure, GenerationFailure.DRAFT_ERROR)
        original.refresh_from_db()
        self.assertEqual(original.status, SuggestionDraft.Status.PENDING)
        self.assertEqual(SuggestionDraft.objects.count(), 1)

    def test_invalid_provider_result_cannot_be_persisted_or_replace_existing_draft(self):
        original = self.make_draft()
        with patch('ai_assistant.drafts.generate_task_suggestions', return_value=SuggestionResult(
            suggestions=(TaskSuggestion('Bad estimate', 0),),
        )):
            draft, result = self.generate()
        self.assertIsNone(draft)
        self.assertEqual(result.failure, GenerationFailure.DRAFT_ERROR)
        original.refresh_from_db()
        self.assertEqual(original.status, SuggestionDraft.Status.PENDING)

    def test_model_rejects_invalid_payloads_and_normalizes_descriptions(self):
        for suggestions in ([], {}, None, [{'description': 'x', 'estimated_minutes': True}],
                            [{'description': '', 'estimated_minutes': 20}],
                            [{'description': 'x' * 501, 'estimated_minutes': 20}],
                            [{'description': 'x', 'estimated_minutes': 481}]):
            with self.subTest(suggestions=suggestions), self.assertRaises(ValidationError):
                self.make_draft(suggestions=suggestions)
        draft = self.make_draft(suggestions=[{'description': '  Outline  ', 'estimated_minutes': 30}])
        self.assertEqual(draft.suggestions[0]['description'], 'Outline')

    def test_model_rejects_foreign_assignment(self):
        with self.assertRaises(ValidationError):
            self.make_draft(assignment=self.other_assignment)

    def test_database_allows_only_one_pending_draft_per_assignment_and_student(self):
        self.make_draft()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SuggestionDraft.objects.bulk_create([SuggestionDraft(
                assignment=self.assignment, user=self.user, suggestions=[],
                generation_mode='demo', model_name='demo-task-suggestions',
            )])

    def test_database_rejects_nonpositive_lifetime(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SuggestionDraft.objects.bulk_create([SuggestionDraft(
                assignment=self.assignment, user=self.user, suggestions=[],
                generation_mode='demo', model_name='demo-task-suggestions',
                created_at=now, expires_at=now,
            )])

    def test_expired_draft_is_hidden_and_can_be_replaced(self):
        now = timezone.now()
        expired = self.make_draft(created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1))
        self.assertIsNone(current_suggestion_draft(assignment=self.assignment, user=self.user))
        self.assertNotContains(self.client.get(self.url), 'Draft saved until')
        replacement, result = self.generate()
        self.assertTrue(result.success)
        expired.refresh_from_db()
        self.assertEqual(expired.status, SuggestionDraft.Status.SUPERSEDED)
        self.assertEqual(current_suggestion_draft(assignment=self.assignment, user=self.user), replacement)

    def test_terminal_statuses_are_not_shown(self):
        for status in ('accepted', 'discarded', 'superseded'):
            with self.subTest(status=status):
                draft = self.make_draft(status=status)
                self.assertIsNone(current_suggestion_draft(assignment=self.assignment, user=self.user))
                self.assertNotContains(self.client.get(self.url), 'Draft saved until')
                draft.delete()

    def test_corrupted_payload_is_not_shown(self):
        draft = self.make_draft()
        SuggestionDraft.objects.filter(pk=draft.pk).update(suggestions=[{'description': 'broken'}])
        self.assertIsNone(current_suggestion_draft(assignment=self.assignment, user=self.user))
        self.assertNotContains(self.client.get(self.url), 'Draft saved until')

    def test_ownership_is_checked_on_generate_and_load(self):
        draft = self.make_draft()
        self.assertIsNone(current_suggestion_draft(assignment=self.assignment, user=self.other))
        for user in (self.other, AnonymousUser()):
            generated, result = self.generate(user=user)
            self.assertIsNone(generated)
            self.assertEqual(result.failure, GenerationFailure.FORBIDDEN)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        draft.refresh_from_db()
        self.assertEqual(draft.status, SuggestionDraft.Status.PENDING)
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_failed_regeneration_displays_existing_saved_draft_alongside_error(self):
        self.make_draft()
        with patch('ai_assistant.drafts.generate_task_suggestions', return_value=SuggestionResult(
            failure=GenerationFailure.TIMEOUT,
        )):
            response = self.client.post(self.generate_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        html = response.json()['html']
        self.assertIn('role="alert"', html)
        self.assertIn('Outline', html)
        self.assertIn('Draft saved until', html)

    @override_settings(AI_SUGGESTIONS_MODE='openai', OPENAI_MODEL='test-model')
    def test_real_provider_mode_reuses_the_same_persistence_path_with_mocked_generation(self):
        result = SuggestionResult(suggestions=(TaskSuggestion('Tailored task', 20),))
        with patch('ai_assistant.drafts.generate_task_suggestions', return_value=result) as generate:
            draft, returned = self.generate()
        generate.assert_called_once_with(assignment=self.assignment, user=self.user, demo=False)
        self.assertEqual(returned, result)
        self.assertEqual(draft.generation_mode, 'openai')
        self.assertEqual(draft.model_name, 'test-model')
        response = self.client.get(self.url)
        self.assertContains(response, 'Task suggestion preview')
        self.assertContains(response, 'Generate task suggestions')
        self.assertNotContains(response, 'fixed example suggestions')

    @override_settings(AI_SUGGESTIONS_MODE='openai', OPENAI_MODEL='gpt-4o-mini', OPENAI_TIMEOUT_SECONDS='30')
    def test_openai_mode_without_key_does_not_fall_back_to_demo(self):
        draft, result = self.generate()
        self.assertIsNone(draft)
        self.assertEqual(result.failure, GenerationFailure.UNAVAILABLE)
        self.assertEqual(SuggestionDraft.objects.count(), 0)
        self.assertFalse(AIRequest.objects.get().success)

    def test_switching_mode_does_not_relabel_saved_demo_as_real_generation(self):
        self.make_draft()
        with override_settings(AI_SUGGESTIONS_MODE='openai'):
            response = self.client.get(self.url)
        self.assertContains(response, 'Generate task suggestions')
        self.assertContains(response, 'Demo suggestion preview')
        self.assertContains(response, 'fixed demo examples')
        self.assertEqual(AIRequest.objects.count(), 0)

    def test_invalid_mode_is_safe_and_does_not_call_any_provider(self):
        original = self.make_draft()
        for mode in ('invalid', '', None):
            with self.subTest(mode=mode), override_settings(AI_SUGGESTIONS_MODE=mode), patch(
                'ai_assistant.drafts.generate_task_suggestions',
            ) as generate:
                draft, result = self.generate()
                self.assertIsNone(draft)
                self.assertEqual(result.failure, GenerationFailure.UNAVAILABLE)
                generate.assert_not_called()
        original.refresh_from_db()
        self.assertEqual(original.status, SuggestionDraft.Status.PENDING)

    def test_purge_removes_only_expired_draft_content_and_keeps_audits(self):
        active, _ = self.generate()
        now = timezone.now()
        self.make_draft(
            assignment=self.second_assignment,
            created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1),
        )
        output = StringIO()
        call_command('purge_expired_suggestion_drafts', stdout=output)
        self.assertIn('Deleted 1 expired suggestion drafts.', output.getvalue())
        self.assertEqual(list(SuggestionDraft.objects.values_list('pk', flat=True)), [active.pk])
        self.assertEqual(AIRequest.objects.count(), 1)
