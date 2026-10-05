import pytest


@pytest.fixture(autouse=True)
def legacy_tests_run_without_beta_invites(settings):
    """Keep pre-invite fixtures focused; invite tests opt into the gate."""

    settings.ALLIES_BETA_INVITES_REQUIRED = False


@pytest.fixture(autouse=True)
def tests_scan_uploads_for_malware(settings):
    """Exercise the scanner path by default; scan-off tests opt out."""

    settings.ALLIES_FILE_MALWARE_SCAN = True
