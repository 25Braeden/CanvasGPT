"""Study plan generation.

Places a student's incomplete checklist tasks into their availability,
earliest due date first, so that every session finishes before the
assignment is due, no two sessions overlap, and nothing is scheduled
outside the student's availability. Tasks that can't be fully placed are
reported back instead of being dropped.
"""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from accounts.models import StudentProfile
from ai_assistant.models import TaskItem

from .models import AvailabilityBlock, PlanSession, StudyPlan

UTC = datetime.timezone.utc

NO_DUE_DATE = 'This assignment has no due date, so it can’t be scheduled before one.'
PAST_DUE = 'This assignment is already past due.'
NOT_ENOUGH_TIME = 'There isn’t enough free time in your availability before the due date.'
NOT_IN_PLAN = (
    'Not in your current plan. There wasn’t enough free time before the due '
    'date, or the task was added after the plan was generated.'
)


@dataclass
class UnscheduledTask:
    task: TaskItem
    reason: str


@dataclass
class PlanResult:
    plan: StudyPlan
    unscheduled: list


def student_timezone(profile):
    try:
        return ZoneInfo(profile.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.get_current_timezone()


def eligible_tasks(user):
    """Incomplete tasks the student owns on active assignments, in priority order."""
    return list(
        TaskItem.objects.select_related('assignment', 'assignment__course')
        .filter(
            user=user,
            assignment__course__user=user,
            is_completed=False,
            assignment__is_active=True,
            assignment__course__is_active=True,
        )
        .order_by('assignment__due_at', 'assignment_id', 'order', 'id')
    )


def unschedulable_reason(task, now):
    """Why a task can never be scheduled, or None if it could be."""
    if task.assignment.due_at is None:
        return NO_DUE_DATE
    if task.assignment.due_at <= now:
        return PAST_DUE
    return None


def availability_windows(user, start, end, tz):
    """Free time between start and end as sorted, non-overlapping UTC intervals.

    Weekly blocks repeat on their weekday and one-time blocks apply on their
    date; times are read in the student's timezone. Overlapping or touching
    blocks are merged so they can never produce overlapping sessions.
    """
    blocks = list(AvailabilityBlock.objects.filter(user=user))
    windows = []
    day = start.astimezone(tz).date()
    last_day = end.astimezone(tz).date()
    while day <= last_day:
        for block in blocks:
            if block.date is not None:
                applies = block.date == day
            else:
                applies = block.weekday == day.weekday()
            if not applies:
                continue
            window_start = max(_to_utc(day, block.start_time, tz), start)
            window_end = min(_to_utc(day, block.end_time, tz), end)
            if window_start < window_end:
                windows.append((window_start, window_end))
        day += datetime.timedelta(days=1)
    return _merge(windows)


def _to_utc(day, time_of_day, tz):
    # Converting to UTC right away keeps arithmetic correct across DST changes.
    return datetime.datetime.combine(day, time_of_day, tzinfo=tz).astimezone(UTC)


def _merge(windows):
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(windows, busy):
    """Remove busy intervals from the free windows."""
    for busy_start, busy_end in busy:
        remaining = []
        for start, end in windows:
            if busy_end <= start or busy_start >= end:
                remaining.append((start, end))
                continue
            if start < busy_start:
                remaining.append((start, busy_start))
            if busy_end < end:
                remaining.append((busy_end, end))
        windows = remaining
    return windows


def _place_task(windows, minutes, session_length, break_length, deadline):
    """Fit a task into the free windows, all or nothing.

    Returns (sessions, updated_windows), or (None, windows) if the task
    doesn't fit before the deadline. Each session is at most session_length
    long, and a break is left after each session before the next one in the
    same window.
    """
    free = list(windows)
    sessions = []
    remaining = minutes
    index = 0
    while remaining > 0:
        length = datetime.timedelta(minutes=min(session_length, remaining))
        while index < len(free):
            start, end = free[index]
            if start + length <= min(end, deadline):
                break
            if start >= deadline:
                return None, windows
            index += 1
        else:
            return None, windows
        session_end = start + length
        sessions.append((start, session_end))
        next_free = session_end + datetime.timedelta(minutes=break_length)
        if next_free < end:
            free[index] = (next_free, end)
        else:
            del free[index]
        remaining -= int(length.total_seconds() // 60)
    return sessions, free


def generate_plan(user, now=None):
    """Build a new active StudyPlan for the user and return it with unscheduled tasks.

    Sessions already marked complete in the current plan are kept: their
    time stays blocked and their minutes count toward the task's estimate.
    """
    now = now or timezone.now()
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    tz = student_timezone(profile)

    previous = StudyPlan.objects.filter(user=user, is_active=True).first()
    kept_sessions = []
    if previous:
        kept_sessions = list(
            previous.sessions.filter(is_completed=True, task_item__user=user)
        )
    completed_minutes = {}
    for session in kept_sessions:
        minutes = int((session.scheduled_end - session.scheduled_start).total_seconds() // 60)
        completed_minutes[session.task_item_id] = (
            completed_minutes.get(session.task_item_id, 0) + minutes
        )

    tasks = eligible_tasks(user)
    unscheduled = []
    schedulable = []
    for task in tasks:
        reason = unschedulable_reason(task, now)
        if reason:
            unscheduled.append(UnscheduledTask(task, reason))
        else:
            schedulable.append(task)

    windows = []
    if schedulable:
        horizon = max(task.assignment.due_at for task in schedulable)
        windows = availability_windows(user, now, horizon, tz)
        windows = _subtract(
            windows,
            [(s.scheduled_start, s.scheduled_end) for s in kept_sessions],
        )

    placements = []
    for task in schedulable:
        minutes = task.estimated_minutes - completed_minutes.get(task.pk, 0)
        if minutes <= 0:
            continue
        sessions, windows = _place_task(
            windows,
            minutes,
            profile.preferred_session_minutes,
            profile.break_minutes,
            task.assignment.due_at,
        )
        if sessions is None:
            unscheduled.append(UnscheduledTask(task, NOT_ENOUGH_TIME))
        else:
            placements.extend((task, start, end) for start, end in sessions)

    today = timezone.localdate(now, timezone=tz)
    dates = [today]
    dates += [timezone.localtime(start, tz).date() for _, start, _ in placements]
    dates += [timezone.localtime(s.scheduled_start, tz).date() for s in kept_sessions]

    with transaction.atomic():
        StudyPlan.objects.filter(user=user, is_active=True).update(is_active=False)
        plan = StudyPlan.objects.create(
            user=user,
            start_date=min(dates),
            end_date=max(dates),
            is_active=True,
        )
        PlanSession.objects.bulk_create(
            [
                PlanSession(
                    study_plan=plan,
                    task_item_id=session.task_item_id,
                    scheduled_start=session.scheduled_start,
                    scheduled_end=session.scheduled_end,
                    is_completed=True,
                )
                for session in kept_sessions
            ]
            + [
                PlanSession(
                    study_plan=plan,
                    task_item=task,
                    scheduled_start=start,
                    scheduled_end=end,
                )
                for task, start, end in placements
            ]
        )
    return PlanResult(plan, unscheduled)


def find_unscheduled(user, plan, now=None):
    """Eligible tasks with no session in the given plan, with a reason for each."""
    now = now or timezone.now()
    planned_ids = set()
    if plan:
        planned_ids = set(plan.sessions.values_list('task_item_id', flat=True))
    unscheduled = []
    for task in eligible_tasks(user):
        if task.pk in planned_ids:
            continue
        reason = unschedulable_reason(task, now) or NOT_IN_PLAN
        unscheduled.append(UnscheduledTask(task, reason))
    return unscheduled
