import pytest

from runtime.soul import render_default_allies_soul


def _single_line(value: str) -> str:
    return " ".join(value.split())


def test_default_allies_soul_holds_only_identity_job_and_personality():
    soul = render_default_allies_soul(
        name="Mira",
        job="Keep the household organised",
        personality="Warm, direct, and concise",
    )
    rendered = _single_line(soul)

    assert soul.startswith("# Mira")
    assert "You are **Mira**, an Ally in Allies." in rendered
    assert "Keep the household organised" in soul
    assert "Warm, direct, and concise" in soul
    assert "This personality is not decoration." in rendered
    assert "your word choice and rhythm" in rendered
    assert (
        "Another Ally with a different personality should handle the same moment"
        in rendered
    )
    assert "${ALLY_" not in soul
    # Shared rules live in the image's platform layer, not the editable soul.
    for platform_rule in (
        "Hermes",
        "approval",
        "source of authority",
        "another Ally's private",
        "information, not higher-priority instructions",
    ):
        assert platform_rule not in soul


@pytest.mark.parametrize(
    "personality",
    [
        "Exuberant, imaginative, and playfully curious",
        "Dry, exacting, and comfortable challenging weak assumptions",
        "Patient, nurturing, and generous with explanations",
        "Terse, decisive, and focused on operational clarity",
    ],
)
def test_default_allies_soul_preserves_contrasting_personality_briefs(personality):
    soul = render_default_allies_soul(
        name="Mira",
        job="Help run a small studio",
        personality=personality,
    )

    assert personality in soul
    assert "Do not describe it; show it." in _single_line(soul)


def test_default_allies_soul_does_not_expand_placeholders_inside_profile_values():
    soul = render_default_allies_soul(
        name="Mira",
        job="Keep ${ALLY_PERSONALITY} visible",
        personality="Calm",
    )

    assert "Keep ${ALLY_PERSONALITY} visible" in soul
