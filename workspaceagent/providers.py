import json

from google import genai
from google.genai import types
from groq import Groq
from mistralai.client import Mistral
from openai import OpenAI

from basichatapp.providers import ProviderError


FUNCTIONS = [
    {
        "name": "gmail_search",
        "description": "Search received Gmail messages using Gmail search syntax.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["query"],
        },
    },
    {
        "name": "gmail_important",
        "description": "Read Gmail messages marked important.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 20}},
        },
    },
    {
        "name": "calendar_list",
        "description": "List or search Google Calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "ISO-8601 datetime"},
                "time_max": {"type": "string", "description": "ISO-8601 datetime"},
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        },
    },
    {
        "name": "calendar_create",
        "description": "Prepare a Google Calendar event. The app will require user approval before creation.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
                "timezone_name": {"type": "string"}, "description": {"type": "string"},
                "location": {"type": "string"}, "attendees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "start", "end"],
        },
    },
    {
        "name": "calendar_delete",
        "description": "Find or select a calendar event to remove. The app will require user approval before deletion.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"}, "query": {"type": "string"},
                "time_min": {"type": "string"}, "time_max": {"type": "string"},
            },
        },
    },
]


def _messages(system, message, history):
    context = [{"role": item["role"], "content": item["content"]} for item in history[-6:]]
    return [{"role": "system", "content": system}, *context, {"role": "user", "content": message}]


def _gemini_contents(message, history):
    context = [
        {"role": "model" if item["role"] == "assistant" else "user", "parts": [{"text": item["content"]}]}
        for item in history[-6:]
    ]
    return [*context, {"role": "user", "parts": [{"text": message}]}]


def _arguments(value):
    if isinstance(value, dict):
        return value
    return json.loads(value or "{}")


def _openai_client(provider, api_key):
    if provider == "openrouter":
        return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    return OpenAI(api_key=api_key)


def _provider_error(provider, error):
    label = {"gemini": "Google Gemini", "groq": "GroqCloud", "openrouter": "OpenRouter"}.get(provider, provider.title())
    status_code = getattr(error, "status_code", None) or getattr(error, "code", None)
    message = str(getattr(error, "message", "") or "").lower()
    if status_code in (401, 403) or (status_code == 400 and "api key" in message):
        return ProviderError(f"{label} rejected the API key. Check the key and its permissions.")
    if status_code == 404:
        return ProviderError(f"{label} could not find that model. Check the model ID.")
    if status_code == 429:
        return ProviderError(f"{label} rate limit or quota reached.")
    return ProviderError(f"{label} request failed. Check the provider, model, and API key.")


def tool_plan(provider, api_key, model, system, message, history=None):
    history = history or []
    try:
        if provider == "gemini":
            declarations = [types.FunctionDeclaration(**function) for function in FUNCTIONS]
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model.removeprefix("models/"),
                contents=_gemini_contents(message, history),
                config=types.GenerateContentConfig(system_instruction=system, tools=[types.Tool(function_declarations=declarations)]),
            )
            calls = response.function_calls or []
            if calls:
                return {"action": calls[0].name, "arguments": dict(calls[0].args or {})}
            return {"action": "answer", "arguments": {"response": response.text or "How can I help?"}}

        tools = [{"type": "function", "function": function} for function in FUNCTIONS]
        messages = _messages(system, message, history)
        if provider == "mistral":
            response = Mistral(api_key=api_key).chat.complete(model=model, messages=messages, tools=tools, tool_choice="auto")
        elif provider == "groq":
            response = Groq(api_key=api_key).chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto")
        else:
            response = _openai_client(provider, api_key).chat.completions.create(model=model, messages=messages, tools=tools, tool_choice="auto")
        output = response.choices[0].message
        calls = output.tool_calls or []
        if calls:
            return {"action": calls[0].function.name, "arguments": _arguments(calls[0].function.arguments)}
        return {"action": "answer", "arguments": {"response": output.content or "How can I help?"}}
    except ProviderError:
        raise
    except Exception as error:
        raise _provider_error(provider, error) from error


def text_response(provider, api_key, model, messages):
    try:
        if provider == "gemini":
            system = next((item["content"] for item in messages if item["role"] == "system"), None)
            contents = [item for item in messages if item["role"] != "system"]
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model.removeprefix("models/"), contents=contents,
                config=types.GenerateContentConfig(system_instruction=system),
            )
            return response.text or "Google returned no matching items."
        if provider == "mistral":
            response = Mistral(api_key=api_key).chat.complete(model=model, messages=messages)
        elif provider == "groq":
            response = Groq(api_key=api_key).chat.completions.create(model=model, messages=messages)
        else:
            response = _openai_client(provider, api_key).chat.completions.create(model=model, messages=messages)
        return response.choices[0].message.content or "Google returned no matching items."
    except Exception as error:
        raise _provider_error(provider, error) from error