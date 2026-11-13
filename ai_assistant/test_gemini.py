"""Offline Gemini tests: never initialize a live provider client."""

import json
from unittest.mock import Mock, patch

import requests
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .drafts import generate_suggestion_draft
from .models import AIRequest, SuggestionDraft, TaskItem
from .services import GenerationFailure, generate_task_suggestions, load_steering_instructions
from .test_services import SuggestionServiceTests


@override_settings(
    AI_SUGGESTIONS_MODE='gemini', GEMINI_API_KEY='fake-test-key',
    GEMINI_MODEL='gemini-2.5-flash', GEMINI_TIMEOUT_SECONDS='30',
)
class GeminiServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        SuggestionServiceTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.original_tasks = list(TaskItem.objects.order_by('pk').values())
        self.post = patch('ai_assistant.gemini.requests.post').start()
        self.addCleanup(patch.stopall)
        self.response = Mock(status_code=200, content=b'{}')
        self.post.return_value.__enter__.return_value = self.response
        self.set_content(json.dumps({'tasks': [{'description': 'Outline', 'estimated_minutes': 20}]}))

    def tearDown(self):
        self.assertEqual(list(TaskItem.objects.order_by('pk').values()), self.original_tasks)

    def set_content(self, text):
        self.response.json.return_value = {
            'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': text}]}}],
        }

    def generate(self):
        return generate_task_suggestions(assignment=self.assignment, user=self.user)

    def ajax_generate(self):
        self.client.force_login(self.user)
        return self.client.post(
            reverse('ai_assistant:suggestions_generate', args=[self.assignment.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json',
        )

    def test_button_post_through_gemini_adapter_renders_review_preview(self):
        # Exercise the same CSRF-protected fetch contract as suggestions.js.
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        page = self.client.get(reverse('canvas_sync:assignment_detail', args=[self.assignment.pk]))
        self.assertContains(page, 'data-suggestion-generation')
        self.assertContains(page, 'Google Gemini')
        response = self.client.post(
            reverse('ai_assistant:suggestions_generate', args=[self.assignment.pk]),
            {'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest', HTTP_ACCEPT='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIsNone(data['failure_code'])
        self.assertIn('Task suggestion preview', data['html'])
        self.assertIn('Review suggestions', data['html'])
        self.assertEqual(SuggestionDraft.objects.get().generation_mode, 'gemini')
        self.post.assert_called_once()
        self.assertTrue(AIRequest.objects.get().success)

    def test_button_reports_empty_assignment_without_contacting_gemini(self):
        self.assignment.description = ''
        self.assignment.save(update_fields=['description'])
        response = self.ajax_generate()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['failure_code'], 'invalid_input')
        self.assertIn('no usable description or rubric', data['html'])
        self.assertIn('manually', data['html'])
        self.post.assert_not_called()
        self.assertFalse(SuggestionDraft.objects.exists())
        self.assertFalse(AIRequest.objects.get().success)

    def test_button_distinguishes_provider_timeout_and_invalid_output(self):
        for failure in ('api_error', 'timeout', 'invalid_output'):
            with self.subTest(failure=failure):
                self.post.side_effect = requests.Timeout() if failure == 'timeout' else None
                self.response.status_code = 404 if failure == 'api_error' else 200
                if failure == 'invalid_output':
                    self.set_content('{broken')
                response = self.ajax_generate()
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertFalse(data['success'])
                self.assertEqual(data['failure_code'], failure)
                self.assertIn('data-suggestion-failure="' + failure + '"', data['html'])
                self.assertIn('manually', data['html'])
                self.assertNotIn('fake-test-key', data['html'])
        self.assertFalse(SuggestionDraft.objects.exists())
        self.assertFalse(AIRequest.objects.filter(success=True).exists())

    def test_success_payload_and_audit(self):
        result = self.generate()
        self.assertTrue(result.success)
        kwargs = self.post.call_args.kwargs
        payload = json.loads(kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(payload, {'description': 'Write an essay.', 'rubric_criteria': []})
        self.assertEqual(kwargs['json']['systemInstruction']['parts'][0]['text'], load_steering_instructions())
        self.assertEqual(kwargs['timeout'], 30)
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['headers'], {'x-goog-api-key': 'fake-test-key'})
        audit = AIRequest.objects.get()
        self.assertTrue(audit.success)
        self.assertEqual(audit.model_name, 'gemini-2.5-flash')
        self.assertNotIn('fake-test-key', repr(list(AIRequest.objects.values())))

    def test_rubric_and_draft_workflow(self):
        from canvas_sync.models import RubricCriterion
        RubricCriterion.objects.create(assignment=self.assignment, title='Evidence', description='Use sources')
        draft, result = generate_suggestion_draft(assignment=self.assignment, user=self.user)
        self.assertTrue(result.success)
        self.assertEqual(draft.generation_mode, 'gemini')
        self.assertEqual(draft.model_name, 'gemini-2.5-flash')
        payload = json.loads(self.post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(payload['rubric_criteria'], [{'title': 'Evidence', 'description': 'Use sources'}])

    def test_signed_final_text_reaches_review_without_storing_metadata(self):
        candidate = self.response.json.return_value['candidates'][0]
        candidate['content']['parts'][0]['thoughtSignature'] = 'opaque-private-signature'
        response = self.ajax_generate()
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Outline', data['html'])
        draft = SuggestionDraft.objects.get()
        self.assertEqual(draft.suggestions, [{'description': 'Outline', 'estimated_minutes': 20}])
        self.assertNotIn('opaque-private-signature', data['html'])
        self.assertNotIn('opaque-private-signature', repr(list(AIRequest.objects.values())))

    def test_split_text_and_thought_parts_use_only_final_json(self):
        candidate = self.response.json.return_value['candidates'][0]
        candidate['content']['parts'] = [
            {'text': 'Private reasoning, not JSON', 'thought': True},
            {'text': '{"tasks":[{"description":"Out', 'thought': False},
            {'text': 'line","estimated_minutes":20}]}', 'thoughtSignature': 'opaque-signature'},
            {'thoughtSignature': 'standalone-signature'},
        ]
        result = self.generate()
        self.assertTrue(result.success)
        self.assertEqual(result.suggestions[0].description, 'Outline')
        self.assertNotIn('Private reasoning', repr(result))
        self.assertNotIn('signature', repr(result))

    def test_reasoning_without_final_answer_is_rejected(self):
        candidate = self.response.json.return_value['candidates'][0]
        candidate['content']['parts'][0]['thought'] = True
        self.assertEqual(self.generate().failure, GenerationFailure.INVALID_OUTPUT)

    def test_invalid_or_tool_parts_are_rejected_even_with_valid_text(self):
        original = self.response.json.return_value['candidates'][0]['content']['parts'][0]
        for part in (
            None, {}, {'text': None}, {'text': 'x', 'thought': 'false'},
            {'text': 'x', 'thoughtSignature': 123}, {'thought': False},
            {'functionCall': {'name': 'unexpected', 'args': {}}},
            {'inlineData': {'mimeType': 'text/plain', 'data': 'abc'}},
        ):
            with self.subTest(part=part):
                self.response.json.return_value['candidates'][0]['content']['parts'] = [original, part]
                self.assertEqual(self.generate().failure, GenerationFailure.INVALID_OUTPUT)

    def test_signed_text_still_requires_valid_task_fields(self):
        self.set_content('{"tasks":[{"description":"Outline","estimated_minutes":0}]}')
        self.response.json.return_value['candidates'][0]['content']['parts'][0]['thoughtSignature'] = 'signature'
        self.assertEqual(self.generate().failure, GenerationFailure.INVALID_OUTPUT)

    def test_invalid_output(self):
        for text in ('{broken', '', '{"tasks": []}',
                     '{"tasks": [{"description": "x", "estimated_minutes": 0}]}'):
            with self.subTest(text=text):
                self.set_content(text)
                result = self.generate()
                self.assertEqual(result.failure, GenerationFailure.INVALID_OUTPUT)
                self.assertEqual(result.suggestions, ())
        self.assertFalse(AIRequest.objects.filter(success=True).exists())

    def test_malformed_envelopes(self):
        for envelope in (None, [], {}, {'promptFeedback': None},
                         {'candidates': [None]}, {'candidates': [{'finishReason': 'MAX_TOKENS'}]},
                         {'promptFeedback': {'blockReason': 'SAFETY'}}):
            with self.subTest(envelope=envelope):
                self.response.json.return_value = envelope
                self.assertEqual(self.generate().failure, GenerationFailure.INVALID_OUTPUT)

    def test_invalid_envelope_json(self):
        self.response.json.side_effect = ValueError()
        self.assertEqual(self.generate().failure, GenerationFailure.INVALID_OUTPUT)

    def test_timeout_connection_and_http_errors(self):
        for error, expected in ((requests.Timeout(), GenerationFailure.TIMEOUT),
                                (requests.ConnectionError(), GenerationFailure.API_ERROR)):
            with self.subTest(error=type(error).__name__):
                self.post.side_effect = error
                self.assertEqual(self.generate().failure, expected)
        self.post.side_effect = None
        for status in (302, 400, 403, 429, 500):
            self.response.status_code = status
            self.assertEqual(self.generate().failure, GenerationFailure.API_ERROR)
        self.assertFalse(AIRequest.objects.filter(success=True).exists())

    def test_missing_key_and_unsafe_model_fail_without_network(self):
        for overrides in ({'GEMINI_API_KEY': ''}, {'GEMINI_MODEL': '../bad'},
                          {'GEMINI_TIMEOUT_SECONDS': 'invalid'}):
            with self.subTest(overrides=overrides), override_settings(**overrides):
                self.assertEqual(self.generate().failure, GenerationFailure.UNAVAILABLE)
        self.post.assert_not_called()
