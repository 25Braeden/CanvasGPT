"""Acceptance appends selected tasks atomically without provider calls."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, Course
from planner.models import PlanSession, StudyPlan

from .acceptance import accept_suggestion_draft
from .models import AIRequest, SuggestionDraft, TaskItem


@override_settings(AI_SUGGESTIONS_MODE='demo', GEMINI_API_KEY='')
class SuggestionAcceptanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='accept-owner')
        cls.other = User.objects.create_user(username='accept-other')
        course = Course.objects.create(user=cls.user, canvas_course_id=951, name='Course')
        cls.assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=9501, title='Essay', description='Write an essay.',
        )
        cls.second_assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=9502, title='Second', description='Research.',
        )
        cls.draft = SuggestionDraft.objects.create(
            user=cls.user, assignment=cls.assignment,
            suggestions=[
                {'description': 'Outline', 'estimated_minutes': 30},
                {'description': 'Draft', 'estimated_minutes': 60},
                {'description': 'Review', 'estimated_minutes': 15},
            ], selected_indices=[0, 2], generation_mode='demo', model_name='demo-task-suggestions',
        )
        cls.completed = TaskItem.objects.create(
            user=cls.user, assignment=cls.assignment, description='Completed work',
            is_completed=True, order=0, estimated_minutes=40,
        )
        TaskItem.objects.create(user=cls.user, assignment=cls.assignment, description='Manual work', order=5, ai_generated=False)
        TaskItem.objects.create(user=cls.user, assignment=cls.second_assignment, description='Other assignment work', order=100)
        other_course = Course.objects.create(user=cls.other, canvas_course_id=952, name='Other')
        cls.other_assignment = Assignment.objects.create(course=other_course, canvas_assignment_id=9503, title='Other')
        TaskItem.objects.create(user=cls.other, assignment=cls.other_assignment, description='Other user work', order=999)
        now = timezone.now()
        plan = StudyPlan.objects.create(user=cls.user, start_date=now.date(), end_date=now.date())
        PlanSession.objects.create(
            study_plan=plan, task_item=cls.completed, scheduled_start=now,
            scheduled_end=now + timedelta(minutes=40), is_completed=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('ai_assistant:suggestions_accept', args=[self.draft.pk])
        self.review_url = reverse('ai_assistant:suggestions_review', args=[self.draft.pk])
        self.assignment_url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])
        self.original_tasks = list(TaskItem.objects.order_by('pk').values())
        self.original_ids = [task['id'] for task in self.original_tasks]
        self.original_plans = list(StudyPlan.objects.values())
        self.original_sessions = list(PlanSession.objects.values())
        self.original_audits = list(AIRequest.objects.values())
        for target in ('ai_assistant.gemini.requests.post', 'ai_assistant.drafts.generate_task_suggestions'):
            guard = patch(target, side_effect=AssertionError('Acceptance must not call generation'))
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self):
        self.assertEqual(list(TaskItem.objects.filter(pk__in=self.original_ids).order_by('pk').values()), self.original_tasks)
        self.assertEqual(list(StudyPlan.objects.values()), self.original_plans)
        self.assertEqual(list(PlanSession.objects.values()), self.original_sessions)
        self.assertEqual(list(AIRequest.objects.values()), self.original_audits)

    def post_data(self, **overrides):
        return {
            'revision': '1', 'suggestions-TOTAL_FORMS': '3', 'suggestions-INITIAL_FORMS': '3',
            'suggestions-0-description': '  Edited outline  ', 'suggestions-0-estimated_minutes': '25',
            'suggestions-0-selected': 'on',
            'suggestions-1-description': 'Edited draft', 'suggestions-1-estimated_minutes': '60',
            'suggestions-2-description': 'Edited review', 'suggestions-2-estimated_minutes': '20',
            'suggestions-2-selected': 'on', **overrides,
        }

    def new_tasks(self):
        return TaskItem.objects.exclude(pk__in=self.original_ids).order_by('order', 'pk')

    def assert_no_acceptance(self):
        self.assertEqual(self.new_tasks().count(), 0)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'pending')
        self.assertEqual(self.draft.revision, 1)
        self.assertEqual(self.draft.suggestions[0]['description'], 'Outline')

    def test_accept_current_edits_and_selected_tasks_only(self):
        expires_at = self.draft.expires_at
        response = self.client.post(self.url, self.post_data(), follow=True)
        self.assertRedirects(response, self.assignment_url)
        self.assertContains(response, 'Added 2 task(s) to your checklist.')
        self.assertContains(response, 'Your study plan was not changed.')
        tasks = list(self.new_tasks())
        self.assertEqual([task.description for task in tasks], ['Edited outline', 'Edited review'])
        self.assertEqual([task.estimated_minutes for task in tasks], [25, 20])
        self.assertEqual([task.order for task in tasks], [6, 7])
        for task in tasks:
            self.assertEqual(task.user, self.user)
            self.assertEqual(task.assignment, self.assignment)
            self.assertTrue(task.ai_generated)
            self.assertFalse(task.is_completed)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'accepted')
        self.assertEqual(self.draft.revision, 2)
        self.assertEqual(self.draft.selected_indices, [0, 2])
        self.assertEqual(self.draft.expires_at, expires_at)
        self.assertNotContains(response, 'Review suggestions')

    def test_repeated_acceptance_never_duplicates_tasks(self):
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.new_tasks().count(), 2)

    def test_empty_selection_is_a_correctable_error(self):
        data = self.post_data()
        del data['suggestions-0-selected']
        del data['suggestions-2-selected']
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Select at least one suggestion', status_code=400)
        self.assertContains(response, 'Edited outline', status_code=400)
        self.assert_no_acceptance()

    def test_invalid_fields_or_revision_cannot_change_anything(self):
        for overrides in (
            {'suggestions-0-description': ''}, {'suggestions-0-description': 'x' * 501},
            {'suggestions-0-estimated_minutes': '0'}, {'suggestions-0-estimated_minutes': '481'},
            {'suggestions-0-estimated_minutes': '2.5'}, {'revision': ''}, {'revision': 'bad'},
            {'suggestions-1-description': ''}, # Unselected rows must still be valid.
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.client.post(self.url, self.post_data(**overrides)).status_code, 400)
                self.assert_no_acceptance()

    def test_form_count_tampering_cannot_add_or_drop_rows(self):
        for total in ('0', '2', '4', '10000'):
            with self.subTest(total=total):
                response = self.client.post(self.url, self.post_data(**{'suggestions-TOTAL_FORMS': total}))
                self.assertEqual(response.status_code, 400)
                self.assert_no_acceptance()
        data = self.post_data(**{'suggestions-INITIAL_FORMS': '0'})
        del data['suggestions-1-description']
        del data['suggestions-1-estimated_minutes']
        self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.assert_no_acceptance()

    def test_stale_review_cannot_be_accepted(self):
        self.client.post(self.review_url, self.post_data())
        response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.new_tasks().count(), 0)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'pending')
        self.assertEqual(self.draft.revision, 2)

    def test_expired_and_terminal_drafts_are_rejected(self):
        for status in ('accepted', 'discarded', 'superseded'):
            with self.subTest(status=status):
                SuggestionDraft.objects.filter(pk=self.draft.pk).update(status=status)
                self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
                self.assertEqual(self.new_tasks().count(), 0)
        now = timezone.now()
        SuggestionDraft.objects.filter(pk=self.draft.pk).update(
            status='pending', created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1),
        )
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.new_tasks().count(), 0)

    def test_expiration_is_rechecked_inside_acceptance_transaction(self):
        original = accept_suggestion_draft

        def expire_then_accept(**kwargs):
            now = timezone.now()
            SuggestionDraft.objects.filter(pk=self.draft.pk).update(
                created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1),
            )
            return original(**kwargs)

        with patch('ai_assistant.views.accept_suggestion_draft', side_effect=expire_then_accept):
            self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.new_tasks().count(), 0)

    def test_replacement_is_rechecked_inside_acceptance_transaction(self):
        original = accept_suggestion_draft

        def replace_then_accept(**kwargs):
            SuggestionDraft.objects.filter(pk=self.draft.pk).update(status='superseded')
            return original(**kwargs)

        with patch('ai_assistant.views.accept_suggestion_draft', side_effect=replace_then_accept):
            self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.new_tasks().count(), 0)

    def test_corrupted_saved_draft_is_rejected_safely(self):
        SuggestionDraft.objects.filter(pk=self.draft.pk).update(selected_indices={'invalid': True})
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.new_tasks().count(), 0)

    def test_partial_task_insert_failure_rolls_back_everything(self):
        original = TaskItem.objects.bulk_create

        def fail_after_insert(tasks):
            original(tasks[:1])
            raise DatabaseError('Private provider or database details')

        with patch('ai_assistant.acceptance.TaskItem.objects.bulk_create', side_effect=fail_after_insert):
            response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'Private provider', status_code=409)
        self.assert_no_acceptance()

    def test_draft_consumption_failure_rolls_back_inserted_tasks(self):
        with patch.object(SuggestionDraft, 'save', side_effect=DatabaseError('private')):
            self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assert_no_acceptance()

    def test_direct_service_revalidates_shape_fields_and_selections(self):
        valid = self.draft.suggestions
        for suggestions, selected in (
            ([], [0]), (valid[:1], [0]),
            ([{'description': 'bad', 'estimated_minutes': 0}] * 3, [0]),
            (valid, [True]), (valid, [3]), (valid, [0, 0]), (valid, []),
        ):
            with self.subTest(selected=selected), self.assertRaises(ValidationError):
                accept_suggestion_draft(
                    draft=self.draft, user=self.user, revision=1,
                    suggestions=suggestions, selected_indices=selected,
                )
            self.assert_no_acceptance()

    def test_untrusted_completion_order_and_ownership_fields_are_ignored(self):
        response = self.client.post(self.url, self.post_data(**{
            'user': self.other.pk, 'assignment': self.other_assignment.pk,
            'order': '999', 'is_completed': 'true', 'ai_generated': 'false', 'selected_indices': '[1]',
        }))
        self.assertEqual(response.status_code, 302)
        for task in self.new_tasks():
            self.assertEqual(task.user, self.user)
            self.assertEqual(task.assignment, self.assignment)
            self.assertFalse(task.is_completed)
            self.assertTrue(task.ai_generated)
        self.assertEqual(list(self.new_tasks().values_list('order', flat=True)), [6, 7])

    def test_acceptance_requires_post_authentication_ownership_and_csrf(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.post_data()).status_code, 403)
        client.get(self.review_url)
        data = self.post_data(csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        self.assertEqual(client.post(self.url, data).status_code, 302)
        self.assertEqual(self.new_tasks().count(), 2)

    @override_settings(AI_SUGGESTIONS_MODE='gemini')
    def test_acceptance_does_not_depend_on_current_provider_or_key(self):
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 302)
        self.assertEqual(self.new_tasks().count(), 2)

    def test_empty_checklist_starts_at_order_zero(self):
        draft = SuggestionDraft.objects.create(
            user=self.user, assignment=self.other_empty_assignment(),
            suggestions=[{'description': 'First task', 'estimated_minutes': 10}],
            selected_indices=[0], generation_mode='demo', model_name='demo-task-suggestions',
        )
        count = accept_suggestion_draft(
            draft=draft, user=self.user, revision=1, suggestions=draft.suggestions, selected_indices=[0],
        )
        self.assertEqual(count, 1)
        self.assertEqual(self.new_tasks().get().order, 0)

    def other_empty_assignment(self):
        return Assignment.objects.create(
            course=self.assignment.course, canvas_assignment_id=9599, title='Empty checklist',
        )
