from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AvailabilityBlock(models.Model):
    """A span of time during which the student is available to study.

    A block is anchored either to a specific calendar date (one-time
    availability) or to a weekday (recurring availability), never both.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    class Recurrence(models.TextChoices):
        NONE = 'none', 'Does not repeat'
        WEEKLY = 'weekly', 'Repeats weekly'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='availability_blocks',
    )
    date = models.DateField(
        null=True,
        blank=True,
        help_text='Specific calendar date, for one-time availability.',
    )
    weekday = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=Weekday.choices,
        help_text='Day of the week, for recurring availability.',
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    recurrence = models.CharField(
        max_length=20,
        choices=Recurrence.choices,
        default=Recurrence.WEEKLY,
    )

    def clean(self):
        errors = {}
        if self.date and self.weekday is not None:
            errors['weekday'] = 'Set either a specific date or a weekday, not both.'
        if not self.date and self.weekday is None:
            errors['date'] = 'Set a specific date or a weekday.'
        if self.date and self.recurrence == self.Recurrence.WEEKLY:
            errors['recurrence'] = 'Weekly recurrence requires a weekday instead of a specific date.'
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors['end_time'] = 'End time must be after start time.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        day = self.date.isoformat() if self.date else self.get_weekday_display()
        return f'{day} {self.start_time:%H:%M}-{self.end_time:%H:%M}'


class StudyPlan(models.Model):
    """A dated study schedule generated from tasks and availability."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='study_plans',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    start_date = models.DateField(help_text='First day covered by this plan.')
    end_date = models.DateField(help_text='Last day covered by this plan.')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError(
                {'end_date': 'End date must be on or after the start date.'}
            )

    def __str__(self):
        return f'Study plan {self.start_date} to {self.end_date} ({self.user})'


class PlanSession(models.Model):
    """One scheduled work session: a task placed on the calendar."""

    study_plan = models.ForeignKey(
        StudyPlan,
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    task_item = models.ForeignKey(
        'ai_assistant.TaskItem',
        on_delete=models.CASCADE,
        related_name='plan_sessions',
    )
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    is_completed = models.BooleanField(default=False)

    class Meta:
        ordering = ['scheduled_start']

    def clean(self):
        if (
            self.scheduled_start
            and self.scheduled_end
            and self.scheduled_start >= self.scheduled_end
        ):
            raise ValidationError(
                {'scheduled_end': 'Scheduled end must be after scheduled start.'}
            )

    def __str__(self):
        return f'{self.task_item.description} at {self.scheduled_start:%Y-%m-%d %H:%M}'
