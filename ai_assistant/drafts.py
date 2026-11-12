"""Provider-independent draft lifecycle, separate from generation and acceptance.

Change AI_SUGGESTIONS_MODE to select a provider. Both providers return the same
validated SuggestionResult; no provider SDK, prompts, or raw responses are stored
here. There is deliberately no TaskItem/PlanSession write or acceptance action.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from canvas_sync.models import Assignment

from .demo import DEMO_MODEL_NAME
from .models import SuggestionDraft
from .services import (
    GenerationFailure, InvalidSuggestions, SuggestionResult, generate_task_suggestions,
)


def generation_mode():
    mode = settings.AI_SUGGESTIONS_MODE
    return mode.strip().lower() if isinstance(mode, str) else ''


def current_suggestion_draft(*, assignment, user):
    """Return only this owner's unexpired pending draft; never generate on GET."""
    draft = SuggestionDraft.objects.filter(
        assignment=assignment, user=user, assignment__course__user=user,
        status=SuggestionDraft.Status.PENDING, expires_at__gt=timezone.now(),
    ).first()
    if draft is not None:
        try:
            draft.validated_suggestions
        except (InvalidSuggestions, TypeError, ValueError, RecursionError):
            return None
    return draft


def suggestion_context(*, assignment, user, result=None):
    draft = current_suggestion_draft(assignment=assignment, user=user)
    return {
        'suggestion_mode': generation_mode(),
        'suggestion_draft': draft,
        'suggestion_result': result if result is not None else SuggestionResult(),
    }


def generate_suggestion_draft(*, assignment, user, client=None):
    """Generate first, then atomically replace pending drafts on success only.

    Returns (draft, result). A failed attempt leaves any previous pending draft
    unchanged. No database transaction/row lock is held during provider I/O.
    ``client`` is an optional SDK-compatible test dependency, not form input.
    """
    if not getattr(user, 'is_authenticated', False) or not Assignment.objects.filter(
        pk=assignment.pk, course__user_id=user.pk,
    ).exists():
        return None, SuggestionResult(failure=GenerationFailure.FORBIDDEN)
    mode = generation_mode()
    if mode not in SuggestionDraft.GenerationMode.values:
        return None, SuggestionResult(failure=GenerationFailure.UNAVAILABLE)

    kwargs = {'assignment': assignment, 'user': user, 'demo': mode == SuggestionDraft.GenerationMode.DEMO}
    if client is not None:
        kwargs['client'] = client
    result = generate_task_suggestions(**kwargs)
    if not result.success:
        return None, result

    try:
        with transaction.atomic():
            # Serializes draft replacement with future acceptance on this assignment.
            Assignment.objects.select_for_update().get(pk=assignment.pk, course__user_id=user.pk)
            SuggestionDraft.objects.filter(
                assignment=assignment, user=user, status=SuggestionDraft.Status.PENDING,
            ).update(status=SuggestionDraft.Status.SUPERSEDED)
            draft = SuggestionDraft.objects.create(
                assignment=assignment,
                user=user,
                suggestions=[
                    {'description': item.description, 'estimated_minutes': item.estimated_minutes}
                    for item in result.suggestions
                ],
                generation_mode=mode,
                model_name=DEMO_MODEL_NAME if mode == SuggestionDraft.GenerationMode.DEMO else settings.OPENAI_MODEL.strip(),
            )
    except (DatabaseError, ValidationError, Assignment.DoesNotExist):
        return None, SuggestionResult(failure=GenerationFailure.DRAFT_ERROR)
    return draft, result
