from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_compose_uses_local_foundry_defaults_and_explicit_opt_in():
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "env_file:\n    - env.staging" in compose
    assert (
        'ALLIES_FOUNDRY_URL: "${ALLIES_LOCAL_FOUNDRY_URL:-http://host.docker.internal:8100}"'
        in compose
    )
    assert (
        'ALLIES_FOUNDRY_SERVICE_TOKEN: "${ALLIES_LOCAL_FOUNDRY_SERVICE_TOKEN:-local-staging-foundry-service-token-change-me-32-bytes}"'
        in compose
    )
    assert (
        'ALLIES_FOUNDRY_EXECUTION_ENABLED: "${ALLIES_LOCAL_FOUNDRY_EXECUTION_ENABLED:-false}"'
        in compose
    )
    assert "${ALLIES_FOUNDRY_URL" not in compose
    assert "${ALLIES_FOUNDRY_SERVICE_TOKEN" not in compose
    assert "${ALLIES_FOUNDRY_EXECUTION_ENABLED" not in compose


def test_compose_event_token_example_is_nonempty_and_shared():
    example = (REPOSITORY_ROOT / "env.staging.example").read_text(encoding="utf-8")
    line = next(
        line
        for line in example.splitlines()
        if line.startswith("ALLIES_FOUNDRY_EVENT_SERVICE_TOKEN=")
    )

    assert line.partition("=")[2]
