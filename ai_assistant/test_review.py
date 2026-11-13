"""Review is provider-independent and never creates checklist/planner work."""

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

from .models import AIRequest, SuggestionDraft, TaskItem


@override_settings(AI_SUGGESTIONS_MODE='demo', GEMINI_API_KEY='')
class SuggestionReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='review-owner')
        cls.other = User.objects.create_user(username='review-other')
        cls.course = Course.objects.create(user=cls.user, canvas_course_id=901, name='Course')
        cls.assignment = Assignment.objects.create(
            course=cls.course, canvas_assignment_id=9001, title='Essay', description='Write an essay.',
        )
        cls.draft = SuggestionDraft.objects.create(
            user=cls.user, assignment=cls.assignment,
            suggestions=[
                {'description': 'Outline the essay', 'estimated_minutes': 30},
                {'description': 'Review the essay', 'estimated_minutes': 15},
            ],
            selected_indices=[0, 1], generation_mode='demo', model_name='demo-task-suggestions',
        )
        task = TaskItem.objects.create(
            user=cls.user, assignment=cls.assignment, description='Completed work',
            is_completed=True, order=5, estimated_minutes=40,
        )
        now = timezone.now()
        plan = StudyPlan.objects.create(user=cls.user, start_date=now.date(), end_date=now.date())
        PlanSession.objects.create(
            study_plan=plan, task_item=task, scheduled_start=now,
            scheduled_end=now + timedelta(minutes=40), is_completed=True,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('ai_assistant:suggestions_review', args=[self.draft.pk])
        self.discard_url = reverse('ai_assistant:suggestions_discard', args=[self.draft.pk])
        self.assignment_url = reverse('canvas_sync:assignment_detail', args=[self.assignment.pk])
        self.original_tasks = list(TaskItem.objects.values())
        self.original_plans = list(StudyPlan.objects.values())
        self.original_sessions = list(PlanSession.objects.values())
        self.original_audits = list(AIRequest.objects.values())
        for target in ('ai_assistant.gemini.requests.post', 'ai_assistant.drafts.generate_task_suggestions'):
            guard = patch(target, side_effect=AssertionError('Review must not call generation'))
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self):
        self.assertEqual(list(TaskItem.objects.values()), self.original_tasks)
        self.assertEqual(list(StudyPlan.objects.values()), self.original_plans)
        self.assertEqual(list(PlanSession.objects.values()), self.original_sessions)
        self.assertEqual(list(AIRequest.objects.values()), self.original_audits)

    def post_data(self, **overrides):
        return {
            'revision': '1',
            'suggestions-TOTAL_FORMS': '2', 'suggestions-INITIAL_FORMS': '2',
            'suggestions-MIN_NUM_FORMS': '1', 'suggestions-MAX_NUM_FORMS': '20',
            'suggestions-0-description': '  Write an updated outline  ',
            'suggestions-0-estimated_minutes': '25', 'suggestions-0-selected': 'on',
            'suggestions-1-description': 'Revised review task', 'suggestions-1-estimated_minutes': '20',
            **overrides,
        }

    def assert_original_draft(self):
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.revision, 1)
        self.assertEqual(self.draft.status, 'pending')
        self.assertEqual(self.draft.selected_indices, [0, 1])
        self.assertEqual(self.draft.suggestions[0]['description'], 'Outline the essay')

    def test_assignment_links_to_review(self):
        response = self.client.get(self.assignment_url)
        self.assertContains(response, self.url)
        self.assertContains(response, 'Review suggestions')
        self.assertContains(response, '2 of 2 selected')

    def test_review_renders_existing_values_selections_and_demo_origin(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Review task suggestions')
        self.assertContains(response, 'Outline the essay')
        self.assertContains(response, 'Save draft review')
        self.assertContains(response, 'Discard draft')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertContains(response, 'accounts/preserve-scroll.js')
        self.assertContains(response, 'Demo draft:')
        self.assertContains(response, 'Accept selected tasks')
        self.assertEqual(len(response.context['formset']), 2)
        self.assertTrue(response.context['formset'][0].initial['selected'])
        self.assert_original_draft()

    def test_save_edits_and_selections_persists_without_extending_expiry(self):
        expires_at = self.draft.expires_at
        response = self.client.post(self.url, self.post_data(), follow=True)
        self.assertContains(response, 'Draft review saved. No tasks have been added')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.suggestions, [
            {'description': 'Write an updated outline', 'estimated_minutes': 25},
            {'description': 'Revised review task', 'estimated_minutes': 20},
        ])
        self.assertEqual(self.draft.selected_indices, [0])
        self.assertEqual(self.draft.revision, 2)
        self.assertEqual(self.draft.expires_at, expires_at)
        response = self.client.get(self.assignment_url)
        self.assertContains(response, 'Write an updated outline')
        self.assertContains(response, '1 of 2 selected')

    def test_save_all_unselected_is_allowed(self):
        data = self.post_data()
        del data['suggestions-0-selected']
        self.assertEqual(self.client.post(self.url, data).status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.selected_indices, [])
        response = self.client.get(self.url)
        self.assertFalse(response.context['formset'][0].initial['selected'])
        self.assertFalse(response.context['formset'][1].initial['selected'])

    def test_validation_rejects_invalid_fields_without_saving_any_changes(self):
        for overrides in (
            {'suggestions-0-description': ''}, {'suggestions-0-description': '  '},
            {'suggestions-0-description': 'x' * 501},
            {'suggestions-0-estimated_minutes': '0'}, {'suggestions-0-estimated_minutes': '-1'},
            {'suggestions-0-estimated_minutes': '481'}, {'suggestions-0-estimated_minutes': '1.5'},
            {'suggestions-0-estimated_minutes': 'text'}, {'suggestions-0-estimated_minutes': ''},
            {'revision': ''}, {'revision': 'not-an-integer'},
        ):
            with self.subTest(overrides=overrides):
                response = self.client.post(self.url, self.post_data(**overrides))
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, 'Save draft review', status_code=400)
                self.assert_original_draft()

    def test_valid_length_and_duration_boundaries(self):
        response = self.client.post(self.url, self.post_data(**{
            'suggestions-0-description': 'x' * 500,
            'suggestions-0-estimated_minutes': '1', 'suggestions-1-estimated_minutes': '480',
        }))
        self.assertEqual(response.status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(len(self.draft.suggestions[0]['description']), 500)
        self.assertEqual(self.draft.suggestions[1]['estimated_minutes'], 480)

    def test_management_data_cannot_drop_or_add_suggestions(self):
        for total in ('0', '1', '3', '10000'):
            with self.subTest(total=total):
                response = self.client.post(self.url, self.post_data(**{'suggestions-TOTAL_FORMS': total}))
                self.assertEqual(response.status_code, 400)
                self.assert_original_draft()
        data = self.post_data()
        del data['suggestions-TOTAL_FORMS']
        self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.assert_original_draft()

    def test_forged_initial_count_cannot_hide_a_required_row(self):
        data = self.post_data(**{'suggestions-INITIAL_FORMS': '0'})
        del data['suggestions-1-description']
        del data['suggestions-1-estimated_minutes']
        self.assertEqual(self.client.post(self.url, data).status_code, 400)
        self.assert_original_draft()

    def test_stale_browser_tab_cannot_overwrite_a_saved_review(self):
        self.client.post(self.url, self.post_data())
        response = self.client.post(self.url, self.post_data(**{'suggestions-0-description': 'Stale edit'}))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'Reload before continuing', status_code=409)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.revision, 2)
        self.assertEqual(self.draft.suggestions[0]['description'], 'Write an updated outline')

    def test_expired_or_terminal_drafts_cannot_be_reviewed_saved_or_discarded(self):
        for status in ('accepted', 'discarded', 'superseded'):
            with self.subTest(status=status):
                SuggestionDraft.objects.filter(pk=self.draft.pk).update(status=status)
                self.assertEqual(self.client.get(self.url).status_code, 409)
                self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
                self.assertEqual(self.client.post(self.discard_url, {'revision': 1}).status_code, 409)
                self.draft.refresh_from_db()
                self.assertEqual(self.draft.status, status)
        now = timezone.now()
        SuggestionDraft.objects.filter(pk=self.draft.pk).update(
            status='pending', created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1),
        )
        self.assertEqual(self.client.get(self.url).status_code, 409)
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 409)
        self.assertEqual(self.client.post(self.discard_url, {'revision': 1}).status_code, 409)

    def test_review_rechecks_expiration_after_locking(self):
        from . import drafts
        original = drafts.update_draft_review

        def expire_then_save(**kwargs):
            now = timezone.now()
            SuggestionDraft.objects.filter(pk=self.draft.pk).update(
                created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1),
            )
            return original(**kwargs)

        with patch('ai_assistant.views.update_draft_review', side_effect=expire_then_save):
            response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 409)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.revision, 1)

    def test_discard_hides_draft_without_touching_checklist(self):
        response = self.client.post(self.discard_url, {'revision': 1})
        self.assertRedirects(response, self.assignment_url)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'discarded')
        self.assertEqual(self.draft.revision, 2)
        self.assertNotContains(self.client.get(self.assignment_url), 'Review suggestions')

    def test_stale_discard_does_not_remove_newer_edits(self):
        self.client.post(self.url, self.post_data())
        self.assertEqual(self.client.post(self.discard_url, {'revision': 1}).status_code, 409)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'pending')
        self.assertEqual(self.draft.revision, 2)

    def test_discard_requires_post_and_revision(self):
        self.assertEqual(self.client.get(self.discard_url).status_code, 405)
        self.assertEqual(self.client.post(self.discard_url).status_code, 400)
        self.assert_original_draft()

    def test_foreign_and_anonymous_access_is_rejected(self):
        self.client.force_login(self.other)
        for method, url in ((self.client.get, self.url), (self.client.post, self.url),
                            (self.client.post, self.discard_url)):
            self.assertEqual(method(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.post(self.discard_url, {'revision': 1}).status_code, 302)
        self.assert_original_draft()

    def test_csrf_required_for_review_and_discard(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.post_data()).status_code, 403)
        self.assertEqual(client.post(self.discard_url, {'revision': 1}).status_code, 403)
        client.get(self.url)
        data = self.post_data(csrfmiddlewaretoken=client.cookies['csrftoken'].value)
        self.assertEqual(client.post(self.url, data).status_code, 302)

    def test_storage_failure_preserves_draft_and_returns_safe_error(self):
        with patch.object(SuggestionDraft, 'save', side_effect=DatabaseError('Private storage details')):
            response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'Private storage details', status_code=409)
        self.assert_original_draft()

    def test_generated_and_edited_text_is_escaped(self):
        payload = '<script>alert("x")</script>'
        self.client.post(self.url, self.post_data(**{'suggestions-0-description': payload}))
        for url in (self.url, self.assignment_url):
            response = self.client.get(url)
            self.assertContains(response, '&lt;script&gt;')
            self.assertNotContains(response, '<script>alert(')

    @override_settings(AI_SUGGESTIONS_MODE='gemini')
    def test_review_uses_saved_origin_not_current_provider_settings(self):
        self.assertContains(self.client.get(self.url), 'Demo draft:')
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 302)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.generation_mode, 'demo')
        self.assertEqual(self.draft.model_name, 'demo-task-suggestions')

    def test_model_rejects_invalid_selection_indexes(self):
        for indices in ([True], [-1], [2], [0, 0], ['0'], {}, None):
            with self.subTest(indices=indices):
                self.draft.selected_indices = indices
                with self.assertRaises(ValidationError):
                    self.draft.full_clean()
