from django.conf import settings
from django.db import models


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

    def __str__(self):
        return self.name


class Assignment(models.Model):
    """A Canvas assignment belonging to an imported course."""

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
    last_synchronized_at = models.DateTimeField(auto_now=True)

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

    def __str__(self):
        return self.title
