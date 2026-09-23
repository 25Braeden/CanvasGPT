import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from ai_assistant.models import TaskItem
from canvas_sync.models import Assignment, Course

from .models import AvailabilityBlock, PlanSession, StudyPlan

User = get_user_model()


class AvailabilityBlockModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='braeden', password='test-pass-123'
        )

    def test_recurring_block_with_weekday(self):
        block = AvailabilityBlock(
            user=self.user,
            weekday=AvailabilityBlock.Weekday.MONDAY,
            start_time=datetime.time(18, 0),
            end_time=datetime.time(20, 0),
            recurrence=AvailabilityBlock.Recurrence.WEEKLY,
        )
        block.full_clean()
        block.save()
        self.assertEqual(block.recurrence, AvailabilityBlock.Recurrence.WEEKLY)

    def test_one_time_block_with_specific_date(self):
        block = AvailabilityBlock(
            user=self.user,
            date=datetime.date(2026, 9, 18),
            start_time=datetime.time(16, 0),
            end_time=datetime.time(17, 30),
            recurrence=AvailabilityBlock.Recurrence.NONE,
        )
        block.full_clean()
        block.save()
        self.assertIsNotNone(block.pk)

    def test_date_and_weekday_cannot_both_be_set(self):
        block = AvailabilityBlock(
            user=self.user,
            date=datetime.date(2026, 9, 18),
            weekday=AvailabilityBlock.Weekday.FRIDAY,
            start_time=datetime.time(16, 0),
            end_time=datetime.time(17, 0),
        )
        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_date_and_weekday_cannot_both_be_blank(self):
        block = AvailabilityBlock(
            user=self.user,
            start_time=datetime.time(16, 0),
            end_time=datetime.time(17, 0),
        )
        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_weekly_recurrence_requires_weekday_not_date(self):
        block = AvailabilityBlock(
            user=self.user,
            date=datetime.date(2026, 9, 18),
            start_time=datetime.time(16, 0),
            end_time=datetime.time(17, 0),
            recurrence=AvailabilityBlock.Recurrence.WEEKLY,
        )
        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_end_time_must_be_after_start_time(self):
        block = AvailabilityBlock(
            user=self.user,
            weekday=AvailabilityBlock.Weekday.MONDAY,
            start_time=datetime.time(20, 0),
            end_time=datetime.time(18, 0),
        )
        with self.assertRaises(ValidationError):
            block.full_clean()

    def test_recurrence_defaults_to_weekly(self):
        block = AvailabilityBlock(
            user=self.user,
            weekday=AvailabilityBlock.Weekday.TUESDAY,
            start_time=datetime.time(18, 0),
            end_time=datetime.time(19, 0),
        )
        self.assertEqual(block.recurrence, AvailabilityBlock.Recurrence.WEEKLY)

    def test_user_delete_cascades_to_blocks(self):
        AvailabilityBlock.objects.create(
            user=self.user,
            weekday=AvailabilityBlock.Weekday.MONDAY,
            start_time=datetime.time(18, 0),
            end_time=datetime.time(19, 0),
        )
        self.user.delete()
        self.assertEqual(AvailabilityBlock.objects.count(), 0)

    def test_block_str(self):
        block = AvailabilityBlock(
            user=self.user,
            weekday=AvailabilityBlock.Weekday.WEDNESDAY,
            start_time=datetime.time(18, 30),
            end_time=datetime.time(20, 0),
        )
        self.assertEqual(str(block), 'Wednesday 18:30-20:00')


class StudyPlanModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='braeden', password='test-pass-123'
        )

    def create_plan(self, **kwargs):
        defaults = {
            'user': self.user,
            'start_date': datetime.date(2026, 9, 14),
            'end_date': datetime.date(2026, 9, 20),
        }
        defaults.update(kwargs)
        return StudyPlan.objects.create(**defaults)

    def test_study_plan_creation(self):
        plan = self.create_plan()
        self.assertTrue(plan.is_active)
        self.assertIsNotNone(plan.created_at)
        self.assertEqual(plan.start_date, datetime.date(2026, 9, 14))
        self.assertEqual(plan.end_date, datetime.date(2026, 9, 20))

    def test_end_date_before_start_date_rejected(self):
        plan = StudyPlan(
            user=self.user,
            start_date=datetime.date(2026, 9, 20),
            end_date=datetime.date(2026, 9, 14),
        )
        with self.assertRaises(ValidationError):
            plan.full_clean()

    def test_plans_listed_newest_first(self):
        older = self.create_plan()
        newer = self.create_plan()
        self.assertEqual(list(StudyPlan.objects.all()), [newer, older])

    def test_plan_str(self):
        plan = self.create_plan()
        self.assertEqual(
            str(plan), f'Study plan 2026-09-14 to 2026-09-20 ({self.user})'
        )


class PlanSessionModelTests(TestCase):
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
        self.task = TaskItem.objects.create(
            assignment=self.assignment,
            user=self.user,
            description='Draft outline',
            estimated_minutes=45,
            order=1,
        )
        self.plan = StudyPlan.objects.create(
            user=self.user,
            start_date=datetime.date(2026, 9, 14),
            end_date=datetime.date(2026, 9, 20),
        )

    def create_session(self, **kwargs):
        defaults = {
            'study_plan': self.plan,
            'task_item': self.task,
            'scheduled_start': timezone.make_aware(datetime.datetime(2026, 9, 15, 18, 0)),
            'scheduled_end': timezone.make_aware(datetime.datetime(2026, 9, 15, 19, 0)),
        }
        defaults.update(kwargs)
        return PlanSession.objects.create(**defaults)

    def test_plan_session_creation(self):
        session = self.create_session()
        self.assertFalse(session.is_completed)

    def test_scheduled_end_must_be_after_start(self):
        session = PlanSession(
            study_plan=self.plan,
            task_item=self.task,
            scheduled_start=timezone.make_aware(datetime.datetime(2026, 9, 15, 19, 0)),
            scheduled_end=timezone.make_aware(datetime.datetime(2026, 9, 15, 18, 0)),
        )
        with self.assertRaises(ValidationError):
            session.full_clean()

    def test_sessions_ordered_by_scheduled_start(self):
        later = self.create_session(
            scheduled_start=timezone.make_aware(datetime.datetime(2026, 9, 16, 18, 0)),
            scheduled_end=timezone.make_aware(datetime.datetime(2026, 9, 16, 19, 0)),
        )
        earlier = self.create_session(
            scheduled_start=timezone.make_aware(datetime.datetime(2026, 9, 15, 9, 0)),
            scheduled_end=timezone.make_aware(datetime.datetime(2026, 9, 15, 10, 0)),
        )
        self.assertEqual(list(PlanSession.objects.all()), [earlier, later])

    def test_study_plan_delete_cascades_to_sessions(self):
        self.create_session()
        self.plan.delete()
        self.assertEqual(PlanSession.objects.count(), 0)

    def test_task_item_delete_cascades_to_sessions(self):
        self.create_session()
        self.task.delete()
        self.assertEqual(PlanSession.objects.count(), 0)

    def test_session_str(self):
        session = self.create_session()
        self.assertEqual(str(session), 'Draft outline at 2026-09-15 18:00')
