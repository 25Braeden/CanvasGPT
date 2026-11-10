import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ai_assistant.models import TaskItem
from canvas_sync.models import Assignment, Course

from .models import AvailabilityBlock, PlanSession, StudyPlan

User = get_user_model()


class PlannerViewTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='owner', password='test-pass-123')
        self.other = User.objects.create_user(username='intruder', password='test-pass-123')
        self.course = Course.objects.create(
            user=self.user, canvas_course_id=301, name='Operating Systems'
        )
        self.assignment = Assignment.objects.create(
            course=self.course,
            canvas_assignment_id=3001,
            title='Scheduler Lab',
            due_at=timezone.now() + datetime.timedelta(days=14),
        )
        self.client.force_login(self.user)

    def make_block(self, user=None, **kwargs):
        kwargs.setdefault('weekday', AvailabilityBlock.Weekday.MONDAY)
        kwargs.setdefault('start_time', datetime.time(18, 0))
        kwargs.setdefault('end_time', datetime.time(20, 0))
        kwargs.setdefault('recurrence', AvailabilityBlock.Recurrence.WEEKLY)
        return AvailabilityBlock.objects.create(user=user or self.user, **kwargs)

    def make_session(self, user=None, assignment=None, **kwargs):
        user = user or self.user
        task = TaskItem.objects.create(
            assignment=assignment or self.assignment,
            user=user,
            description=kwargs.pop('description', 'Write tests'),
        )
        plan = kwargs.pop('plan', None) or StudyPlan.objects.create(
            user=user,
            start_date=datetime.date(2026, 10, 1),
            end_date=datetime.date(2026, 10, 1),
        )
        start = kwargs.pop(
            'scheduled_start',
            datetime.datetime(2026, 10, 1, 18, tzinfo=datetime.timezone.utc),
        )
        return PlanSession.objects.create(
            study_plan=plan,
            task_item=task,
            scheduled_start=start,
            scheduled_end=start + datetime.timedelta(minutes=30),
            **kwargs,
        )


