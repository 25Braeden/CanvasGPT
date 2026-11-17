"""Offline end-to-end request flow through real generation, drafts, and acceptance."""

import datetime
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from canvas_sync.models import Assignment, Course
from planner.models import AvailabilityBlock, PlanSession, StudyPlan
from planner.scheduling import generate_plan

from .models import AIRequest, SuggestionDraft, TaskItem


@override_settings(
    AI_SUGGESTIONS_MODE='demo',
    GEMINI_API_KEY='',
    GEMINI_MODEL='',
    GEMINI_TIMEOUT_SECONDS='invalid',
)
class OfflineSuggestionWorkflowTests(TestCase):
    def test_generate_reload_review_save_accept_and_replay_with_csrf(self):
        user = get_user_model().objects.create_user(username='offline-workflow')

        profile = user.student_profile
        profile.timezone = 'UTC'
        profile.preferred_session_minutes = 30
        profile.break_minutes = 0
        profile.save()

        course = Course.objects.create(
            user=user,
            canvas_course_id=991,
            name='Course',
        )

        now = timezone.now()
        availability_date = (now + timedelta(days=1)).date()
        due_at = datetime.datetime.combine(
            availability_date,
            datetime.time(23, 0),
            tzinfo=datetime.timezone.utc,
        )

        assignment = Assignment.objects.create(
            course=course,
            canvas_assignment_id=9901,
            title='Essay',
            description='Write an essay.',
            due_at=due_at,
        )

        completed = TaskItem.objects.create(
            user=user,
            assignment=assignment,
            description='Already complete',
            order=4,
            estimated_minutes=30,
            is_completed=True,
            ai_generated=False,
        )

        plan = StudyPlan.objects.create(
            user=user,
            start_date=now.date(),
            end_date=now.date(),
        )

        PlanSession.objects.create(
            study_plan=plan,
            task_item=completed,
            scheduled_start=now,
            scheduled_end=now + timedelta(minutes=30),
            is_completed=True,
        )

        original_task = TaskItem.objects.values().get(pk=completed.pk)

        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        detail_url = reverse(
            'canvas_sync:assignment_detail',
            args=[assignment.pk],
        )
        generate_url = reverse(
            'ai_assistant:suggestions_generate',
            args=[assignment.pk],
        )

        with patch(
            'ai_assistant.gemini.requests.post',
            side_effect=AssertionError('No live API'),
        ):
            client.get(detail_url)
            token = client.cookies['csrftoken'].value

            response = client.post(
                generate_url,
                {'csrfmiddlewaretoken': token},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

            self.assertIn(
                'Review suggestions',
                response.json()['html'],
            )

            draft = SuggestionDraft.objects.get()

            self.assertEqual(TaskItem.objects.count(), 1)
            self.assertEqual(AIRequest.objects.count(), 1)
            self.assertTrue(AIRequest.objects.get().success)

            self.assertContains(
                client.get(detail_url),
                'Draft saved until',
            )

            self.assertEqual(AIRequest.objects.count(), 1)

            review_url = reverse(
                'ai_assistant:suggestions_review',
                args=[draft.pk],
            )
            accept_url = reverse(
                'ai_assistant:suggestions_accept',
                args=[draft.pk],
            )

            review = client.get(review_url)
            forms = review.context['formset']

            data = {
                'csrfmiddlewaretoken': token,
                'revision': draft.revision,
                'suggestions-TOTAL_FORMS': len(forms),
                'suggestions-INITIAL_FORMS': len(forms),
            }

            for index, form in enumerate(forms):
                data[f'suggestions-{index}-description'] = (
                    form.initial['description']
                )
                data[f'suggestions-{index}-estimated_minutes'] = (
                    form.initial['estimated_minutes']
                )

            data['suggestions-0-description'] = 'My reviewed task'
            data['suggestions-0-estimated_minutes'] = 45
            data['suggestions-0-selected'] = 'on'

            self.assertEqual(
                client.post(review_url, data).status_code,
                302,
            )

            self.assertEqual(TaskItem.objects.count(), 1)

            draft.refresh_from_db()
            data['revision'] = draft.revision

            invalid = {
                **data,
                'suggestions-0-estimated_minutes': '0',
            }

            self.assertEqual(
                client.post(accept_url, invalid).status_code,
                400,
            )

            self.assertEqual(TaskItem.objects.count(), 1)

            accepted = client.post(
                accept_url,
                data,
                follow=True,
            )

            self.assertContains(
                accepted,
                'Added 1 task(s)',
            )

            task = TaskItem.objects.exclude(
                pk=completed.pk,
            ).get()

            self.assertEqual(
                task.description,
                'My reviewed task',
            )
            self.assertEqual(
                task.estimated_minutes,
                45,
            )
            self.assertEqual(
                task.order,
                5,
            )
            self.assertTrue(task.ai_generated)
            self.assertFalse(task.is_completed)

            self.assertEqual(
                client.post(accept_url, data).status_code,
                409,
            )

            self.assertEqual(TaskItem.objects.count(), 2)

            draft.refresh_from_db()

            self.assertEqual(
                draft.status,
                'accepted',
            )

            self.assertNotContains(
                client.get(detail_url),
                'Review suggestions',
            )

        self.assertEqual(
            TaskItem.objects.values().get(pk=completed.pk),
            original_task,
        )

        self.assertEqual(AIRequest.objects.count(), 1)

        AvailabilityBlock.objects.create(
            user=user,
            date=availability_date,
            start_time=datetime.time(18, 0),
            end_time=datetime.time(20, 0),
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )

        result = generate_plan(user, now=now)

        self.assertEqual(result.unscheduled, [])

        scheduled_sessions = list(
            result.plan.sessions.filter(
                task_item=task,
            ).order_by('scheduled_start')
        )

        self.assertTrue(scheduled_sessions)

        total_scheduled_minutes = sum(
            int(
                (
                    session.scheduled_end
                    - session.scheduled_start
                ).total_seconds()
                / 60
            )
            for session in scheduled_sessions
        )

        self.assertEqual(
            total_scheduled_minutes,
            task.estimated_minutes,
        )

        for session in scheduled_sessions:
            self.assertLessEqual(
                session.scheduled_end,
                assignment.due_at,
            )

        self.assertTrue(
            PlanSession.objects.filter(
                task_item=completed,
                is_completed=True,
            ).exists()
        )

        self.assertTrue(
            TaskItem.objects.filter(
                pk=completed.pk,
                is_completed=True,
            ).exists()
        )