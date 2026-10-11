from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
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


@login_required
def plan_detail(request):
    tz = _timezone_for(request.user)
    plan = StudyPlan.objects.filter(user=request.user, is_active=True).first()
    days = []
    if plan:
        sessions = plan.sessions.select_related(
            'task_item', 'task_item__assignment'
        ).filter(task_item__user=request.user)
        days = [
            (day, list(day_sessions))
            for day, day_sessions in groupby(
                sessions,
                key=lambda s: timezone.localtime(s.scheduled_start, tz).date(),
            )
        ]
    return render(
        request,
        'planner/plan_detail.html',
        {
            'plan': plan,
            'days': days,
            'unscheduled': find_unscheduled(request.user, plan),
            'student_timezone': tz,
            'has_availability': AvailabilityBlock.objects.filter(user=request.user).exists(),
        },
    )


@login_required
@require_POST
def plan_generate(request):
    generate_plan(request.user)
    return redirect('planner:plan_detail')


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
    return redirect('planner:plan_detail')
