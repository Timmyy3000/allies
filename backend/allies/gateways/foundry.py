from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from allies.exceptions import ProvisioningRejected, ProvisioningRetryable

_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class ProfileProvisioningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(default=1, ge=1, le=1)
    workspace_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    ally_ref: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    request_fingerprint: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    job: StrictStr = Field(min_length=1, max_length=200, pattern=r"^[^\x00\r]*$")
    personality: StrictStr = Field(
        min_length=1, max_length=4000, pattern=r"^[^\x00\r]*$"
    )


class ProfileProvisioningReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: StrictInt = Field(ge=1, le=1)
    binding_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    operation_id: StrictStr = Field(min_length=36, max_length=36, pattern=_UUID_PATTERN)
    request_fingerprint: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    status: StrictStr = Field(
        pattern=r"^(pending|active|cleanup_pending|deprovisioned|repair_required)$"
    )
    evidence_digest: StrictStr = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def provision_profile(
    payload: ProfileProvisioningRequest,
) -> ProfileProvisioningReceipt:
    origin = str(getattr(settings, "ALLIES_FOUNDRY_URL", ""))
    token = str(getattr(settings, "ALLIES_FOUNDRY_SERVICE_TOKEN", ""))
    parsed = urlparse(origin)
    if not token or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProvisioningRetryable("foundry unavailable")
    request = Request(
        urljoin(origin.rstrip("/") + "/", "api/v1/internal/profile-provisioning"),
        data=payload.model_dump_json().encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect).open(
            request,
            timeout=float(getattr(settings, "ALLIES_FOUNDRY_TIMEOUT_SECONDS", 5.0)),
        ) as response:
            raw = response.read(65_537)
            if len(raw) > 65_536:
                raise ProvisioningRejected("foundry response too large")
    except HTTPError as exc:
        if exc.code in {408, 429} or exc.code >= 500:
            raise ProvisioningRetryable("foundry unavailable") from exc
        raise ProvisioningRejected("foundry rejected request") from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise ProvisioningRetryable("foundry outcome unknown") from exc
    try:
        return ProfileProvisioningReceipt.model_validate_json(raw)
    except ValueError as exc:
        raise ProvisioningRejected("foundry response invalid") from exc
