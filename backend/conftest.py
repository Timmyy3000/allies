import pytest


@pytest.fixture(autouse=True)
def legacy_tests_run_without_beta_invites(settings):
    """Keep pre-invite fixtures focused; invite tests opt into the gate."""

    settings.ALLIES_BETA_INVITES_REQUIRED = False
