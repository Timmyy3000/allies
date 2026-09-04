FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ARG FLYCTL_VERSION=0.4.81
ARG TARGETARCH=amd64

# These digests come from the official v0.4.81 release checksum asset.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && case "$TARGETARCH" in \
      amd64) flyctl_arch=x86_64; flyctl_checksum=1db7e3f61d91917edfc8a2e661a0a47c6dfbe45f2d64832aa4e372c511514efc ;; \
      arm64) flyctl_arch=arm64; flyctl_checksum=a92d30158b8a8b601b85396d3e9b05445dcee6ed40da6439a4f9db50e7c63979 ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && flyctl_archive="flyctl_${FLYCTL_VERSION}_Linux_${flyctl_arch}.tar.gz" \
    && curl --fail --location --silent --show-error \
      "https://github.com/superfly/flyctl/releases/download/v${FLYCTL_VERSION}/${flyctl_archive}" \
      --output /tmp/flyctl.tar.gz \
    && printf '%s  %s\n' "$flyctl_checksum" /tmp/flyctl.tar.gz | sha256sum --check --status - \
    && tar --extract --gzip --file /tmp/flyctl.tar.gz --directory /usr/local/bin flyctl \
    && ln -s /usr/local/bin/flyctl /usr/local/bin/fly \
    && rm -f /tmp/flyctl.tar.gz \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev

COPY backend/ ./
COPY docker-entrypoint.sh /usr/local/bin/foundry-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/foundry-entrypoint \
    && chmod 0755 /usr/local/bin/foundry-entrypoint

EXPOSE 8000

CMD ["foundry-entrypoint"]
