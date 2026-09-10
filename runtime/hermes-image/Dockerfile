# The upstream image owns Hermes, /init, s6 supervision, and the /opt/data
# volume contract.  This image only adds the Allies provider and its locked
# local-memory dependencies.
FROM nousresearch/hermes-agent:latest@sha256:b6f18532e2c082ef6686c659fc222427e41fde3eed08aa058411f0ea5ab705ca

ARG HERMES_SOURCE_SHA=36cb5ae5530a75def7df3195e49b7a4aa2add482
ARG ALLIES_WRAPPER_VERSION=0.1.0
ARG SOURCE_DATE_EPOCH=0
ARG TARGETARCH

USER root
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALLIES_MNEMOSYNE_POLICY=allies-mnemosyne-v1

# Pin the skill's executable so it is ready without installation during wake.
RUN case "$TARGETARCH" in \
      amd64) archive=xurl_Linux_x86_64.tar.gz; checksum=ccfc4b3ca5240565da650ef003b51d7f887eabe0c6e3797802410240289d4feb ;; \
      arm64) archive=xurl_Linux_arm64.tar.gz; checksum=22474398fb55fe2ae242cc1b940dd5d92c0083508d108ec95922d1adacd2bb76 ;; \
      *) echo "Unsupported xurl architecture" >&2; exit 1 ;; \
    esac \
    && curl --fail --location --retry 3 --connect-timeout 15 --max-time 120 \
      "https://github.com/xdevplatform/xurl/releases/download/v1.3.1/$archive" -o /tmp/xurl.tar.gz \
    && echo "$checksum  /tmp/xurl.tar.gz" | sha256sum -c - \
    && mkdir /tmp/xurl-release \
    && tar -xzf /tmp/xurl.tar.gz -C /tmp/xurl-release \
    && install -m 0755 /tmp/xurl-release/xurl /usr/local/bin/xurl \
    && mkdir -p /usr/local/share/licenses/xurl \
    && install -m 0644 /tmp/xurl-release/LICENSE /usr/local/share/licenses/xurl/LICENSE \
    && xurl --help >/dev/null \
    && rm -rf /tmp/xurl-release /tmp/xurl.tar.gz

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

# Keep the shared catalog immutable and separate from Hermes' writable profile
# skills.  The build script validates provenance before copying any content.
COPY build_skills_catalog.py /tmp/allies-build-skills-catalog.py
COPY skills/allies-skill-discovery/ /tmp/allies-skill-discovery/
RUN /opt/hermes/.venv/bin/python /tmp/allies-build-skills-catalog.py \
    && rm -rf /tmp/allies-build-skills-catalog.py /tmp/allies-skill-discovery

# The pinned base already ships the helper used by youtube-content.  Keep the
# assertion at image build so profile wake never installs it.
RUN /opt/hermes/.venv/bin/python -c \
    'import importlib.metadata as m; assert m.version("youtube-transcript-api") == "1.2.4"'

# Copy the wrapper into the sealed Hermes environment without assuming a
# particular site-packages path in the pinned Python minor release.
COPY provider/allies_mnemosyne/ /opt/allies-mnemosyne-provider/allies_mnemosyne/
RUN site=$(/opt/hermes/.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])') \
    && cp -a /opt/allies-mnemosyne-provider/allies_mnemosyne "$site/" \
    && rm -rf /opt/allies-mnemosyne-provider

# Pinned Hermes scans this bundled directory before user plugins.  Keep its
# registration bridge separate from the installed wrapper package.
COPY plugins/memory/allies_mnemosyne/ /opt/hermes/plugins/memory/allies_mnemosyne/

# This tool is only added to the agent's enabled toolsets for the marked
# scheduled-routine stream. Its handler is side-effect-free and the runtime
# validates the typed call again from Hermes' terminal transcript.
COPY plugins/routine-result/ /opt/hermes/plugins/routine-result/

# Hermes connects to a root-owned runtime socket but cannot replace it.
RUN groupadd --gid 10001 allies-publication \
    && usermod --append --groups allies-publication "$(getent passwd 10000 | cut -d: -f1)"

COPY --chmod=0755 allies-volume-boundary.sh /opt/hermes/docker/allies-volume-boundary.sh
COPY patches/volume-ownership-boundary.patch /tmp/allies-volume-ownership-boundary.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-volume-ownership-boundary.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-volume-ownership-boundary.patch \
    && git apply --whitespace=nowarn /tmp/allies-volume-ownership-boundary.patch \
    && rm -f /tmp/allies-volume-ownership-boundary.patch

