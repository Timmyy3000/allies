BACKEND_DIR := backend
APP ?=
NAME ?=
MIGRATION_NAME ?=
PORT ?= 8000

.PHONY: help sync app check validate test format lint migrate migrations server shell

help:
	@echo Allies Foundry commands:
	@echo   make sync
	@echo   make app NAME=domain
	@echo   make check
	@echo   make validate
	@echo   make test APP=path
	@echo   make format
	@echo   make lint
	@echo   make migrate APP=label
	@echo   make migrations APP=label MIGRATION_NAME=name
	@echo   make server PORT=8000
	@echo   make shell

sync:
	cd $(BACKEND_DIR) && uv sync

app:
	cd $(BACKEND_DIR) && uv run python manage.py startdomain $(NAME)

check:
	cd $(BACKEND_DIR) && uv run python manage.py check
	cd $(BACKEND_DIR) && uv run python manage.py makemigrations --check --dry-run

validate:
	uv run --locked --project $(BACKEND_DIR) python scripts/validate.py

test:
	cd $(BACKEND_DIR) && uv run pytest $(APP)

format:
	cd $(BACKEND_DIR) && uv run ruff format .

lint:
	cd $(BACKEND_DIR) && uv run ruff check .

migrate:
	cd $(BACKEND_DIR) && uv run python manage.py migrate $(APP)

migrations:
	cd $(BACKEND_DIR) && uv run python manage.py makemigrations $(APP) $(if $(MIGRATION_NAME),--name $(MIGRATION_NAME),)

server:
	cd $(BACKEND_DIR) && uv run python manage.py runserver $(PORT)

shell:
	cd $(BACKEND_DIR) && uv run python manage.py shell
