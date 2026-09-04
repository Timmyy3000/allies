# The upstream image owns Hermes, /init, s6 supervision, and the /opt/data
# volume contract.  This image only adds the Allies provider and its locked
# local-memory dependencies.
FROM nousresearch/hermes-agent:latest@sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca

ARG HERMES_SOURCE_SHA=36cb5ae5530a75def7df3195e49b7a4aa2add482
ARG ALLIES_WRAPPER_VERSION=0.1.0
ARG SOURCE_DATE_EPOCH=0

USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALLIES_MNEMOSYNE_POLICY=allies-mnemosyne-v1

# The wheelhouse is produced by the hermes-image-wheelhouse Make target/CI
# job.  Installation is deliberately offline and hash checked in the image.
COPY requirements.lock /tmp/allies-mnemosyne-requirements.lock
COPY wheelhouse/ /tmp/allies-mnemosyne-wheelhouse/
COPY verify_wheelhouse.py /tmp/allies-verify-wheelhouse.py
RUN /opt/hermes/.venv/bin/python /tmp/allies-verify-wheelhouse.py \
      /tmp/allies-mnemosyne-requirements.lock \
      /tmp/allies-mnemosyne-wheelhouse \
    && uv pip install \
      --python /opt/hermes/.venv/bin/python \
      --no-index \
      --no-deps \
      /tmp/allies-mnemosyne-wheelhouse/mnemosyne_hermes-0.5.0-py3-none-any.whl \
      /tmp/allies-mnemosyne-wheelhouse/mnemosyne_memory-3.15.1-py3-none-any.whl \
      /tmp/allies-mnemosyne-wheelhouse/pyyaml-6.0.3-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl \
    && rm -rf /tmp/allies-mnemosyne-requirements.lock \
      /tmp/allies-mnemosyne-wheelhouse \
      /tmp/allies-verify-wheelhouse.py

# Copy the wrapper into the sealed Hermes environment without assuming a
# particular site-packages path in the pinned Python minor release.
COPY provider/allies_mnemosyne/ /opt/allies-mnemosyne-provider/allies_mnemosyne/
RUN site=$(/opt/hermes/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])') \
    && cp -a /opt/allies-mnemosyne-provider/allies_mnemosyne "$site/" \
    && rm -rf /opt/allies-mnemosyne-provider

# Pinned Hermes scans this bundled directory before user plugins.  Keep its
# registration bridge separate from the installed wrapper package.
COPY plugins/memory/allies_mnemosyne/ /opt/hermes/plugins/memory/allies_mnemosyne/

# Keep the private Allies transcript seam as a small, pinned-source overlay.
# A rejected hunk must fail the image build instead of silently shipping an
# image without the capability the runtime expects.
COPY patches/first-turn-transcript-bootstrap.patch /tmp/allies-first-turn-transcript-bootstrap.patch
RUN cd /opt/hermes \
    && git apply --check --whitespace=nowarn /tmp/allies-first-turn-transcript-bootstrap.patch \
    && git apply --whitespace=nowarn /tmp/allies-first-turn-transcript-bootstrap.patch \
    && rm -f /tmp/allies-first-turn-transcript-bootstrap.patch

LABEL org.opencontainers.image.title="Allies Hermes with Mnemosyne" \
      org.opencontainers.image.description="Policy-fenced profile-local Mnemosyne provider" \
      org.opencontainers.image.version="${ALLIES_WRAPPER_VERSION}" \
      org.opencontainers.image.source="https://github.com/NousResearch/hermes-agent" \
      org.opencontainers.image.revision="${HERMES_SOURCE_SHA}" \
      org.opencontainers.image.base.digest="sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca" \
      io.allies.hermes.source-sha="${HERMES_SOURCE_SHA}" \
      io.allies.mnemosyne.policy-version="allies-mnemosyne-v1" \
      io.allies.build.source-date-epoch="${SOURCE_DATE_EPOCH}"

# Import/status smoke runs at build time.  No ENTRYPOINT or CMD is declared:
# /init and the upstream entrypoint-dispatch contract remain inherited.
RUN /opt/hermes/.venv/bin/python -c \
    'from allies_mnemosyne import AlliesMnemosyneProvider; \
     p = AlliesMnemosyneProvider(); \
     assert p.name == "allies_mnemosyne"; \
     assert p.get_tool_schemas() == []'

USER hermes
