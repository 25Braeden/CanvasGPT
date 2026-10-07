from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class User(AbstractUser):
    pass


class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_profile',
    )
    timezone = models.CharField(max_length=64, default='UTC')
    preferred_session_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
    )
    break_minutes = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(0)],
    )
    daily_study_goal_minutes = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1)],
    )
    notifications_enabled = models.BooleanField(default=True)
    dark_mode_enabled = models.BooleanField(default=False)
    due_soon_days = models.PositiveIntegerField(
        default=7,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
        help_text='Assignments due today through this many days ahead are due soon.',
    )

    def __str__(self):
        return f"{self.user.username}'s student profile"
