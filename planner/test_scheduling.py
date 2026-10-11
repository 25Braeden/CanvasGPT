import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from ai_assistant.models import TaskItem
from canvas_sync.models import Assignment, Course

from .models import AvailabilityBlock, PlanSession, StudyPlan
from .scheduling import (
    NO_DUE_DATE,
    NOT_ENOUGH_TIME,
    NOT_IN_PLAN,
    PAST_DUE,
    find_unscheduled,
    generate_plan,
)

User = get_user_model()
UTC = datetime.timezone.utc

# Thursday, Oct 1 2026, 08:00 UTC.
NOW = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def at(day, hour, minute=0):
    """An aware UTC datetime on October 2026."""
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=UTC)


class SchedulingTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='test-pass-123')
        profile = self.user.student_profile
        profile.timezone = 'UTC'
        profile.preferred_session_minutes = 30
        profile.break_minutes = 0
        profile.save()
        self.course = Course.objects.create(
            user=self.user, canvas_course_id=1, name='Algorithms'
        )
        self.assignment_count = 0

    def set_profile(self, **fields):
        profile = self.user.student_profile
        for name, value in fields.items():
            setattr(profile, name, value)
        profile.save()

    def make_assignment(self, due_at, course=None, **kwargs):
        self.assignment_count += 1
        return Assignment.objects.create(
            course=course or self.course,
            canvas_assignment_id=self.assignment_count,
            title=f'Assignment {self.assignment_count}',
            due_at=due_at,
            **kwargs,
        )

    def make_task(self, assignment, minutes=30, user=None, **kwargs):
        return TaskItem.objects.create(
            assignment=assignment,
            user=user or self.user,
            description=kwargs.pop('description', f'Task for {assignment.title}'),
            estimated_minutes=minutes,
            **kwargs,
        )

    def weekly(self, weekday, start, end, user=None):
        return AvailabilityBlock.objects.create(
            user=user or self.user,
            weekday=weekday,
            start_time=start,
            end_time=end,
            recurrence=AvailabilityBlock.Recurrence.WEEKLY,
        )

    def one_time(self, date, start, end, user=None):
        return AvailabilityBlock.objects.create(
            user=user or self.user,
            date=date,
            start_time=start,
            end_time=end,
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )

    def sessions(self, plan):
        return list(plan.sessions.order_by('scheduled_start'))

    def times(self, plan):
        return [(s.scheduled_start, s.scheduled_end) for s in self.sessions(plan)]

    def assert_valid_plan(self, plan):
        """No overlaps, nothing past a due date, everything inside availability."""
        sessions = self.sessions(plan)
        for earlier, later in zip(sessions, sessions[1:]):
            self.assertLessEqual(earlier.scheduled_end, later.scheduled_start)
        tz = ZoneInfo(self.user.student_profile.timezone)
        blocks = list(AvailabilityBlock.objects.filter(user=self.user))
        for session in sessions:
            self.assertLessEqual(session.scheduled_end, session.task_item.assignment.due_at)
            start = session.scheduled_start.astimezone(tz)
            end = session.scheduled_end.astimezone(tz)
            inside = any(
                (block.date == start.date() or block.weekday == start.weekday())
                and start.date() == end.date()
                and block.start_time <= start.time()
                and end.time() <= block.end_time
                for block in blocks
            )
            self.assertTrue(inside, f'{session} is outside availability')


