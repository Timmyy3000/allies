import pytest

from waitlist.exceptions import WaitlistValidationError
from waitlist.services.generation import validate_output


def test_validate_output_leaves_name_style_to_provider_prompt():
    greeting = "Hola, Roban!"

    assert validate_output(greeting, ally_name="Roban") == greeting


def test_validate_output_allows_ally_name_as_job_word():
    greeting = (
        "Hi, I’m Quiz. I can create a clear, engaging quiz for you. "
        "What topic and difficulty would you like?"
    )

    assert validate_output(greeting, ally_name="Quiz") == greeting


@pytest.mark.parametrize(
    "greeting",
    [
        "Hi, Roban here. What would you like to start with?",
        "Hey, I'm Roban. I can help you get better at French. Where should we start?",
        "Hi, I’m Roban. What is the biggest thing you struggle with financially?",
    ],
)
def test_validate_output_allows_ally_name_in_self_introduction(greeting):
    assert validate_output(greeting, ally_name="Roban") == greeting


def test_validate_output_does_not_reject_ally_name_as_substring():
    assert validate_output("Hola, Robando!", ally_name="Roban") == "Hola, Robando!"


def test_validate_output_rejects_preview_framing():
    with pytest.raises(WaitlistValidationError):
        validate_output("Hi there! I am your preview Ally.")


def test_validate_output_allows_contextual_help_with_resource():
    greeting = "I can help you organize your workspace. What should we start with?"
    assert validate_output(greeting) == greeting


@pytest.mark.parametrize(
    "greeting",
    [
        "I can access your workspace. What should we start with?",
        "I have access to your files. What should we start with?",
        "I already read your messages. What should we start with?",
    ],
)
def test_validate_output_rejects_false_resource_claims(greeting):
    with pytest.raises(WaitlistValidationError):
        validate_output(greeting)
