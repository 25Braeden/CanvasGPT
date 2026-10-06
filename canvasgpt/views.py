from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from canvas_sync.models import Assignment

STALE_AFTER = timedelta(hours=24)


def home(request):
    return render(request, 'home.html')


@login_required
def dashboard(request):
    is_new_user = request.session.pop('new_user', False)
    assignments = (
        Assignment.objects.select_related('course')
        .filter(course__user=request.user)
        .order_by('due_at', 'course__name', 'title')
    )
    sync_status = get_dashboard_sync_status(assignments)
    return render(
        request,
        'dashboard.html',
        {
            'is_new_user': is_new_user,
            'assignments': assignments,
            'sync_status': sync_status,
        },
    )


def get_dashboard_sync_status(assignments):
    assignment_list = list(assignments)
    if not assignment_list:
        return {
            'level': 'warning',
            'label': 'No synced assignments yet',
            'message': 'Canvas assignment data has not been synchronized for this account yet.',
        }

    failed_assignments = [
        assignment
        for assignment in assignment_list
        if assignment.sync_status == Assignment.SyncStatus.FAILED
    ]
    if failed_assignments:
        error_messages = [
            assignment.sync_error_message
            for assignment in failed_assignments
            if assignment.sync_error_message
        ]
        return {
            'level': 'error',
            'label': 'Sync failed',
            'message': error_messages[0] if error_messages else 'Canvas synchronization failed for one or more assignments.',
        }

    last_synced_values = [assignment.last_synchronized_at for assignment in assignment_list]
    if any(value is None for value in last_synced_values):
        return {
            'level': 'warning',
            'label': 'Sync incomplete',
            'message': 'Some Canvas assignment data is missing a sync timestamp.',
        }

    latest_sync = max(last_synced_values)
    oldest_sync = min(last_synced_values)
    if timezone.now() - oldest_sync > STALE_AFTER:
        return {
            'level': 'warning',
            'label': 'Sync may be stale',
            'message': 'Some Canvas assignment data was synced more than 24 hours ago.',
            'last_synced': latest_sync,
        }

    return {
        'level': 'success',
        'label': 'Up to date',
        'message': 'Canvas assignment data was recently synchronized.',
        'last_synced': latest_sync,
    }
