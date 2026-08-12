# The base manifest is immutable; the runtime image is released by digest.
FROM python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY allies_runtime /app/allies_runtime
COPY pyproject.toml uv.lock /app/

# The package has no network/runtime dependency.  The lockfile is copied into
# the image as provenance and is checked in CI before an image is published.
RUN python -m compileall -q /app/allies_runtime

# Fly's container command is intentionally not overridden: this is the
# image-baked process and therefore the runtime container's PID 1.
ENTRYPOINT ["python", "-m", "allies_runtime"]
