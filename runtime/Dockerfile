# The base manifest is immutable; the runtime image is released by digest.
FROM python:3.13-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

RUN groupadd --gid 10001 allies-publication

COPY allies_runtime /app/allies_runtime
COPY pyproject.toml uv.lock /app/

RUN python -c 'import tomllib; lock=tomllib.load(open("uv.lock", "rb")); p=next(p for p in lock["package"] if p["name"] == "pyyaml"); print("PyYAML==" + p["version"] + " " + " ".join("--hash=" + w["hash"] for w in p["wheels"]))' > /tmp/runtime-requirements.txt \
    && pip install --no-cache-dir --no-deps --only-binary=:all: --require-hashes -r /tmp/runtime-requirements.txt \
    && rm /tmp/runtime-requirements.txt \
    && python -c 'import yaml; import allies_runtime.profile_store' \
    && python -m compileall -q /app/allies_runtime

# Fly's container command is intentionally not overridden: this is the
# image-baked process and therefore the runtime container's PID 1.
ENTRYPOINT ["python", "-m", "allies_runtime"]
