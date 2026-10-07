from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from accounts.models import StudentProfile
from canvas_sync.models import Assignment, CanvasConnection

STALE_AFTER = timedelta(hours=24)


def home(request):
    return render(request, 'home.html')


@login_required
def dashboard(request):
    is_new_user = request.session.pop('new_user', False)
    all_assignments = list(
        Assignment.objects.select_related('course')
        .filter(course__user=request.user)
        .order_by('due_at', 'course__name', 'title')
    )
    assignments = [
        assignment
        for assignment in all_assignments
        if assignment.course.is_visible
    ]
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    due_soon, due_later, past_due = categorize_assignments(
        assignments,
        profile,
    )
    connection = CanvasConnection.objects.filter(user=request.user).first()
    sync_status = get_dashboard_sync_status(all_assignments, connection)
    return render(
        request,
        'dashboard.html',
        {
            'is_new_user': is_new_user,
            'assignments': assignments,
            'due_soon_assignments': due_soon,
            'due_later_assignments': due_later,
            'past_due_assignments': past_due,
            'due_soon_days': profile.due_soon_days,
            'sync_status': sync_status,
        },
    )


def categorize_assignments(assignments, profile):
    try:
        student_timezone = ZoneInfo(profile.timezone)
    except ZoneInfoNotFoundError:
        student_timezone = timezone.get_current_timezone()

    today = timezone.localdate(timezone=student_timezone)
    due_soon_end = today + timedelta(days=profile.due_soon_days)
    due_soon = []
    due_later = []
    past_due = []

    for assignment in assignments:
        if assignment.due_at is None:
            due_later.append(assignment)
            continue

        due_date = timezone.localtime(
            assignment.due_at,
            student_timezone,
        ).date()
        if due_date < today:
            past_due.append(assignment)
        elif due_date <= due_soon_end:
            due_soon.append(assignment)
        else:
            due_later.append(assignment)

    return due_soon, due_later, past_due


def get_dashboard_sync_status(assignments, connection=None):
    assignment_list = list(assignments)

    if connection and connection.sync_status == CanvasConnection.SyncStatus.FAILED:
        return {
            'level': 'error',
            'label': 'Sync failed',
            'message': connection.sync_error_message or 'Canvas synchronization failed. Check your Canvas connection.',
        }

    if not assignment_list:
        if connection and connection.sync_status == CanvasConnection.SyncStatus.SUCCESS:
            return {
                'level': 'success',
                'label': 'Up to date',
                'message': 'Canvas data was recently synchronized. No active assignments were found.',
                'last_synced': connection.last_synchronized_at,
            }
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
