from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from canvas_sync.models import Assignment

from .forms import TaskItemForm
from .models import TaskItem


def _get_assignment(request, assignment_pk):
    return get_object_or_404(
        Assignment, pk=assignment_pk, course__user=request.user
    )


def _get_task(request, pk):
    return get_object_or_404(
        TaskItem.objects.select_related('assignment'),
        pk=pk,
        user=request.user,
        assignment__course__user=request.user,
    )


def _back_to_assignment(assignment):
    return redirect('canvas_sync:assignment_detail', pk=assignment.pk)


@login_required
@require_POST
def task_add(request, assignment_pk):
    assignment = _get_assignment(request, assignment_pk)
    form = TaskItemForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            'canvas_sync/assignment_detail.html',
            {
                'assignment': assignment,
                'task_items': assignment.task_items.filter(user=request.user),
                'task_form': form,
            },
            status=400,
        )

    last_order = assignment.task_items.filter(user=request.user).aggregate(
        last=Max('order')
    )['last']
    task = form.save(commit=False)
    task.assignment = assignment
    task.user = request.user
    task.ai_generated = False
    task.order = 0 if last_order is None else last_order + 1
    task.save()
    return _back_to_assignment(assignment)


@login_required
def task_edit(request, pk):
    task = _get_task(request, pk)
    form = TaskItemForm(request.POST or None, instance=task)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return _back_to_assignment(task.assignment)
    status = 400 if request.method == 'POST' else 200
    return render(
        request,
        'ai_assistant/task_edit.html',
        {'task': task, 'assignment': task.assignment, 'form': form},
        status=status,
    )


@login_required
@require_POST
def task_delete(request, pk):
    task = _get_task(request, pk)
    assignment = task.assignment
    task.delete()
    return _back_to_assignment(assignment)


@login_required
@require_POST
def task_toggle(request, pk):
    task = _get_task(request, pk)
    task.is_completed = not task.is_completed
    task.save(update_fields=['is_completed'])
    return _back_to_assignment(task.assignment)


@login_required
@require_POST
def task_move(request, pk, direction):
    task = _get_task(request, pk)
    if direction not in ('up', 'down'):
        return _back_to_assignment(task.assignment)

    with transaction.atomic():
        siblings = list(
            TaskItem.objects.select_for_update()
            .filter(assignment=task.assignment, user=request.user)
            .order_by('order', 'id')
        )
        index = next(i for i, item in enumerate(siblings) if item.pk == task.pk)
        target = index - 1 if direction == 'up' else index + 1
        if 0 <= target < len(siblings):
            siblings[index], siblings[target] = siblings[target], siblings[index]
        for position, item in enumerate(siblings):
            if item.order != position:
                item.order = position
                item.save(update_fields=['order'])
    return _back_to_assignment(task.assignment)
