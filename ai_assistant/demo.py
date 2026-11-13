"""Fixed SDK-compatible responses for the site's explicitly labeled demo.

This adapter performs no network I/O and does not infer tasks from source text.
It still exercises the real service's input/output validation and audit path.
"""

import json
from types import SimpleNamespace

DEMO_MODEL_NAME = 'demo-task-suggestions'


class DemoSuggestionClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        content = json.dumps({
            'tasks': [
                {'description': 'Read the assignment instructions and note the requirements.', 'estimated_minutes': 15},
                {'description': 'Draft an outline or plan for the assignment.', 'estimated_minutes': 30},
                {'description': 'Review your work against the instructions and any rubric criteria.', 'estimated_minutes': 20},
            ],
        })
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason='stop',
            message=SimpleNamespace(content=content, refusal=None, tool_calls=None),
        )])
