from runtime.soul import render_default_allies_soul


def test_default_allies_soul_renders_profile_context_without_generator_metadata():
    soul = render_default_allies_soul(
        name="Mira",
        job="Keep the household organised",
        personality="Warm, direct, and concise",
    )

    assert "Mira" in soul
    assert "Keep the household organised" in soul
    assert "Warm, direct, and concise" in soul
    assert "${ALLY_" not in soul
    assert "beta waitlist" not in soul.lower()
    assert "waitlist provider" not in soul.lower()
    assert "## Communication" in soul
    assert "Do not use em dashes" in soul
    assert "—" not in soul
    assert "–" not in soul


def test_default_allies_soul_does_not_expand_placeholders_inside_profile_values():
    soul = render_default_allies_soul(
        name="Mira",
        job="Keep ${ALLY_PERSONALITY} visible",
        personality="Calm",
    )

    assert "Keep ${ALLY_PERSONALITY} visible" in soul