# Keep the private Allies transcript seam as a small, pinned-source overlay.
# A rejected hunk must fail the image build instead of silently shipping an
# image without the capability the runtime expects.
COPY patches/first-turn-transcript-bootstrap.patch /tmp/allies-first-turn-transcript-bootstrap.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-first-turn-transcript-bootstrap.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-first-turn-transcript-bootstrap.patch \
    && git apply --whitespace=nowarn /tmp/allies-first-turn-transcript-bootstrap.patch \
    && rm -f /tmp/allies-first-turn-transcript-bootstrap.patch

COPY patches/meaningful-activity.patch /tmp/allies-meaningful-activity.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-meaningful-activity.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-meaningful-activity.patch \
    && git apply --whitespace=nowarn /tmp/allies-meaningful-activity.patch \
    && rm -f /tmp/allies-meaningful-activity.patch

COPY patches/approval-flow.patch /tmp/allies-approval-flow.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-approval-flow.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-approval-flow.patch \
    && git apply --whitespace=nowarn /tmp/allies-approval-flow.patch \
    && rm -f /tmp/allies-approval-flow.patch

# The provider publishes its narrow tool schemas during initialization.  Keep
# Hermes dispatch in sync with that lifecycle so advertised memory tools route
# in the active profile instead of falling through as unknown tools.
COPY patches/memory-provider-tool-routing.patch /tmp/allies-memory-provider-tool-routing.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-memory-provider-tool-routing.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-memory-provider-tool-routing.patch \
    && git apply --whitespace=nowarn /tmp/allies-memory-provider-tool-routing.patch \
    && rm -f /tmp/allies-memory-provider-tool-routing.patch

# Marked routine streams receive a bounded ephemeral instruction and the
# isolated typed-result toolset. Keep this source-pinned overlay fail-closed.
COPY patches/routine-result-protocol.patch /tmp/allies-routine-result-protocol.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-routine-result-protocol.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-routine-result-protocol.patch \
    && git apply --whitespace=nowarn /tmp/allies-routine-result-protocol.patch \
    && rm -f /tmp/allies-routine-result-protocol.patch

# The runtime sends only a bounded staged-file manifest. This source-pinned
# overlay keeps the context ephemeral and rejects bytes or routine use.
COPY patches/incoming-file-context.patch /tmp/allies-incoming-file-context.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-incoming-file-context.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-incoming-file-context.patch \
    && git apply --whitespace=nowarn /tmp/allies-incoming-file-context.patch \
    && rm -f /tmp/allies-incoming-file-context.patch

# The runtime supplies this opaque request context only for marked normal
# conversation streams. The tool receives the Hermes tool-call ID separately.
COPY plugins/file-publication/ /opt/hermes/plugins/file-publication/
COPY patches/file-publication-protocol.patch /tmp/allies-file-publication-protocol.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-file-publication-protocol.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-file-publication-protocol.patch \
    && git apply --whitespace=nowarn /tmp/allies-file-publication-protocol.patch \
    && rm -f /tmp/allies-file-publication-protocol.patch

COPY smoke_routine_result_tool.py /tmp/allies-smoke-routine-result-tool.py
COPY smoke_incoming_file_context.py /tmp/allies-smoke-incoming-file-context.py
COPY smoke_file_publication_tool.py /tmp/allies-smoke-file-publication-tool.py
RUN /opt/hermes/.venv/bin/python /tmp/allies-smoke-incoming-file-context.py \
    && rm -f /tmp/allies-smoke-incoming-file-context.py
RUN /opt/hermes/.venv/bin/python /tmp/allies-smoke-routine-result-tool.py \
    && rm -f /tmp/allies-smoke-routine-result-tool.py
RUN PYTHONPATH=/opt/hermes /opt/hermes/.venv/bin/python /tmp/allies-smoke-file-publication-tool.py \
    && rm -f /tmp/allies-smoke-file-publication-tool.py

COPY plugins/routines/ /opt/hermes/plugins/routines/
COPY allies_routines.py /opt/hermes/tools/allies_routines.py
COPY patches/routine-management-tool.patch /tmp/allies-routine-management-tool.patch
RUN cd /opt/hermes \
    && sed -i 's/\r$//' /tmp/allies-routine-management-tool.patch \
    && git apply --check --whitespace=nowarn /tmp/allies-routine-management-tool.patch \
    && git apply --whitespace=nowarn /tmp/allies-routine-management-tool.patch \
    && rm -f /tmp/allies-routine-management-tool.patch

COPY smoke_routine_management.py /tmp/allies-smoke-routine-management.py
RUN /opt/hermes/.venv/bin/python /tmp/allies-smoke-routine-management.py \
    && rm -f /tmp/allies-smoke-routine-management.py

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

# Upstream initializes mounted storage as root, then drops service privileges.
USER root
