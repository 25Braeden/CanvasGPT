"""Generate ephemeral suggestions, never active checklist tasks.

Only the selected assignment's description and rubric text cross the provider
boundary. Acceptance belongs to a separate, explicit student review action.
"""

import json
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError, transaction
from django.utils.html import strip_tags

from canvas_sync.models import Assignment

from .demo import DEMO_MODEL_NAME, DemoSuggestionClient
from .models import AIRequest
from .gemini import GeminiError, GeminiTimeout, request_suggestions as request_gemini_suggestions

MAX_TASKS = 20
MAX_DESCRIPTION_LENGTH = 500
MAX_ESTIMATED_MINUTES = 480
MAX_INPUT_LENGTH = 50_000
MAX_RUBRIC_CRITERIA = 50
MAX_OUTPUT_LENGTH = 32_000

STEERING_FILE = Path(__file__).resolve().parent / 'prompts' / 'task_suggestions.md'


def load_steering_instructions():
    """Read only the trusted, server-owned file; never a path from form input."""
    instructions = STEERING_FILE.read_text(encoding='utf-8').strip()
    if not instructions or len(instructions) > 20_000:
        raise ValueError('Invalid steering file')
    return instructions

TASK_SCHEMA = {
    'type': 'object',
    'properties': {
        'tasks': {
            'type': 'array',
            'minItems': 1,
            'maxItems': MAX_TASKS,
            'items': {
                'type': 'object',
                'properties': {
                    'description': {
                        'type': 'string',
                        'minLength': 1,
                        'maxLength': MAX_DESCRIPTION_LENGTH,
                    },
                    'estimated_minutes': {
                        'type': 'integer',
                        'minimum': 1,
                        'maximum': MAX_ESTIMATED_MINUTES,
                    },
                },
                'required': ['description', 'estimated_minutes'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['tasks'],
    'additionalProperties': False,
}


class GenerationFailure(StrEnum):
    FORBIDDEN = 'forbidden'
    UNAVAILABLE = 'unavailable'
    INVALID_INPUT = 'invalid_input'
    TIMEOUT = 'timeout'
    API_ERROR = 'api_error'
    INVALID_OUTPUT = 'invalid_output'
    AUDIT_ERROR = 'audit_error'
    DRAFT_ERROR = 'draft_error'


@dataclass(frozen=True)
class TaskSuggestion:
    description: str
    estimated_minutes: int


@dataclass(frozen=True)
class SuggestionResult:
    suggestions: tuple[TaskSuggestion, ...] = ()
    failure: GenerationFailure | None = None

    @property
    def success(self):
        return self.failure is None and bool(self.suggestions)

    @property
    def message(self):
        if self.success:
            return ''
        reasons = {
            GenerationFailure.INVALID_INPUT: (
                'This assignment has no usable description or rubric criteria, '
                'or its text exceeds the supported size limits.'
            ),
            GenerationFailure.UNAVAILABLE: 'Task suggestion generation is not configured correctly.',
            GenerationFailure.TIMEOUT: 'The AI provider timed out. Try again.',
            GenerationFailure.API_ERROR: 'The AI provider could not complete this request. Try again later.',
            GenerationFailure.INVALID_OUTPUT: 'The AI provider returned suggestions that could not be validated. Try again.',
            GenerationFailure.AUDIT_ERROR: 'The generation audit could not be saved. No suggestions were added.',
            GenerationFailure.DRAFT_ERROR: 'Suggestions were generated, but the review draft could not be saved.',
            GenerationFailure.FORBIDDEN: 'You do not have access to generate suggestions for this assignment.',
        }
        reason = reasons.get(self.failure, 'Task suggestions are unavailable.')
        return f'{reason} You can still add checklist tasks manually.'


class InvalidSuggestions(ValueError):
    """Deliberately carries no provider output or source text."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSuggestions()
        result[key] = value
    return result


def validate_suggestions(content):
    """Reject the whole response on any error; never coerce invalid fields."""
    if not isinstance(content, str) or not content.strip() or len(content) > MAX_OUTPUT_LENGTH:
        raise InvalidSuggestions()
    try:
        data = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError):
        raise InvalidSuggestions() from None
    if not isinstance(data, dict) or set(data) != {'tasks'}:
        raise InvalidSuggestions()
    tasks = data['tasks']
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        raise InvalidSuggestions()
    suggestions = []
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {'description', 'estimated_minutes'}:
            raise InvalidSuggestions()
        description = task['description']
        minutes = task['estimated_minutes']
        if not isinstance(description, str):
            raise InvalidSuggestions()
        description = description.strip()
        if not 1 <= len(description) <= MAX_DESCRIPTION_LENGTH:
            raise InvalidSuggestions()
        # bool is an int subclass, but is not an acceptable duration.
        if type(minutes) is not int or not 1 <= minutes <= MAX_ESTIMATED_MINUTES:
            raise InvalidSuggestions()
        suggestions.append(TaskSuggestion(description, minutes))
    return tuple(suggestions)


def _assignment_payload(assignment):
    description = assignment.plain_description
    criteria = []
    text_length = len(description)
    if text_length > MAX_INPUT_LENGTH:
        return None
    for criterion in assignment.rubric_criteria.order_by('pk')[:MAX_RUBRIC_CRITERIA + 1]:
        # No IDs, points, account fields, URLs, or other assignment metadata.
        item = {
            'title': strip_tags(criterion.title).strip(),
            'description': strip_tags(criterion.description).strip(),
        }
        text_length += len(item['title']) + len(item['description'])
        criteria.append(item)
        if text_length > MAX_INPUT_LENGTH or len(criteria) > MAX_RUBRIC_CRITERIA:
            return None
    if not description and not any(item['title'] or item['description'] for item in criteria):
        return None
    return {'description': description, 'rubric_criteria': criteria}


def generate_task_suggestions(*, assignment, user, client=None, demo=False):
    """Return validated suggestions or a safe failure; write only AIRequest.

    ``client`` may be a callable returning raw task JSON for offline tests.
    No request/response/exception bodies are logged. An authorized attempt gets
    one metadata-only audit record, including configuration/input failures;
    unauthorized attempts get none. ``demo=True`` uses a fixed offline adapter,
    with a distinct audit model name and no dependence on Gemini configuration.
    """
    if (
        not getattr(user, 'is_authenticated', False)
        or not user.pk
        or not assignment.pk
        or not Assignment.objects.filter(pk=assignment.pk, course__user_id=user.pk).exists()
    ):
        return SuggestionResult(failure=GenerationFailure.FORBIDDEN)

    if demo:
        client = DemoSuggestionClient()
    model = DEMO_MODEL_NAME if demo else settings.GEMINI_MODEL
    valid_model = (
        isinstance(model, str) and 1 <= len(model.strip()) <= 100
        and re.fullmatch(r'[A-Za-z0-9_.-]+', model.strip()) is not None
    )
    api_key = settings.GEMINI_API_KEY
    model = model.strip() if valid_model else '(unconfigured)'
    try:
        # A savepoint keeps a failed audit write from breaking caller transactions.
        with transaction.atomic():
            audit = AIRequest.objects.create(
                user=user,
                request_type=AIRequest.RequestType.CHECKLIST_GENERATION,
                model_name=model,
                success=False,
            )
    except DatabaseError:
        return SuggestionResult(failure=GenerationFailure.AUDIT_ERROR)

    try:
        timeout = 30.0 if demo else float(settings.GEMINI_TIMEOUT_SECONDS)
    except (ValueError, TypeError, OverflowError):
        timeout = 0
    if (
        not valid_model
        or not math.isfinite(timeout)
        or not 0 < timeout <= 120
        or (client is None and not api_key.strip())
    ):
        return SuggestionResult(failure=GenerationFailure.UNAVAILABLE)

    payload = _assignment_payload(assignment)
    if payload is None:
        return SuggestionResult(failure=GenerationFailure.INVALID_INPUT)
    try:
        instructions = load_steering_instructions()
    except (OSError, UnicodeError, ValueError):
        return SuggestionResult(failure=GenerationFailure.UNAVAILABLE)
    try:
        provider = client if client is not None else request_gemini_suggestions
        content = provider(
            api_key='' if demo else api_key, model=model, timeout=timeout, payload=payload,
            instructions=instructions, schema=TASK_SCHEMA,
        )
        suggestions = validate_suggestions(content)
    except GeminiTimeout:
        return SuggestionResult(failure=GenerationFailure.TIMEOUT)
    except GeminiError:
        return SuggestionResult(failure=GenerationFailure.API_ERROR)
    except InvalidSuggestions:
        return SuggestionResult(failure=GenerationFailure.INVALID_OUTPUT)

    try:
        with transaction.atomic():
            audit.success = True
            audit.save(update_fields=['success'])
    except DatabaseError:
        return SuggestionResult(failure=GenerationFailure.AUDIT_ERROR)
    return SuggestionResult(suggestions=suggestions)
