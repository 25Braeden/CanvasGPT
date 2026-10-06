from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from ai_assistant.forms import TaskItemForm

from .models import Assignment

STALE_AFTER = timedelta(hours=24)


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.select_related('course').prefetch_related('rubric_criteria'),
        pk=pk,
        course__user=request.user,
    )

    return render(
        request,
        'canvas_sync/assignment_detail.html',
        {
            'assignment': assignment,
            'task_items': assignment.task_items.filter(user=request.user),
            'task_form': TaskItemForm(),
        },
    )


def get_assignment_sync_status(assignment):
    if not assignment.last_synchronized_at:
        return {
            'level': 'warning',
            'label': 'Not synced yet',
            'message': 'Canvas data has not been synchronized for this assignment yet.',
        }

    age = timezone.now() - assignment.last_synchronized_at
    if age > STALE_AFTER:
        return {
            'level': 'warning',
            'label': 'Sync may be stale',
            'message': 'This assignment was last synced more than 24 hours ago. Details may have changed in Canvas.',
        }

    return {
        'level': 'success',
        'label': 'Up to date',
        'message': 'This assignment was recently synchronized with Canvas.',
    }
