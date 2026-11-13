"""Fixed offline responses; no network I/O or inference from source text."""

import json

DEMO_MODEL_NAME = 'demo-task-suggestions'


class DemoSuggestionClient:
    def __call__(self, **kwargs):
        return json.dumps({
            'tasks': [
                {'description': 'Read the assignment instructions and note the requirements.', 'estimated_minutes': 15},
                {'description': 'Draft an outline or plan for the assignment.', 'estimated_minutes': 30},
                {'description': 'Review your work against the instructions and any rubric criteria.', 'estimated_minutes': 20},
            ],
        })
