from django.conf import settings
from django.db import models

class CanvasConnection(models.Model):
    class SyncStatus(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="canvas_connection",
    )
    canvas_base_url = models.URLField()
    access_token = models.CharField(max_length=255)
    sync_status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
    )
    sync_error_message = models.TextField(blank=True)
    last_synchronized_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username}'s Canvas connection"


class Course(models.Model):
    """A Canvas course imported for a student."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='courses',
    )
    canvas_course_id = models.BigIntegerField()
    name = models.CharField(max_length=255)
    course_code = models.CharField(max_length=50, blank=True)
    term = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "canvas_course_id"),
                name="unique_canvas_course_per_user",
            ),
        ]

    def __str__(self):
        return self.name


class Assignment(models.Model):
    """A Canvas assignment belonging to an imported course."""

    class SyncStatus(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='assignments',
    )
    canvas_assignment_id = models.BigIntegerField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    points_possible = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    submission_url = models.URLField(blank=True)
    sync_status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.SUCCESS,
    )
    sync_error_message = models.TextField(blank=True)
    last_synchronized_at = models.DateTimeField(
        auto_now=True,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("course", "canvas_assignment_id"),
                name="unique_canvas_assignment_per_course",
            ),
        ]

    def __str__(self):
        return self.title


class RubricCriterion(models.Model):
    """One criterion from a Canvas assignment rubric."""

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name='rubric_criteria',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    points = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    canvas_rubric_criterion_id = models.BigIntegerField(
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("assignment", "canvas_rubric_criterion_id"),
                condition=models.Q(canvas_rubric_criterion_id__isnull=False),
                name="unique_canvas_rubric_criterion_per_assignment",
            ),
        ]

    def __str__(self):
        return self.title
