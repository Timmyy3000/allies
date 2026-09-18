"""Greeting provider selection and output validation."""

import re
from typing import Any

from django.conf import settings

from ..exceptions import GenerationUnavailable, WaitlistValidationError
from ..providers.fake import FakeGreetingProvider
from ..providers.openai import OpenAIResponsesProvider

PROHIBITED_CLAIMS = re.compile(
    r"\b(?:i|we|this assistant)\s+(?:"
    r"(?:have|has)\s+(?:access\s+to\s+)?(?:your\s+)?"
    r"(?:account|workspace|ally|conversation|tool|memory|file|message)s?\b"
    r"|(?:already|just|successfully)\s+"
    r"(?:accessed|opened|read|wrote|sent|connected(?:\s+to)?|used|inspected|checked)"
    r"\b.{0,40}\b(?:account|workspace|ally|conversation|tool|memory|file|message)s?\b"
    r"|(?:can|will)\s+"
    r"(?:access|open|read|write|send|connect(?:\s+to)?|use|inspect|check)"
    r"\b.{0,40}\b(?:account|workspace|ally|conversation|tool|memory|file|message)s?\b"
    r")",
    re.IGNORECASE,
)
PROHIBITED_PRODUCT_FRAMING = re.compile(r"\bpreview\b", re.IGNORECASE)


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
    if PROHIBITED_PRODUCT_FRAMING.search(text):
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
