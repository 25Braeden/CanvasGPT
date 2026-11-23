"""Explicit student acceptance; generation/review never call this module."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from canvas_sync.models import Assignment

from .drafts import DraftReviewConflict
from .models import SuggestionDraft, TaskItem


class DraftAcceptanceError(ValidationError):
    """A safe, user-correctable acceptance error."""


def accept_suggestion_draft(
    *,
    draft,
    user,
    revision,
    suggestions,
    selected_indices,
    student_added_indices=None,
):
    """Atomically append the selected reviewed tasks and consume the draft.

    Validate against the current locked row, not client-provided ownership,
    status, order, or completion fields. Replayed/stale submissions cannot add
    duplicates. No provider call, audit write, task replacement, or scheduling.
    """
    with transaction.atomic():
        Assignment.objects.select_for_update().get(
            pk=draft.assignment_id,
            course__user_id=user.pk,
        )

        current = SuggestionDraft.objects.select_for_update().get(
            pk=draft.pk,
            user=user,
            assignment__course__user=user,
        )

        if (
            current.status != SuggestionDraft.Status.PENDING
            or current.expires_at <= timezone.now()
            or current.revision != revision
        ):
            raise DraftReviewConflict(
                'This draft changed or is no longer available. '
                'Reload before continuing.'
            )

        original_count = len(current.validated_suggestions)

        # Preserve the original strict behavior for direct callers.
        # The review page explicitly provides student_added_indices when
        # students remove AI suggestions or add their own steps.
        if student_added_indices is None:
            if (
                not isinstance(suggestions, list)
                or len(suggestions) != original_count
            ):
                raise DraftAcceptanceError(
                    'The suggestion list changed. '
                    'Reload the draft before accepting.'
                )

            student_added_indices = list(current.student_added_indices)

        else:
            if not isinstance(suggestions, list):
                raise DraftAcceptanceError(
                    'The suggestion list changed. '
                    'Reload the draft before accepting.'
                )

            if not isinstance(student_added_indices, list):
                raise DraftAcceptanceError(
                    'The suggestion list changed. '
                    'Reload the draft before accepting.'
                )

            if (
                any(
                    type(index) is not int
                    or index < 0
                    or index >= len(suggestions)
                    for index in student_added_indices
                )
                or len(set(student_added_indices))
                != len(student_added_indices)
            ):
                raise DraftAcceptanceError(
                    'The suggestion list changed. '
                    'Reload the draft before accepting.'
                )

            ai_count = (
                len(suggestions)
                - len(student_added_indices)
            )

            if ai_count > original_count:
                raise DraftAcceptanceError(
                    'The suggestion list changed. '
                    'Reload the draft before accepting.'
                )

        current.suggestions = suggestions
        current.selected_indices = selected_indices
        current.student_added_indices = student_added_indices
        current.full_clean()

        if not current.selected_indices:
            raise DraftAcceptanceError(
                'Select at least one suggestion to accept.'
            )

        last_order = TaskItem.objects.filter(
            assignment_id=current.assignment_id,
            user=user,
        ).aggregate(
            last=Max('order'),
        )['last']

        start_order = 0 if last_order is None else last_order + 1

        tasks = []

        for position, index in enumerate(current.selected_indices):
            suggestion = current.suggestions[index]

            task = TaskItem(
                assignment_id=current.assignment_id,
                user=user,
                description=suggestion['description'],
                estimated_minutes=suggestion['estimated_minutes'],
                order=start_order + position,
                ai_generated=index not in current.student_added_indices,
                is_completed=False,
            )

            task.full_clean()
            tasks.append(task)

        TaskItem.objects.bulk_create(tasks)

        current.status = SuggestionDraft.Status.ACCEPTED
        current.revision += 1
        current.save()

    return len(tasks)