import json
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def suggestion_draft_expiry():
    return timezone.now() + timedelta(hours=24)


class TaskItem(models.Model):
    """One editable step of an assignment checklist.

    Task items may be AI-generated suggestions or student-created tasks;
    both live in the same table so they can be edited, reordered, and
    scheduled together.
    """

    assignment = models.ForeignKey(
        'canvas_sync.Assignment',
        on_delete=models.CASCADE,
        related_name='task_items',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='task_items',
    )
    description = models.CharField(max_length=500)
    estimated_minutes = models.PositiveIntegerField(
        default=30,
        help_text='Estimated time needed to complete this task.',
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text='Position of this task within the assignment checklist.',
    )
    is_completed = models.BooleanField(default=False)
    ai_generated = models.BooleanField(
        default=True,
        help_text='True if this task was suggested by the AI, False if the student added it.',
    )

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.description} ({self.assignment.title})'


class AIRequest(models.Model):
    """Audit log of AI calls made on behalf of a student.

    Only metadata is recorded. Prompt content is deliberately not stored,
    so assignment text never lingers in this table.
    """

    class RequestType(models.TextChoices):
        CHECKLIST_GENERATION = 'checklist_generation', 'Checklist generation'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_requests',
    )
    request_type = models.CharField(max_length=50, choices=RequestType.choices)
    requested_at = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)
    model_name = models.CharField(max_length=100)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'{self.get_request_type_display()} at {self.requested_at:%Y-%m-%d %H:%M}'


class SuggestionDraft(models.Model):
    """Validated, temporary suggestions; never part of the active checklist."""

    class GenerationMode(models.TextChoices):
        DEMO = 'demo', 'Demo'
        OPENAI = 'openai', 'OpenAI'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending review'
        ACCEPTED = 'accepted', 'Accepted'
        DISCARDED = 'discarded', 'Discarded'
        SUPERSEDED = 'superseded', 'Replaced by a newer draft'

    assignment = models.ForeignKey(
        'canvas_sync.Assignment', on_delete=models.CASCADE, related_name='suggestion_drafts',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='suggestion_drafts',
    )
    suggestions = models.JSONField()
    generation_mode = models.CharField(max_length=20, choices=GenerationMode.choices)
    model_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(default=suggestion_draft_expiry, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'assignment'], condition=models.Q(status='pending'),
                name='one_pending_suggestion_draft',
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F('created_at')),
                name='suggestion_draft_positive_lifetime',
            ),
        ]

    @property
    def validated_suggestions(self):
        # Local import avoids a models/services import cycle; reuse one schema.
        from .services import validate_suggestions
        return validate_suggestions(json.dumps({'tasks': self.suggestions}, ensure_ascii=False))

    def clean(self):
        from canvas_sync.models import Assignment
        from .services import InvalidSuggestions

        super().clean()
        if self.assignment_id and self.user_id and not Assignment.objects.filter(
            pk=self.assignment_id, course__user_id=self.user_id,
        ).exists():
            raise ValidationError({'assignment': 'The assignment must belong to the draft owner.'})
        try:
            validated = self.validated_suggestions
        except (InvalidSuggestions, TypeError, ValueError, RecursionError):
            raise ValidationError({'suggestions': 'A draft must contain valid task suggestions.'}) from None
        self.suggestions = [
            {'description': item.description, 'estimated_minutes': item.estimated_minutes}
            for item in validated
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
