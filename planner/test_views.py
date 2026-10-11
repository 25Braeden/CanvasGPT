import datetime

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
        response = self.client.get(reverse('planner:plan_detail'))
        self.assertContains(response, 'Read chapter 4')
        day = response.context['days'][0][0]
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
