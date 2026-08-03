# Allies Cloud

Private managed-product control plane for Allies.

The Django application lives in `backend/`. Repository-wide deployment,
infrastructure, automation, and engineering configuration belongs at the
repository root.

## Development

```powershell
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

Create Django domain apps from `backend/` as they become necessary:

```powershell
uv run python manage.py startapp <domain>
```