class GeneratePlanTests(SchedulingTestCase):
    def test_single_task_fits_in_one_block(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        task = self.make_task(self.make_assignment(at(5, 12)), minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.unscheduled, [])
        self.assertEqual(self.times(result.plan), [(at(1, 18), at(1, 18, 30))])
        self.assertEqual(result.plan.sessions.get().task_item, task)
        self.assertTrue(result.plan.is_active)
        self.assertEqual(result.plan.start_date, datetime.date(2026, 10, 1))
        self.assertEqual(result.plan.end_date, datetime.date(2026, 10, 1))

    def test_long_task_is_split_into_sessions_with_breaks(self):
        self.set_profile(preferred_session_minutes=30, break_minutes=10)
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(20))
        self.make_task(self.make_assignment(at(5, 12)), minutes=75)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(
            self.times(result.plan),
            [
                (at(1, 18), at(1, 18, 30)),
                (at(1, 18, 40), at(1, 19, 10)),
                (at(1, 19, 20), at(1, 19, 35)),
            ],
        )
        self.assert_valid_plan(result.plan)

    def test_task_spreads_across_blocks_and_days(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(18, 30))
        self.one_time(datetime.date(2026, 10, 2), datetime.time(9), datetime.time(9, 30))
        self.make_task(self.make_assignment(at(5, 12)), minutes=60)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(
            self.times(result.plan),
            [(at(1, 18), at(1, 18, 30)), (at(2, 9), at(2, 9, 30))],
        )
        self.assertEqual(result.plan.end_date, datetime.date(2026, 10, 2))

    def test_session_may_end_exactly_at_due_time(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        self.make_task(self.make_assignment(at(1, 18, 30)), minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.unscheduled, [])
        self.assertEqual(self.times(result.plan), [(at(1, 18), at(1, 18, 30))])

    def test_nothing_is_scheduled_after_the_due_date(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        self.one_time(datetime.date(2026, 10, 3), datetime.time(18), datetime.time(19))
        task = self.make_task(self.make_assignment(at(1, 18, 20)), minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        self.assertEqual([(u.task, u.reason) for u in result.unscheduled], [(task, NOT_ENOUGH_TIME)])

    def test_tasks_do_not_overlap(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(20))
        assignment = self.make_assignment(at(5, 12))
        for _ in range(4):
            self.make_task(assignment, minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 4)
        self.assert_valid_plan(result.plan)

    def test_overlapping_blocks_are_merged(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        self.weekly(AvailabilityBlock.Weekday.THURSDAY, datetime.time(18, 30), datetime.time(19, 30))
        assignment = self.make_assignment(at(1, 23))
        for _ in range(3):
            self.make_task(assignment, minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(
            self.times(result.plan),
            [
                (at(1, 18), at(1, 18, 30)),
                (at(1, 18, 30), at(1, 19)),
                (at(1, 19), at(1, 19, 30)),
            ],
        )
        self.assert_valid_plan(result.plan)

    def test_earliest_due_date_is_scheduled_first(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        later = self.make_task(self.make_assignment(at(9, 12)), description='Later')
        sooner = self.make_task(self.make_assignment(at(2, 12)), description='Sooner')

        result = generate_plan(self.user, now=NOW)

        self.assertEqual([s.task_item for s in self.sessions(result.plan)], [sooner, later])

    def test_checklist_order_is_kept_within_an_assignment(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        assignment = self.make_assignment(at(5, 12))
        second = self.make_task(assignment, order=1, description='Second')
        first = self.make_task(assignment, order=0, description='First')

        result = generate_plan(self.user, now=NOW)

        self.assertEqual([s.task_item for s in self.sessions(result.plan)], [first, second])

    def test_task_too_large_is_reported_without_partial_sessions(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        big = self.make_task(self.make_assignment(at(2, 12)), minutes=90, description='Big')
        small = self.make_task(self.make_assignment(at(3, 12)), minutes=30, description='Small')

        result = generate_plan(self.user, now=NOW)

        self.assertEqual([(u.task, u.reason) for u in result.unscheduled], [(big, NOT_ENOUGH_TIME)])
        self.assertFalse(result.plan.sessions.filter(task_item=big).exists())
        self.assertEqual([s.task_item for s in self.sessions(result.plan)], [small])
        self.assertEqual(self.times(result.plan), [(at(1, 18), at(1, 18, 30))])

    def test_no_availability_reports_every_task(self):
        tasks = [self.make_task(self.make_assignment(at(5, 12))) for _ in range(2)]

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        self.assertEqual(
            [(u.task, u.reason) for u in result.unscheduled],
            [(task, NOT_ENOUGH_TIME) for task in tasks],
        )

    def test_no_due_date_and_past_due_are_reported(self):
        self.weekly(AvailabilityBlock.Weekday.THURSDAY, datetime.time(18), datetime.time(20))
        no_due = self.make_task(self.make_assignment(None))
        past_due = self.make_task(self.make_assignment(at(1, 7)))

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        reasons = {u.task: u.reason for u in result.unscheduled}
        self.assertEqual(reasons, {no_due: NO_DUE_DATE, past_due: PAST_DUE})

    def test_completed_and_inactive_tasks_are_ignored(self):
        self.weekly(AvailabilityBlock.Weekday.THURSDAY, datetime.time(18), datetime.time(20))
        due = at(5, 12)
        self.make_task(self.make_assignment(due), is_completed=True)
        self.make_task(self.make_assignment(due, is_active=False))
        inactive_course = Course.objects.create(
            user=self.user, canvas_course_id=2, name='Old', is_active=False
        )
        self.make_task(self.make_assignment(due, course=inactive_course))

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        self.assertEqual(result.unscheduled, [])

    def test_weekly_block_repeats_each_week(self):
        self.weekly(AvailabilityBlock.Weekday.MONDAY, datetime.time(18), datetime.time(18, 30))
        self.make_task(self.make_assignment(at(13, 12)), minutes=60)

        result = generate_plan(self.user, now=NOW)

        # Mondays after Thursday Oct 1 are Oct 5 and Oct 12.
        self.assertEqual(
            self.times(result.plan),
            [(at(5, 18), at(5, 18, 30)), (at(12, 18), at(12, 18, 30))],
        )

    def test_past_one_time_block_is_ignored(self):
        self.one_time(datetime.date(2026, 9, 30), datetime.time(18), datetime.time(19))
        task = self.make_task(self.make_assignment(at(5, 12)))

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        self.assertEqual([u.task for u in result.unscheduled], [task])

    def test_today_starts_from_the_current_time(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(7), datetime.time(9))
        self.make_task(self.make_assignment(at(5, 12)), minutes=30)

        result = generate_plan(self.user, now=at(1, 8, 15))

        self.assertEqual(self.times(result.plan), [(at(1, 8, 15), at(1, 8, 45))])

    def test_availability_uses_the_students_timezone(self):
        self.set_profile(timezone='America/New_York')
        # 6 PM in New York on Oct 1 is 22:00 UTC (EDT, UTC-4).
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        self.make_task(self.make_assignment(at(5, 12)), minutes=30)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(self.times(result.plan), [(at(1, 22), at(1, 22, 30))])
        self.assert_valid_plan(result.plan)

    def test_weekly_block_across_daylight_saving_change(self):
        self.set_profile(timezone='America/New_York')
        # DST ends Sunday Nov 1 2026: 6 PM is 22:00 UTC before and 23:00 UTC after.
        self.weekly(AvailabilityBlock.Weekday.SATURDAY, datetime.time(18), datetime.time(18, 30))
        self.weekly(AvailabilityBlock.Weekday.MONDAY, datetime.time(18), datetime.time(18, 30))
        self.make_task(self.make_assignment(datetime.datetime(2026, 11, 3, tzinfo=UTC)), minutes=60)

        result = generate_plan(self.user, now=datetime.datetime(2026, 10, 31, 12, tzinfo=UTC))

        self.assertEqual(
            self.times(result.plan),
            [
                (datetime.datetime(2026, 10, 31, 22, tzinfo=UTC), datetime.datetime(2026, 10, 31, 22, 30, tzinfo=UTC)),
                (datetime.datetime(2026, 11, 2, 23, tzinfo=UTC), datetime.datetime(2026, 11, 2, 23, 30, tzinfo=UTC)),
            ],
        )
        self.assert_valid_plan(result.plan)

    def test_regenerating_deactivates_the_previous_plan(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        self.make_task(self.make_assignment(at(5, 12)))

        first = generate_plan(self.user, now=NOW).plan
        second = generate_plan(self.user, now=NOW).plan

        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(StudyPlan.objects.filter(user=self.user, is_active=True).get(), second)

    def test_regenerating_keeps_completed_sessions_and_schedules_the_rest(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(20))
        task = self.make_task(self.make_assignment(at(5, 12)), minutes=60)
        first = generate_plan(self.user, now=NOW).plan
        done = first.sessions.order_by('scheduled_start').first()
        done.is_completed = True
        done.save()

        second = generate_plan(self.user, now=NOW).plan

        sessions = self.sessions(second)
        self.assertEqual([s.task_item for s in sessions], [task, task])
        self.assertEqual(
            [(s.scheduled_start, s.scheduled_end, s.is_completed) for s in sessions],
            [(at(1, 18), at(1, 18, 30), True), (at(1, 18, 30), at(1, 19), False)],
        )
        self.assert_valid_plan(second)

    def test_other_users_tasks_and_availability_are_not_used(self):
        other = User.objects.create_user(username='other', password='test-pass-123')
        other_course = Course.objects.create(user=other, canvas_course_id=99, name='Theirs')
        other_assignment = self.make_assignment(at(5, 12), course=other_course)
        self.make_task(other_assignment, user=other)
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19), user=other)
        mine = self.make_task(self.make_assignment(at(5, 12)))
        # A task the student owns that sits on someone else's assignment.
        self.make_task(other_assignment)

        result = generate_plan(self.user, now=NOW)

        self.assertEqual(result.plan.sessions.count(), 0)
        self.assertEqual([u.task for u in result.unscheduled], [mine])
        self.assertFalse(StudyPlan.objects.filter(user=other).exists())


class FindUnscheduledTests(SchedulingTestCase):
    def test_reports_tasks_missing_from_the_plan(self):
        self.one_time(datetime.date(2026, 10, 1), datetime.time(18), datetime.time(19))
        planned = self.make_task(self.make_assignment(at(5, 12)))
        no_due = self.make_task(self.make_assignment(None))
        plan = generate_plan(self.user, now=NOW).plan
        added_later = self.make_task(self.make_assignment(at(6, 12)))

        reasons = {u.task: u.reason for u in find_unscheduled(self.user, plan, now=NOW)}

        self.assertNotIn(planned, reasons)
        self.assertEqual(reasons, {no_due: NO_DUE_DATE, added_later: NOT_IN_PLAN})

    def test_without_a_plan_every_eligible_task_is_listed(self):
        task = self.make_task(self.make_assignment(at(5, 12)))

        unscheduled = find_unscheduled(self.user, None, now=NOW)

        self.assertEqual([(u.task, u.reason) for u in unscheduled], [(task, NOT_IN_PLAN)])
        self.assertFalse(PlanSession.objects.exists())
