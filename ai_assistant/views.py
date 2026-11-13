from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Max
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from canvas_sync.models import Assignment
from canvas_sync.views import get_assignment_sync_status

from .acceptance import DraftAcceptanceError, accept_suggestion_draft
from .drafts import (
    DraftReviewConflict, generate_suggestion_draft, suggestion_context, update_draft_review,
)
from .forms import DraftRevisionForm, SuggestionReviewFormSet, TaskItemForm
from .models import SuggestionDraft, TaskItem
from .services import InvalidSuggestions


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
def suggestions_generate(request, assignment_pk):
    assignment = _get_assignment(request, assignment_pk)
    # Provider selection is server-side; form input cannot opt into live calls.
    _, result = generate_suggestion_draft(assignment=assignment, user=request.user)
    context = suggestion_context(assignment=assignment, user=request.user, result=result)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': result.success,
            'failure_code': result.failure,
            'html': render_to_string(
                'ai_assistant/_suggestion_result.html',
                context,
                request=request,
            ),
        })
    return render(
        request,
        'canvas_sync/assignment_detail.html',
        {
            'assignment': assignment,
            'assignment_sync_status': get_assignment_sync_status(assignment),
            'task_items': assignment.task_items.filter(user=request.user),
            'task_form': TaskItemForm(),
            **context,
        },
    )


def _get_owned_draft(request, pk):
    return get_object_or_404(
        SuggestionDraft.objects.select_related('assignment__course'),
        pk=pk, user=request.user, assignment__course__user=request.user,
    )


def _unavailable_draft(request, draft, *, status=409):
    return render(
        request, 'ai_assistant/draft_unavailable.html',
        {'assignment': draft.assignment}, status=status,
    )


@login_required
@require_http_methods(['GET', 'POST'])
def suggestions_review(request, pk):
    return _review_suggestions(request, pk)


@login_required
@require_POST
def suggestions_accept(request, pk):
    return _review_suggestions(request, pk, accept=True)


def _review_suggestions(request, pk, *, accept=False):
    draft = _get_owned_draft(request, pk)
    if draft.status != SuggestionDraft.Status.PENDING or draft.expires_at <= timezone.now():
        return _unavailable_draft(request, draft)
    try:
        suggestions = draft.validated_suggestions
    except (InvalidSuggestions, TypeError, ValueError, RecursionError):
        return _unavailable_draft(request, draft)

    data = request.POST if request.method == 'POST' else None
    revision_form = DraftRevisionForm(data=data, initial={'revision': draft.revision})
    formset = SuggestionReviewFormSet(
        data=data, prefix='suggestions', expected_count=len(suggestions),
        initial=[
            {'description': item.description, 'estimated_minutes': item.estimated_minutes,
             'selected': index in draft.selected_indices}
            for index, item in enumerate(suggestions)
        ],
    )
    status = 200
    if request.method == 'POST':
        valid_revision = revision_form.is_valid()
        valid_suggestions = formset.is_valid()
        if valid_revision and valid_suggestions:
            try:
                action = accept_suggestion_draft if accept else update_draft_review
                accepted_count = action(
                    draft=draft, user=request.user,
                    revision=revision_form.cleaned_data['revision'],
                    suggestions=[
                        {'description': form.cleaned_data['description'],
                         'estimated_minutes': form.cleaned_data['estimated_minutes']}
                        for form in formset
                    ],
                    selected_indices=[index for index, form in enumerate(formset) if form.cleaned_data['selected']],
                )
            except DraftAcceptanceError as error:
                revision_form.add_error(None, error.messages[0])
                status = 400
            except DraftReviewConflict as error:
                revision_form.add_error(None, str(error))
                status = 409
            except (DatabaseError, ValidationError, InvalidSuggestions, Assignment.DoesNotExist, SuggestionDraft.DoesNotExist):
                revision_form.add_error(None, 'Could not complete this action safely. Reload the draft and try again.')
                status = 409
            else:
                if accept:
                    messages.success(request, f'Added {accepted_count} task(s) to your checklist. Your study plan was not changed.')
                    return _back_to_assignment(draft.assignment)
                messages.success(request, 'Draft review saved. No tasks have been added to your checklist.')
                return redirect('ai_assistant:suggestions_review', pk=draft.pk)
        else:
            status = 400
    return render(
        request, 'ai_assistant/suggestion_review.html',
        {'assignment': draft.assignment, 'draft': draft, 'revision_form': revision_form, 'formset': formset},
        status=status,
    )


@login_required
@require_POST
def suggestions_discard(request, pk):
    draft = _get_owned_draft(request, pk)
    revision_form = DraftRevisionForm(request.POST)
    if not revision_form.is_valid():
        return _unavailable_draft(request, draft, status=400)
    try:
        update_draft_review(
            draft=draft, user=request.user, revision=revision_form.cleaned_data['revision'], discard=True,
        )
    except (DraftReviewConflict, DatabaseError, ValidationError, Assignment.DoesNotExist, SuggestionDraft.DoesNotExist):
        return _unavailable_draft(request, draft)
    return _back_to_assignment(draft.assignment)


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
                'assignment_sync_status': get_assignment_sync_status(assignment),
                'task_items': assignment.task_items.filter(user=request.user),
                'task_form': form,
                **suggestion_context(assignment=assignment, user=request.user),
            },
            status=400,
        )

    with transaction.atomic():
        Assignment.objects.select_for_update().get(pk=assignment.pk, course__user=request.user)
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
        Assignment.objects.select_for_update().get(pk=task.assignment_id, course__user=request.user)
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
