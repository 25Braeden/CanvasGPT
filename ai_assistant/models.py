from django.conf import settings
from django.db import models


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
