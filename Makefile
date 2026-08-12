BACKEND_DIR := backend
APP ?=
NAME ?=
MIGRATION_NAME ?=
PORT ?= 8000

.PHONY: help sync app beat check format lint migrate migrations server shell test worker

help:
	@echo Allies Cloud commands:
	@echo   make sync
	@echo   make app NAME=domain
	@echo   make check
	@echo   make test APP=path
	@echo   make format
	@echo   make lint
	@echo   make migrate APP=label
	@echo   make migrations APP=label MIGRATION_NAME=name
	@echo   make server PORT=8000
	@echo   make worker
	@echo   make beat
	@echo   make shell

sync:
	cd $(BACKEND_DIR) && uv sync

app:
	cd $(BACKEND_DIR) && uv run python manage.py startdomain $(NAME)

check:
	cd $(BACKEND_DIR) && uv run python manage.py check
	cd $(BACKEND_DIR) && uv run python manage.py makemigrations --check --dry-run

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

worker:
	cd $(BACKEND_DIR) && uv run celery -A config.celery:app worker --loglevel=INFO --concurrency=1 --prefetch-multiplier=1 --queues=cloud

beat:
	cd $(BACKEND_DIR) && uv run celery -A config.celery:app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule

shell:
	cd $(BACKEND_DIR) && uv run python manage.py shell