class AvailabilityViewTests(PlannerViewTestCase):
    def test_list_shows_only_own_blocks(self):
        self.make_block(weekday=AvailabilityBlock.Weekday.TUESDAY)
        self.make_block(user=self.other, weekday=AvailabilityBlock.Weekday.FRIDAY)

        response = self.client.get(reverse('planner:availability_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tuesday')
        self.assertNotContains(response, 'Friday')

    def test_list_hides_past_one_time_blocks(self):
        today = timezone.localdate()
        self.make_block(
            weekday=None,
            date=today + datetime.timedelta(days=2),
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )
        self.make_block(
            weekday=None,
            date=today - datetime.timedelta(days=2),
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )

        response = self.client.get(reverse('planner:availability_list'))

        self.assertEqual(len(response.context['one_time_blocks']), 1)

    def test_add_weekly_block(self):
        response = self.client.post(
            reverse('planner:availability_add'),
            {
                'recurrence': 'weekly',
                'weekday': AvailabilityBlock.Weekday.WEDNESDAY,
                'date': '2026-10-20',
                'start_time': '17:00',
                'end_time': '19:00',
            },
        )

        self.assertRedirects(response, reverse('planner:availability_list'))
        block = AvailabilityBlock.objects.get()
        self.assertEqual(block.user, self.user)
        self.assertEqual(block.weekday, AvailabilityBlock.Weekday.WEDNESDAY)
        # The date is ignored for weekly availability.
        self.assertIsNone(block.date)

    def test_add_one_time_block(self):
        response = self.client.post(
            reverse('planner:availability_add'),
            {
                'recurrence': 'none',
                'date': '2026-10-20',
                'weekday': AvailabilityBlock.Weekday.WEDNESDAY,
                'start_time': '09:00',
                'end_time': '10:30',
            },
        )

        self.assertRedirects(response, reverse('planner:availability_list'))
        block = AvailabilityBlock.objects.get()
        self.assertEqual(block.date, datetime.date(2026, 10, 20))
        self.assertIsNone(block.weekday)

    def test_add_validation_errors(self):
        url = reverse('planner:availability_add')
        cases = [
            {'recurrence': 'weekly', 'start_time': '17:00', 'end_time': '19:00'},
            {'recurrence': 'none', 'start_time': '17:00', 'end_time': '19:00'},
            {'recurrence': 'weekly', 'weekday': 0, 'start_time': '19:00', 'end_time': '17:00'},
            {'recurrence': 'weekly', 'weekday': 0, 'start_time': '17:00', 'end_time': '17:00'},
        ]
        for data in cases:
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 400, data)
        self.assertFalse(AvailabilityBlock.objects.exists())

    def test_cannot_assign_block_to_another_user(self):
        self.client.post(
            reverse('planner:availability_add'),
            {
                'recurrence': 'weekly',
                'weekday': 0,
                'start_time': '17:00',
                'end_time': '19:00',
                'user': self.other.pk,
            },
        )

        self.assertEqual(AvailabilityBlock.objects.get().user, self.user)

    def test_add_form_shows_timezone_and_availability_help(self):
        self.user.student_profile.timezone = 'America/New_York'
        self.user.student_profile.save()

        response = self.client.get(
            reverse('planner:availability_add')
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'America/New_York')
        self.assertContains(
            response,
            'Overnight availability should be entered as two separate blocks.',
        )
        self.assertContains(response, 'id="weekday-field"')
        self.assertContains(response, 'id="date-field"')

    def test_edit_form_shows_timezone_and_both_fallback_fields(self):
        self.user.student_profile.timezone = 'America/New_York'
        self.user.student_profile.save()

        block = self.make_block()

        response = self.client.get(
            reverse(
                'planner:availability_edit',
                args=[block.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'America/New_York')
        self.assertContains(response, 'name="weekday"')
        self.assertContains(response, 'name="date"')

    def test_invalid_time_range_shows_useful_error(self):
        response = self.client.post(
            reverse('planner:availability_add'),
            {
                'recurrence': 'weekly',
                'weekday': AvailabilityBlock.Weekday.MONDAY,
                'start_time': '20:00',
                'end_time': '18:00',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            'End time must be after start time.',
            status_code=400,
        )

    def test_validation_error_keeps_recurrence_selection(self):
        response = self.client.post(
            reverse('planner:availability_add'),
            {
                'recurrence': 'none',
                'date': '',
                'start_time': '09:00',
                'end_time': '10:00',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.context['form']['recurrence'].value(),
            'none',
        )

    def test_edit_block(self):
        block = self.make_block()

        response = self.client.post(
            reverse('planner:availability_edit', args=[block.pk]),
            {'recurrence': 'none', 'date': '2026-11-02', 'start_time': '08:00', 'end_time': '09:00'},
        )

        self.assertRedirects(response, reverse('planner:availability_list'))
        block.refresh_from_db()
        self.assertEqual(block.recurrence, AvailabilityBlock.Recurrence.NONE)
        self.assertEqual(block.date, datetime.date(2026, 11, 2))
        self.assertIsNone(block.weekday)

    def test_edit_validation_errors(self):
        block = self.make_block()

        response = self.client.post(
            reverse('planner:availability_edit', args=[block.pk]),
            {'recurrence': 'weekly', 'weekday': 0, 'start_time': '20:00', 'end_time': '18:00'},
        )

        self.assertEqual(response.status_code, 400)
        block.refresh_from_db()
        self.assertEqual(block.end_time, datetime.time(20, 0))

    def test_delete_block(self):
        block = self.make_block()

        response = self.client.post(reverse('planner:availability_delete', args=[block.pk]))

        self.assertRedirects(response, reverse('planner:availability_list'))
        self.assertFalse(AvailabilityBlock.objects.filter(pk=block.pk).exists())

    def test_delete_requires_post(self):
        block = self.make_block()

        response = self.client.get(reverse('planner:availability_delete', args=[block.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(AvailabilityBlock.objects.filter(pk=block.pk).exists())

    def test_other_users_block_actions_rejected(self):
        block = self.make_block(user=self.other)

        edit_url = reverse('planner:availability_edit', args=[block.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        response = self.client.post(
            edit_url,
            {'recurrence': 'weekly', 'weekday': 3, 'start_time': '01:00', 'end_time': '02:00'},
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(reverse('planner:availability_delete', args=[block.pk]))
        self.assertEqual(response.status_code, 404)

        block.refresh_from_db()
        self.assertEqual(block.weekday, AvailabilityBlock.Weekday.MONDAY)
        self.assertEqual(block.start_time, datetime.time(18, 0))


class WeeklyPlanViewTests(PlannerViewTestCase):
    def setUp(self):
        super().setUp()
        self.user.student_profile.timezone = 'America/Los_Angeles'
        self.user.student_profile.save()
        self.url = reverse('planner:plan_detail')

    def test_local_week_boundaries_and_grouping(self):
        # March 2 is PST; March 9 is PDT, so this week is only 167 hours.
        start = datetime.datetime(2026, 3, 2, 8, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 3, 9, 7, tzinfo=datetime.timezone.utc)
        first = self.make_session(scheduled_start=start, description='Monday session')
        plan = first.study_plan
        last = self.make_session(
            plan=plan, scheduled_start=end - datetime.timedelta(minutes=1), description='Sunday session',
        )
        self.make_session(
            plan=plan, scheduled_start=start - datetime.timedelta(minutes=1), description='Previous week session',
        )
        self.make_session(plan=plan, scheduled_start=end, description='Next week session')

        response = self.client.get(self.url, {'week': '2026-03-05'})

        days = response.context['days']
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0], (datetime.date(2026, 3, 2), [first]))
        self.assertEqual(days[-1], (datetime.date(2026, 3, 8), [last]))
        self.assertEqual(sum(len(sessions) for _, sessions in days), 2)
        self.assertContains(response, 'Monday session')
        self.assertContains(response, 'Sunday session')
        self.assertNotContains(response, 'Previous week session')
        self.assertNotContains(response, 'Next week session')

    def test_fall_dst_week_includes_both_repeated_local_times(self):
        # October 26 starts in PDT; November 2 starts in PST (169 hours).
        start = datetime.datetime(2026, 10, 26, 7, tzinfo=datetime.timezone.utc)
        end = datetime.datetime(2026, 11, 2, 8, tzinfo=datetime.timezone.utc)
        first = self.make_session(scheduled_start=start)
        plan = first.study_plan
        repeated = [
            self.make_session(
                plan=plan,
                scheduled_start=datetime.datetime(2026, 11, 1, hour, 30, tzinfo=datetime.timezone.utc),
            )
            for hour in (8, 9)
        ]
        last = self.make_session(plan=plan, scheduled_start=end - datetime.timedelta(microseconds=1))
        self.make_session(plan=plan, scheduled_start=end)

        response = self.client.get(self.url, {'week': '2026-11-01'})

        days = response.context['days']
        self.assertEqual(days[0], (datetime.date(2026, 10, 26), [first]))
        self.assertEqual(days[-1], (datetime.date(2026, 11, 1), [*repeated, last]))
        self.assertEqual(sum(len(sessions) for _, sessions in days), 4)

    def test_empty_week_has_all_seven_dates(self):
        self.make_session()
        response = self.client.get(self.url, {'week': '2026-12-30'})
        days = response.context['days']
        self.assertEqual(days, [
            (datetime.date(2026, 12, 28) + datetime.timedelta(days=i), [])
            for i in range(7)
        ])
        self.assertEqual(response.context['next_week'], datetime.date(2027, 1, 4))

    def test_week_navigation_and_range(self):
        now = datetime.datetime(2026, 3, 5, 12, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=now):
            response = self.client.get(self.url, {'week': '2026-12-30'})

        self.assertContains(response, 'Dec 28, 2026 – Jan 3, 2027')
        for label, target in (
            ('Previous week', '2026-12-21'),
            ('This week', '2026-03-02'),
            ('Next week', '2027-01-04'),
        ):
            self.assertContains(
                response,
                f'<a class="button" data-preserve-scroll href="{self.url}?week={target}">{label}</a>',
                html=True,
            )

    def test_empty_days_render_with_and_without_a_plan(self):
        for has_plan in (False, True):
            with self.subTest(has_plan=has_plan):
                if has_plan:
                    self.make_session()
                response = self.client.get(self.url, {'week': '2026-12-30'})

                self.assertContains(response, '<li>No sessions</li>', count=7, html=True)
                for label in ('Previous week', 'This week', 'Next week'):
                    self.assertContains(response, label)
                for offset in range(7):
                    day = datetime.date(2026, 12, 28) + datetime.timedelta(days=offset)
                    heading = f'{day:%A}, {day:%b} {day.day}, {day.year}'
                    self.assertContains(
                        response, f'<h2 class="section-divider">{heading}</h2>', html=True,
                    )

    def test_invalid_or_missing_week_uses_students_current_week(self):
        # Still Sunday in Los Angeles, even though UTC has reached Monday.
        now = datetime.datetime(2026, 3, 9, 1, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=now):
            for value in (None, '', 'nonsense', '2026-02-30', '20260309', '0001-01-01', '9999-12-31'):
                with self.subTest(week=value):
                    response = self.client.get(self.url, {} if value is None else {'week': value})
                    self.assertEqual(response.context['week_start'], datetime.date(2026, 3, 2))
                    self.assertEqual(len(response.context['days']), 7)

    def test_completion_preserves_selected_week_and_updates_task(self):
        session = self.make_session()
        response = self.client.get(self.url, {'week': '2026-10-01'})
        self.assertContains(
            response, '<input type="hidden" name="week" value="2026-09-28">',
            count=2, html=True,
        )
        self.assertContains(response, f'data-scroll-page="{self.url}?week=2026-09-28"', count=2)
        response = self.client.post(
            reverse('planner:session_toggle', args=[session.pk]), {'week': '2026-10-01'},
        )
        self.assertRedirects(response, self.url + '?week=2026-09-28')
        session.refresh_from_db()
        session.task_item.refresh_from_db()
        self.assertTrue(session.is_completed)
        self.assertTrue(session.task_item.is_completed)

    def test_generation_preserves_selected_week(self):
        response = self.client.post(reverse('planner:plan_generate'), {'week': '2026-12-30'})
        self.assertRedirects(response, self.url + '?week=2026-12-28')

    def test_invalid_completion_week_falls_back_without_external_redirect(self):
        session = self.make_session()
        now = datetime.datetime(2026, 3, 5, 12, tzinfo=datetime.timezone.utc)
        with patch('django.utils.timezone.now', return_value=now):
            for week in ('', 'invalid', 'https://other.test/', '9999-12-31'):
                with self.subTest(week=week):
                    response = self.client.post(
                        reverse('planner:session_toggle', args=[session.pk]), {'week': week},
                    )
                    self.assertRedirects(response, self.url + '?week=2026-03-02')

    def test_scroll_script_is_shared_across_pages(self):
        for name in ('home', 'dashboard', 'accounts:profile', 'planner:plan_detail',
                     'planner:availability_list', 'canvas_sync:connection'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, '/static/accounts/preserve-scroll.js', count=1)

    def test_selected_week_excludes_other_users_tasks(self):
        own = self.make_session()
        self.make_session(user=self.other, description='Private session')
        self.make_session(user=self.other, plan=own.study_plan, description='Foreign task')

        response = self.client.get(self.url, {'week': '2026-10-01'})

        sessions = [session for _, items in response.context['days'] for session in items]
        self.assertEqual(sessions, [own])
        self.assertNotContains(response, 'Private session')
        self.assertNotContains(response, 'Foreign task')

    def test_selected_week_ignores_inactive_and_foreign_plans_with_own_tasks(self):
        active = self.make_session(description='Active session')
        inactive_plan = StudyPlan.objects.create(
            user=self.user, start_date=active.study_plan.start_date,
            end_date=active.study_plan.end_date, is_active=False,
        )
        self.make_session(plan=inactive_plan, description='Inactive session')
        foreign_plan = StudyPlan.objects.create(
            user=self.other, start_date=active.study_plan.start_date,
            end_date=active.study_plan.end_date,
        )
        self.make_session(plan=foreign_plan, description='Session on foreign plan')

        response = self.client.get(self.url, {'week': '2026-10-01'})

        sessions = [session for _, items in response.context['days'] for session in items]
        self.assertEqual(sessions, [active])
        # These are still the user's tasks, so the unscheduled list may show
        # them; only session rows must exclude inactive and foreign plans.
        for description in ('Inactive session', 'Session on foreign plan'):
            self.assertNotContains(
                response, f'<strong class="schedule-task">{description}</strong>', html=True,
            )


class PlanSummaryTests(PlannerViewTestCase):
    def test_totals_cover_entire_active_plan_and_use_session_durations(self):
        first = self.make_session()
        plan = first.study_plan
        # Split one task across weeks; its estimate must not determine totals.
        first.task_item.estimated_minutes = 999
        first.task_item.save()
        PlanSession.objects.create(
            study_plan=plan,
            task_item=first.task_item,
            scheduled_start=first.scheduled_start + datetime.timedelta(days=7),
            scheduled_end=first.scheduled_start + datetime.timedelta(days=7, minutes=45),
        )
        self.make_session(plan=plan, is_completed=True)
        TaskItem.objects.create(
            user=self.user, assignment=self.assignment, description='Not scheduled',
        )
        expected = {
            'scheduled_unfinished_minutes': 75,
            'completed_session_minutes': 30,
            'unscheduled_task_count': 1,
        }

        for week in ('2026-10-01', '2026-10-08', '2026-12-30'):
            with self.subTest(week=week):
                response = self.client.get(reverse('planner:plan_detail'), {'week': week})
                self.assertEqual(response.context['plan_summary'], expected)
                self.assertEqual(len(response.context['unscheduled']), 1)
                self.assertContains(response, 'Entire active plan')
                self.assertContains(
                    response,
                    '<p><strong>75 min</strong> scheduled unfinished · '
                    '<strong>30 min</strong> completed sessions · '
                    '<strong>1</strong> task not scheduled</p>',
                    html=True,
                )
                self.assertContains(
                    response,
                    'Totals cover your entire active plan, not just the week below.',
                )
                content = response.content.decode()
                self.assertLess(
                    content.index('id="plan-summary-heading"'),
                    content.index('aria-label="Study plan week navigation"'),
                )

    def test_summary_excludes_inactive_foreign_and_cross_linked_records(self):
        own = self.make_session()
        inactive = StudyPlan.objects.create(
            user=self.user, start_date=own.study_plan.start_date,
            end_date=own.study_plan.end_date, is_active=False,
        )
        self.make_session(plan=inactive, is_completed=True)
        other_course = Course.objects.create(
            user=self.other, canvas_course_id=990, name='Private course',
        )
        other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=9900, title='Private assignment',
        )
        self.make_session(user=self.other, assignment=other_assignment)
        self.make_session(
            user=self.other, assignment=other_assignment, plan=own.study_plan,
        )
        self.make_session(assignment=other_assignment, plan=own.study_plan)
        TaskItem.objects.create(
            user=self.other, assignment=other_assignment, description='Private task',
        )
        # An own task in an inactive plan is still unscheduled in the active plan.
        expected = {
            'scheduled_unfinished_minutes': 30,
            'completed_session_minutes': 0,
            'unscheduled_task_count': 1,
        }
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertEqual(response.context['plan_summary'], expected)
        self.assertEqual(len(response.context['unscheduled']), 1)

    def test_foreign_records_do_not_change_summary_or_warning_actions(self):
        own = self.make_session()
        TaskItem.objects.create(
            user=self.user, assignment=self.assignment, description='Own unscheduled task',
        )
        url = reverse('planner:plan_detail')
        before = self.client.get(url)
        expected_summary = before.context['plan_summary']
        expected_warnings = [
            (item.task.pk, item.reason, item.next_step)
            for item in before.context['unscheduled']
        ]
        course = Course.objects.create(user=self.other, canvas_course_id=991, name='Private course')
        assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=9910, title='Confidential assignment',
        )
        for index, (user, task_assignment) in enumerate((
            (self.other, assignment),
            (self.other, self.assignment),
            (self.user, assignment),
        )):
            self.make_session(
                user=user, assignment=task_assignment, plan=own.study_plan,
                is_completed=index % 2 == 0, description=f'Confidential session {index}',
            )
            TaskItem.objects.create(
                user=user, assignment=task_assignment,
                description=f'Confidential unscheduled task {index}',
            )
        self.make_session(user=self.other, assignment=assignment)

        after = self.client.get(url)
        self.assertEqual(after.context['plan_summary'], expected_summary)
        self.assertEqual([
            (item.task.pk, item.reason, item.next_step)
            for item in after.context['unscheduled']
        ], expected_warnings)
        self.assertNotContains(after, 'Confidential')
        self.assertNotContains(after, reverse('canvas_sync:assignment_detail', args=[assignment.pk]))

    def test_own_task_sessions_on_foreign_or_inactive_plans_do_not_add_minutes(self):
        own = self.make_session()
        for user, active in ((self.other, True), (self.user, False)):
            plan = StudyPlan.objects.create(
                user=user, is_active=active,
                start_date=own.study_plan.start_date, end_date=own.study_plan.end_date,
            )
            for completed in (False, True):
                PlanSession.objects.create(
                    study_plan=plan, task_item=own.task_item,
                    scheduled_start=own.scheduled_start,
                    scheduled_end=own.scheduled_start + datetime.timedelta(hours=5),
                    is_completed=completed,
                )
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertEqual(response.context['plan_summary'], {
            'scheduled_unfinished_minutes': 30,
            'completed_session_minutes': 0,
            'unscheduled_task_count': 0,
        })

    def test_no_plan_and_empty_plan_have_no_summary(self):
        url = reverse('planner:plan_detail')
        response = self.client.get(url)
        self.assertIsNone(response.context['plan_summary'])
        self.assertNotContains(response, 'id="plan-summary-heading"')
        StudyPlan.objects.create(
            user=self.user, start_date=timezone.localdate(), end_date=timezone.localdate(),
        )
        response = self.client.get(url)
        self.assertIsNone(response.context['plan_summary'])
        self.assertNotContains(response, 'id="plan-summary-heading"')

    def test_completion_moves_minutes_between_totals(self):
        session = self.make_session()
        self.client.post(reverse('planner:session_toggle', args=[session.pk]))
        summary = self.client.get(reverse('planner:plan_detail')).context['plan_summary']
        self.assertEqual(summary['scheduled_unfinished_minutes'], 0)
        self.assertEqual(summary['completed_session_minutes'], 30)
        self.client.post(reverse('planner:session_toggle', args=[session.pk]))
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertEqual(response.context['plan_summary'], {
            'scheduled_unfinished_minutes': 30,
            'completed_session_minutes': 0,
            'unscheduled_task_count': 0,
        })
        self.assertNotContains(response, 'All sessions in your active plan are complete.')


class PlanEmptyStateTests(PlannerViewTestCase):
    def test_no_plan_with_tasks_guides_generation_without_failure_warning(self):
        TaskItem.objects.create(user=self.user, assignment=self.assignment, description='Read')
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertContains(response, 'Add availability, then choose Generate plan')
        self.assertNotContains(response, 'Couldn’t schedule')
        self.assertNotContains(response, 'id="plan-summary-heading"')
        self.assertNotContains(response, 'There are no tasks to schedule yet.')

    def test_zero_task_states_show_guidance_instead_of_totals(self):
        for has_plan in (False, True):
            with self.subTest(has_plan=has_plan):
                if has_plan:
                    StudyPlan.objects.create(
                        user=self.user, start_date=timezone.localdate(),
                        end_date=timezone.localdate(),
                    )
                response = self.client.get(reverse('planner:plan_detail'))
                self.assertContains(response, 'There are no tasks to schedule yet.')
                self.assertContains(response, f'href="{reverse("canvas_sync:connection")}"')
                self.assertContains(response, 'to add checklist tasks.')
                self.assertNotContains(response, 'id="plan-summary-heading"')
                self.assertNotContains(response, 'Couldn’t schedule')
                self.assertNotContains(response, 'Nice work!')

    def test_completed_only_plan_keeps_minutes_and_shows_completion_message(self):
        session = self.make_session(is_completed=True)
        session.task_item.is_completed = True
        session.task_item.save()
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertContains(response, '<strong>30 min</strong> completed sessions')
        self.assertContains(response, 'All sessions in your active plan are complete. Nice work!')
        self.assertNotContains(response, 'There are no tasks to schedule yet.')

    def test_wholly_unscheduled_plan_keeps_zero_minutes_and_actionable_warning(self):
        TaskItem.objects.create(user=self.user, assignment=self.assignment, description='Read')
        self.client.post(reverse('planner:plan_generate'))
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertEqual(response.context['plan_summary'], {
            'scheduled_unfinished_minutes': 0,
            'completed_session_minutes': 0,
            'unscheduled_task_count': 1,
        })
        self.assertContains(response, 'id="plan-summary-heading"')
        self.assertContains(response, 'Couldn’t schedule 1 task')
        self.assertContains(response, 'Adjust availability')
        self.assertNotContains(response, 'There are no tasks to schedule yet.')
        self.assertNotContains(response, 'Nice work!')

    def test_other_students_records_do_not_hide_empty_guidance(self):
        course = Course.objects.create(user=self.other, canvas_course_id=999, name='Private')
        assignment = Assignment.objects.create(
            course=course, canvas_assignment_id=9999, title='Private assignment',
        )
        plan = StudyPlan.objects.create(
            user=self.user, start_date=timezone.localdate(), end_date=timezone.localdate(),
        )
        self.make_session(user=self.other, assignment=assignment, plan=plan)
        self.make_session(assignment=assignment, plan=plan)
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertContains(response, 'There are no tasks to schedule yet.')
        self.assertNotContains(response, 'id="plan-summary-heading"')
        self.assertNotContains(response, 'Private assignment')


class UnscheduledWarningLinkTests(PlannerViewTestCase):
    def test_warning_actions_match_each_reason_and_assignment(self):
        now = timezone.now()
        StudyPlan.objects.create(
            user=self.user, start_date=now.date(), end_date=now.date(),
        )
        cases = (
            (None, 'no due date', 'Review assignment'),
            (now - datetime.timedelta(days=1), 'already past due', 'Review assignment'),
            (now + datetime.timedelta(days=7), 'Not in your current plan', 'Adjust availability'),
        )
        for index, (due_at, reason, label) in enumerate(cases):
            with self.subTest(reason=reason):
                assignment = Assignment.objects.create(
                    course=self.course, canvas_assignment_id=8000 + index,
                    title=f'Assignment {index}', due_at=due_at,
                )
                task = TaskItem.objects.create(
                    user=self.user, assignment=assignment, description=f'Task {index}',
                )
                response = self.client.get(reverse('planner:plan_detail'))
                # Inspect this warning row, not unrelated navigation links.
                row = response.content.decode().split(f'<strong>{task.description}</strong>')[1]
                row = row.split('</li>')[0]
                self.assertIn(reason, row)
                target = (
                    reverse('canvas_sync:assignment_detail', args=[assignment.pk])
                    if label == 'Review assignment'
                    else reverse('planner:availability_list')
                )
                self.assertIn(f'<a href="{target}">{label}</a>', row)
                if label == 'Adjust availability':
                    self.assertIn('or the task was added after the plan was generated', row)
                    self.assertIn('Regenerate your plan after changing availability or adding tasks.', row)
                else:
                    self.assertNotIn('Adjust availability', row)
                task.delete()


class PlanViewTests(PlannerViewTestCase):
    def test_plan_page_without_a_plan(self):
        response = self.client.get(reverse('planner:plan_detail'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generate plan')
        self.assertContains(response, 'haven’t added any availability')

    def test_generate_creates_a_plan_and_shows_sessions_by_date(self):
        self.make_block(
            weekday=None,
            date=timezone.localdate() + datetime.timedelta(days=1),
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )
        TaskItem.objects.create(
            assignment=self.assignment, user=self.user, description='Read chapter 4'
        )

        response = self.client.post(reverse('planner:plan_generate'))

        self.assertRedirects(response, reverse('planner:plan_detail'))
        plan = StudyPlan.objects.get(user=self.user, is_active=True)
        self.assertEqual(plan.sessions.count(), 1)
        # Tomorrow can be in the following week (when the test runs on Sunday).
        session = plan.sessions.get()
        tz = ZoneInfo(self.user.student_profile.timezone)
        day = timezone.localdate(session.scheduled_start, timezone=tz)
        response = self.client.get(reverse('planner:plan_detail'), {'week': day.isoformat()})
        self.assertContains(response, 'Read chapter 4')
        self.assertIn((day, [session]), response.context['days'])
        self.assertContains(response, day.strftime('%A'))

    def test_plan_page_reports_unscheduled_tasks(self):
        no_due = Assignment.objects.create(
            course=self.course, canvas_assignment_id=3002, title='Reflection'
        )
        TaskItem.objects.create(assignment=no_due, user=self.user, description='Write reflection')

        self.client.post(reverse('planner:plan_generate'))
        response = self.client.get(reverse('planner:plan_detail'))

        self.assertContains(response, 'Couldn’t schedule 1 task')
        self.assertContains(response, 'Write reflection')
        self.assertContains(response, 'no due date')

    def test_generate_requires_post(self):
        response = self.client.get(reverse('planner:plan_generate'))

        self.assertEqual(response.status_code, 405)
        self.assertFalse(StudyPlan.objects.exists())

    def test_plan_page_shows_only_own_plan(self):
        other_course = Course.objects.create(user=self.other, canvas_course_id=302, name='Theirs')
        other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=3003, title='Their Lab'
        )
        self.make_session(user=self.other, assignment=other_assignment, description='Secret task')

        response = self.client.get(reverse('planner:plan_detail'))

        self.assertIsNone(response.context['plan'])
        self.assertNotContains(response, 'Secret task')

    def test_toggle_session_complete(self):
        session = self.make_session()

        response = self.client.post(reverse('planner:session_toggle', args=[session.pk]))

        self.assertRedirects(response, reverse('planner:plan_detail'))
        session.refresh_from_db()
        self.assertTrue(session.is_completed)
        self.client.post(reverse('planner:session_toggle', args=[session.pk]))
        session.refresh_from_db()
        self.assertFalse(session.is_completed)

    def test_task_completes_when_all_its_sessions_are_complete(self):
        first = self.make_session()
        second = PlanSession.objects.create(
            study_plan=first.study_plan,
            task_item=first.task_item,
            scheduled_start=first.scheduled_end,
            scheduled_end=first.scheduled_end + datetime.timedelta(minutes=30),
        )
        task = first.task_item

        self.client.post(reverse('planner:session_toggle', args=[first.pk]))
        task.refresh_from_db()
        self.assertFalse(task.is_completed)

        self.client.post(reverse('planner:session_toggle', args=[second.pk]))
        task.refresh_from_db()
        self.assertTrue(task.is_completed)

        self.client.post(reverse('planner:session_toggle', args=[second.pk]))
        task.refresh_from_db()
        self.assertFalse(task.is_completed)

    def test_toggle_requires_post(self):
        session = self.make_session()

        response = self.client.get(reverse('planner:session_toggle', args=[session.pk]))

        self.assertEqual(response.status_code, 405)

    def test_other_users_session_toggle_rejected(self):
        other_course = Course.objects.create(user=self.other, canvas_course_id=303, name='Theirs')
        other_assignment = Assignment.objects.create(
            course=other_course, canvas_assignment_id=3004, title='Their Lab'
        )
        session = self.make_session(user=self.other, assignment=other_assignment)

        response = self.client.post(reverse('planner:session_toggle', args=[session.pk]))

        self.assertEqual(response.status_code, 404)
        session.refresh_from_db()
        self.assertFalse(session.is_completed)

    def test_anonymous_redirected_to_login(self):
        block = self.make_block()
        session = self.make_session()
        self.client.logout()
        for name, args in (
            ('availability_list', []),
            ('availability_add', []),
            ('availability_edit', [block.pk]),
            ('availability_delete', [block.pk]),
            ('plan_detail', []),
            ('plan_generate', []),
            ('session_toggle', [session.pk]),
        ):
            response = self.client.post(reverse(f'planner:{name}', args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn('/accounts/login/', response['Location'])
        self.assertTrue(AvailabilityBlock.objects.filter(pk=block.pk).exists())
        session.refresh_from_db()
        self.assertFalse(session.is_completed)
        self.assertEqual(StudyPlan.objects.count(), 1)
