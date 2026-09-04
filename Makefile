BACKEND_DIR := backend
APP ?=
NAME ?=
MIGRATION_NAME ?=
PORT ?= 8000

# Preserve the production-safe default for every target. Local development
# commands should set DJANGO_DEBUG=true explicitly before invoking make.
DJANGO_DEBUG ?= false
export DJANGO_DEBUG

.PHONY: help sync app check validate test runtime-test format lint runtime-lint migrate migrations server shell hermes-image-wheelhouse hermes-image-build hermes-image-test

HERMES_IMAGE_CONTEXT ?= runtime/hermes-image
HERMES_IMAGE_TAG ?= allies/hermes-mnemosyne:dev
HERMES_IMAGE_PLATFORM ?= linux/amd64
HERMES_IMAGE_PYTHON_VERSION ?= 313
# The pinned Debian 13 base has glibc 2.41; Mnemosyne's current cp313
# mmh3/onnxruntime wheels target manylinux_2_28.
HERMES_IMAGE_PIP_PLATFORM ?= manylinux_2_28_x86_64
HERMES_IMAGE_SOURCE_DATE_EPOCH ?= $(shell git show -s --format=%ct HEAD)
HERMES_IMAGE_ATTESTATION ?= /tmp/allies-hermes-mnemosyne.oci.tar

help:
	@echo Allies Foundry commands:
	@echo   make sync
	@echo   make app NAME=domain
	@echo   make check
	@echo   make validate
	@echo   make test APP=path
	@echo   make runtime-test
	@echo   make format
	@echo   make lint
	@echo   make migrate APP=label
	@echo   make migrations APP=label MIGRATION_NAME=name
	@echo   make server PORT=8000
	@echo   make shell
	@echo   make hermes-image-build

sync:
	cd $(BACKEND_DIR) && uv sync --locked
	uv sync --project runtime --locked

app:
	cd $(BACKEND_DIR) && uv run python manage.py startdomain $(NAME)

check:
	cd $(BACKEND_DIR) && uv run --locked python manage.py check
	cd $(BACKEND_DIR) && uv run --locked python manage.py makemigrations --check --dry-run
	uv lock --check --project runtime

validate:
	uv run --locked --project $(BACKEND_DIR) python scripts/validate.py

test:
	cd $(BACKEND_DIR) && uv run --locked pytest $(APP)

runtime-test:
	cd runtime && uv run --locked pytest --cov=allies_runtime --cov-report=xml:coverage.xml

format:
	cd $(BACKEND_DIR) && uv run --locked ruff format .
	cd runtime && uv run --locked ruff format .

lint:
	cd $(BACKEND_DIR) && uv run --locked ruff check .
	cd runtime && uv run --locked ruff check .

runtime-lint:
	cd runtime && uv run --locked ruff check .

migrate:
	cd $(BACKEND_DIR) && uv run --locked python manage.py migrate $(APP)

migrations:
	cd $(BACKEND_DIR) && uv run --locked python manage.py makemigrations $(APP) $(if $(MIGRATION_NAME),--name $(MIGRATION_NAME),)

server:
	cd $(BACKEND_DIR) && uv run --locked python manage.py runserver $(PORT)

shell:
	cd $(BACKEND_DIR) && uv run --locked python manage.py shell

hermes-image-wheelhouse:
	python -m pip download --only-binary=:all: --no-deps --require-hashes \
		--platform $(HERMES_IMAGE_PIP_PLATFORM) \
		--python-version $(HERMES_IMAGE_PYTHON_VERSION) --implementation cp --abi cp313 \
		--index-url https://pypi.org/simple \
		--dest $(HERMES_IMAGE_CONTEXT)/wheelhouse \
		-r $(HERMES_IMAGE_CONTEXT)/requirements.lock

hermes-image-build: hermes-image-wheelhouse
	docker buildx build \
		--platform $(HERMES_IMAGE_PLATFORM) --provenance=true --sbom=true \
		--output type=oci,dest=$(HERMES_IMAGE_ATTESTATION) \
		--build-arg SOURCE_DATE_EPOCH=$(HERMES_IMAGE_SOURCE_DATE_EPOCH) \
		--tag $(HERMES_IMAGE_TAG) --file $(HERMES_IMAGE_CONTEXT)/Dockerfile $(HERMES_IMAGE_CONTEXT)
	docker buildx build \
		--platform $(HERMES_IMAGE_PLATFORM) --provenance=false --sbom=false --load \
		--build-arg SOURCE_DATE_EPOCH=$(HERMES_IMAGE_SOURCE_DATE_EPOCH) \
		--tag $(HERMES_IMAGE_TAG) --file $(HERMES_IMAGE_CONTEXT)/Dockerfile $(HERMES_IMAGE_CONTEXT)

hermes-image-test: hermes-image-build
	docker run --rm --entrypoint /opt/hermes/.venv/bin/python $(HERMES_IMAGE_TAG) \
		-c 'from plugins.memory import load_memory_provider; p=load_memory_provider("allies_mnemosyne"); assert p is not None; p.initialize("smoke-session", hermes_home="/tmp/ally-smoke", profile_root="/tmp/ally-smoke", agent_identity="ally-v1-00000000000000000000000000000001", agent_context="conversation", memory_mode="context_only", tools=[]); assert p.status()["available"] is True; assert p.get_tool_schemas() == []; assert p._delegate._beam.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000; print(p.status()); p.shutdown()'
