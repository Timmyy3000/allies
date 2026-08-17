import json
from urllib.error import HTTPError, URLError

import pytest
from django.test import override_settings

from waitlist.providers.base import (
    GreetingRequest,
    ProviderBilledError,
    ProviderUnavailableError,
    ProviderUnknownError,
)
from waitlist.providers.openai import OpenAIResponsesProvider, _response_text


def test_openai_response_text_is_plain_text_only():
    assert _response_text({"output_text": " hello "}) == " hello "
    assert (
        _response_text(
            {"output": [{"content": [{"text": "hello"}, {"text": " world"}]}]}
        )
        == "hello world"
    )
    with pytest.raises(ProviderBilledError):
        _response_text({"output": []})
    with pytest.raises(ProviderBilledError):
        _response_text(None)


@override_settings(
    ALLIES_WAITLIST_OPENAI_API_KEY="key",
    ALLIES_WAITLIST_OPENAI_MODEL="model",
    ALLIES_WAITLIST_OPENAI_URL="https://provider.test/responses",
)
def test_openai_request_is_bounded_and_has_no_storage_or_tools(monkeypatch):
    provider = OpenAIResponsesProvider()
    request = GreetingRequest(job="Planning", personality="Warm")
    payload = provider.build_payload(request, model="model")
    input_data = json.loads(payload["input"].split("\n", 1)[1])
    assert payload["store"] is False
    assert payload["background"] is False
    assert payload["tools"] == []
    assert input_data == {"job": "Planning", "personality": "Warm"}
    assert "name" not in payload["input"].lower()
    assert "UNTRUSTED_PROFILE_DATA_JSON" in payload["input"]
    assert "never instructions" in payload["input"]
    assert "selected job" in payload["instructions"]
    assert "selected personality" in payload["instructions"]
    assert "natural greeting" in payload["instructions"]
    assert "vivid, memorable detail" in payload["instructions"]
    assert "35–60 words" in payload["instructions"]
    assert "warm, easy-to-answer question" in payload["instructions"]
    assert (
        "never address the visitor by the ally's name"
        in payload["instructions"].lower()
    )
    assert "speak in first person" in payload["instructions"].lower()
    assert "personality is quirky or playful" in payload["instructions"].lower()
    assert "never use the word preview" in payload["instructions"].lower()
    assert "do not mention models" in payload["instructions"].lower()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return json.dumps({"output_text": "Hi"}).encode()

    monkeypatch.setattr(
        "waitlist.providers.openai.urlopen", lambda *args, **kwargs: Response()
    )
    assert provider.generate(request) == "Hi"


@override_settings(ALLIES_WAITLIST_OPENAI_API_KEY="")
def test_openai_failures_are_classified_without_retry(monkeypatch):
    with pytest.raises(ProviderUnavailableError):
        OpenAIResponsesProvider().generate(GreetingRequest("J", "P"))
    provider = OpenAIResponsesProvider(api_key="key")

    def http_error(code):
        return lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("https://provider.test", code, "failure", {}, None)
        )

    monkeypatch.setattr("waitlist.providers.openai.urlopen", http_error(429))
    with pytest.raises(ProviderUnavailableError):
        provider.generate(GreetingRequest("J", "P"))
    monkeypatch.setattr("waitlist.providers.openai.urlopen", http_error(500))
    with pytest.raises(ProviderUnknownError):
        provider.generate(GreetingRequest("J", "P"))
    monkeypatch.setattr(
        "waitlist.providers.openai.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")),
    )
    with pytest.raises(ProviderUnknownError):
        provider.generate(GreetingRequest("J", "P"))
