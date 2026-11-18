"""Minimal Gemini REST adapter. No retries, tools, logging, or task writes."""

import json

import requests


class GeminiError(Exception):
    pass


class GeminiTimeout(GeminiError):
    pass


def request_suggestions(*, api_key, model, timeout, payload, instructions, schema):
    # Import here to keep the shared validator independent of this adapter.
    from .services import InvalidSuggestions, MAX_OUTPUT_LENGTH

    try:
        with requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
            headers={'x-goog-api-key': api_key},
            json={
                'systemInstruction': {'parts': [{'text': instructions}]},
                'contents': [{'role': 'user', 'parts': [{'text': json.dumps(payload, ensure_ascii=False)}]}],
                'generationConfig': {
                    'responseMimeType': 'application/json',
                    'responseJsonSchema': schema,
                    'maxOutputTokens': 8192,
                },
            },
            timeout=timeout,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise GeminiError()
            # Bound the accepted envelope as well as the task JSON.
            if len(response.content) > MAX_OUTPUT_LENGTH * 4:
                raise InvalidSuggestions()
            try:
                data = response.json()
            except ValueError:
                raise InvalidSuggestions() from None
    except requests.Timeout:
        raise GeminiTimeout() from None
    except requests.RequestException:
        raise GeminiError() from None

    if not isinstance(data, dict):
        raise InvalidSuggestions()
    feedback = data.get('promptFeedback', {})
    if not isinstance(feedback, dict) or feedback.get('blockReason'):
        raise InvalidSuggestions()
    candidates = data.get('candidates')
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise InvalidSuggestions()
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get('finishReason') != 'STOP':
        raise InvalidSuggestions()
    content = candidate.get('content')
    parts = content.get('parts') if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise InvalidSuggestions()
    # Gemini can attach opaque thought signatures to final text and split the
    # answer across parts. These are envelope metadata, not task JSON fields.
    # Never return/store reasoning or signatures, and still reject tool/media
    # parts rather than silently accepting a response that invoked a tool.
    texts = []
    for part in parts:
        if not isinstance(part, dict) or not part or set(part) - {'text', 'thought', 'thoughtSignature'}:
            raise InvalidSuggestions()
        if 'thought' in part and type(part['thought']) is not bool:
            raise InvalidSuggestions()
        if 'thoughtSignature' in part and not isinstance(part['thoughtSignature'], str):
            raise InvalidSuggestions()
        if 'text' not in part:
            if 'thoughtSignature' not in part:
                raise InvalidSuggestions()
            continue
        if not isinstance(part['text'], str):
            raise InvalidSuggestions()
        if not part.get('thought', False):
            texts.append(part['text'])
    # The service validates the combined JSON, task count, fields and bounds.
    return ''.join(texts)
