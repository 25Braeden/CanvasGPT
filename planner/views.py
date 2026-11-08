from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import StudentProfile

from .forms import AvailabilityBlockForm
from .models import AvailabilityBlock, PlanSession, StudyPlan
from .scheduling import find_unscheduled, generate_plan, student_timezone


def _get_block(request, pk):
    return get_object_or_404(AvailabilityBlock, pk=pk, user=request.user)


def _get_session(request, pk):
    return get_object_or_404(
        PlanSession.objects.select_related('study_plan', 'task_item'),
        pk=pk,
        study_plan__user=request.user,
        task_item__user=request.user,
    )


def _timezone_for(user):
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    return student_timezone(profile)


@login_required
def availability_list(request):
    tz = _timezone_for(request.user)
    today = timezone.localdate(timezone=tz)
    blocks = AvailabilityBlock.objects.filter(user=request.user)
    return render(
        request,
        'planner/availability_list.html',
        {
            'weekly_blocks': blocks.filter(date__isnull=True).order_by('weekday', 'start_time'),
            'one_time_blocks': blocks.filter(date__gte=today).order_by('date', 'start_time'),
        },
    )


@login_required
def availability_add(request):
    block = AvailabilityBlock(user=request.user)
    form = AvailabilityBlockForm(request.POST or None, instance=block)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('planner:availability_list')
    status = 400 if request.method == 'POST' else 200
    return render(
        request,
        'planner/availability_form.html',
        {'form': form, 'is_new': True},
        status=status,
    )


@login_required
def availability_edit(request, pk):
    block = _get_block(request, pk)
    form = AvailabilityBlockForm(request.POST or None, instance=block)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('planner:availability_list')
    status = 400 if request.method == 'POST' else 200
    return render(
        request,
        'planner/availability_form.html',
        {'form': form, 'is_new': False},
        status=status,
    )


@login_required
@require_POST
def availability_delete(request, pk):
    _get_block(request, pk).delete()
    return redirect('planner:availability_list')


def _selected_week(value, today):
    """Resolve an ISO date to Monday, falling back for unsafe date ranges."""
    try:
        selected = date.fromisoformat(value)
        if selected.isoformat() != value or not 2 <= selected.year <= 9998:
            raise ValueError
    except (TypeError, ValueError):
        selected = today
    return selected - timedelta(days=selected.weekday())


@login_required
def plan_detail(request):
    tz = _timezone_for(request.user)
    today = timezone.localdate(timezone=tz)
    week_start = _selected_week(request.GET.get('week'), today)
    next_week = week_start + timedelta(days=7)
    # Construct each local midnight separately: a DST week need not be 168 hours.
    starts_at = timezone.make_aware(datetime.combine(week_start, time.min), tz)
    ends_at = timezone.make_aware(datetime.combine(next_week, time.min), tz)
    plan = StudyPlan.objects.filter(user=request.user, is_active=True).first()
    sessions_by_day = {
        week_start + timedelta(days=offset): [] for offset in range(7)
    }
    unscheduled = find_unscheduled(request.user, plan)
    plan_summary = None
    if plan:
        plan_sessions = plan.sessions.filter(
            task_item__user=request.user,
            task_item__assignment__course__user=request.user,
        )
        duration = F('scheduled_end') - F('scheduled_start')
        totals = plan_sessions.aggregate(
            unfinished=Sum(duration, filter=Q(is_completed=False)),
            completed=Sum(duration, filter=Q(is_completed=True)),
        )
        # These totals cover the whole active plan, independent of week navigation.
        plan_summary = {
            'scheduled_unfinished_minutes': int(
                (totals['unfinished'] or timedelta()).total_seconds() // 60
            ),
            'completed_session_minutes': int(
                (totals['completed'] or timedelta()).total_seconds() // 60
            ),
            'unscheduled_task_count': len(unscheduled),
        }
        sessions = plan_sessions.select_related(
            'task_item', 'task_item__assignment'
        ).filter(
            scheduled_start__gte=starts_at,
            scheduled_start__lt=ends_at,
        ).order_by('scheduled_start', 'pk')
        for session in sessions:
            day = timezone.localtime(session.scheduled_start, tz).date()
            sessions_by_day[day].append(session)
    days = list(sessions_by_day.items())
    return render(
        request,
        'planner/plan_detail.html',
        {
            'plan': plan,
            'days': days,
            'week_start': week_start,
            'week_end': next_week - timedelta(days=1),
            'previous_week': week_start - timedelta(days=7),
            'next_week': next_week,
            'current_week': today - timedelta(days=today.weekday()),
            'unscheduled': unscheduled,
            'plan_summary': plan_summary,
            'student_timezone': tz,
            'has_availability': AvailabilityBlock.objects.filter(user=request.user).exists(),
        },
    )


def _back_to_week(request):
    url = reverse('planner:plan_detail')
    if 'week' in request.POST:
        today = timezone.localdate(timezone=_timezone_for(request.user))
        week = _selected_week(request.POST['week'], today)
        url += '?' + urlencode({'week': week.isoformat()})
    return redirect(url)


@login_required
@require_POST
def plan_generate(request):
    generate_plan(request.user)
    return _back_to_week(request)


@login_required
@require_POST
def session_toggle(request, pk):
    session = _get_session(request, pk)
    with transaction.atomic():
        session.is_completed = not session.is_completed
        session.save(update_fields=['is_completed'])
        task = session.task_item
        task.is_completed = not task.plan_sessions.filter(
            study_plan=session.study_plan, is_completed=False
        ).exists()
        task.save(update_fields=['is_completed'])
    return _back_to_week(request)
