import base64

import pytest

from integrations.exceptions import IntegrationUnavailable
from integrations.services.vault import (
    VAULT_KEY_CURRENT_VERSION,
    seal_refresh_token,
    unseal_refresh_token,
    vault_key,
)

VAULT_KEY_B64 = base64.urlsafe_b64encode(b"v" * 32).decode()


@pytest.mark.django_db
def test_vault_roundtrip(settings):
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = VAULT_KEY_B64
    ciphertext, version = seal_refresh_token("refresh-token-abc")
    assert version == VAULT_KEY_CURRENT_VERSION
    assert unseal_refresh_token(ciphertext, key_version=version) == "refresh-token-abc"
    assert b"refresh-token-abc" not in bytes(ciphertext)


@pytest.mark.django_db
def test_vault_unknown_version_fails_closed(settings):
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = VAULT_KEY_B64
    ciphertext, _ = seal_refresh_token("refresh-token-abc")
    with pytest.raises(IntegrationUnavailable):
        unseal_refresh_token(ciphertext, key_version=999)


@pytest.mark.django_db
def test_vault_missing_key_fails_closed(settings):
    settings.DEBUG = False
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = ""
    with pytest.raises(IntegrationUnavailable):
        vault_key(1)
    with pytest.raises(IntegrationUnavailable):
        seal_refresh_token("refresh-token-abc")


@pytest.mark.django_db
def test_vault_tampered_ciphertext_fails_closed(settings):
    settings.ALLIES_INTEGRATIONS_VAULT_KEY = VAULT_KEY_B64
    ciphertext, version = seal_refresh_token("refresh-token-abc")
    tampered = bytearray(bytes(ciphertext))
    tampered[10] ^= 0xFF
    with pytest.raises(IntegrationUnavailable):
        unseal_refresh_token(bytes(tampered), key_version=version)
