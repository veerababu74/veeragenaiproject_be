from urllib.parse import quote

import requests


OPENAI_COMPATIBLE_URLS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


class ProviderError(Exception):
    pass


def _error_message(provider, status_code):
    label = "GroqCloud" if provider == "groq" else provider.title()
    if status_code in (401, 403):
        return f"{label} rejected the API key. Check the key and its permissions."
    if status_code == 404:
        return f"{label} could not find that model. Check the model ID."
    if status_code == 429:
        return f"{label} rate limit or quota reached. Check your provider account."
    if status_code == 400:
        return f"{label} rejected the request. Check the model ID and provider settings."
    return f"{label} request failed with status {status_code}."


def _post(url, headers, payload, provider):
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(10, 120))
    except requests.Timeout as error:
        raise ProviderError(f"{provider.title()} took too long to respond. Try again.") from error
    except requests.RequestException as error:
        raise ProviderError(f"Could not reach {provider}") from error
    if not response.ok:
        raise ProviderError(_error_message(provider, response.status_code))
    try:
        return response.json()
    except ValueError as error:
        raise ProviderError(f"{provider} returned an invalid response") from error


def chat(provider, api_key, model, messages):
    if provider == "gemini":
        model = model.removeprefix("models/")
        payload = {
            "contents": [
                {
                    "role": "model" if message["role"] == "assistant" else "user",
                    "parts": [{"text": message["content"]}],
                }
                for message in messages
            ]
        }
        data = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
            {"x-goog-api-key": api_key, "Content-Type": "application/json"},
            payload,
            provider,
        )
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError("Gemini returned no answer") from error

    data = _post(
        OPENAI_COMPATIBLE_URLS[provider],
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"model": model, "messages": messages},
        provider,
    )
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ProviderError(f"{provider} returned no answer") from error