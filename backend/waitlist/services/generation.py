"""Greeting provider selection and output validation."""

import re
from typing import Any

from django.conf import settings

from ..exceptions import GenerationUnavailable, WaitlistValidationError
from ..providers.fake import FakeGreetingProvider
from ..providers.openai import OpenAIResponsesProvider

PROHIBITED_CLAIMS = re.compile(
    r"\b(?:i|we|this assistant)\s+(?:have|has|already|just|successfully|can|will)\b"
    r".{0,80}\b(?:account|workspace|ally|conversation|tool|memory|file|message)\b",
    re.IGNORECASE,
)


def validate_output(value: Any, *, ally_name: str = "") -> str:
    max_chars = int(
        getattr(settings, "ALLIES_WAITLIST_GENERATION_MAX_OUTPUT_CHARS", 1200)
    )
    if not isinstance(value, str):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    text = value.strip()
    if (
        not text
        or len(text) > max_chars
        or "\x00" in text
        or "<" in text
        or ">" in text
    ):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    if PROHIBITED_CLAIMS.search(text):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    normalized_ally_name = ally_name.strip()
    if normalized_ally_name and re.search(
        rf"(?<!\w){re.escape(normalized_ally_name)}(?!\w)",
        text,
        re.IGNORECASE,
    ):
        raise WaitlistValidationError("greeting output is invalid", field="greeting")
    return text


def get_provider():
    if not bool(getattr(settings, "ALLIES_WAITLIST_PROVIDER_ENABLED", False)):
        raise GenerationUnavailable("generation unavailable")
    provider = str(getattr(settings, "ALLIES_WAITLIST_PROVIDER", "openai"))
    if provider == "fake":
        return FakeGreetingProvider()
    if provider == "openai":
        return OpenAIResponsesProvider()
    raise GenerationUnavailable("generation unavailable")
