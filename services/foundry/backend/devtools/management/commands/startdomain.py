from __future__ import annotations

import keyword
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create an Allies domain app with the standard backend structure."

    def add_arguments(self, parser):
        parser.add_argument("name", help="The Python package name for the domain app.")
        parser.add_argument(
            "--directory",
            default=".",
            help="Parent directory in which to create the app.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the files that would be created without writing them.",
        )

    def handle(self, *args, **options):
        name = options["name"].strip()
        self._validate_name(name)

        parent = Path(options["directory"]).expanduser().resolve()
        target = parent / name
        if target.exists():
            raise CommandError(f"Destination already exists: {target}")

        files = self._files_for(name)
        if options["dry_run"]:
            self.stdout.write(f"Would create {target}:")
            for relative_path in files:
                self.stdout.write(f"  {relative_path}")
            self.stdout.write(
                "Then add the app to INSTALLED_APPS and register its API explicitly."
            )
            return

        target.mkdir(parents=True)
        for relative_path, content in files.items():
            path = target / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        self.stdout.write(self.style.SUCCESS(f"Created domain app at {target}"))
        self.stdout.write("Next steps:")
        self.stdout.write(f'  Add "{name}" to INSTALLED_APPS.')
        self.stdout.write(
            f"  Call {name}.api.register.register(api) from config/api.py."
        )

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name:
            raise CommandError("The app name is required.")
        if not name.isidentifier():
            raise CommandError(
                "The app name must be a valid Python identifier using letters, "
                "numbers, and underscores."
            )
        if keyword.iskeyword(name):
            raise CommandError(f"The app name cannot be the Python keyword {name!r}.")

    @staticmethod
    def _files_for(name: str) -> dict[str, str]:
        class_name = "".join(part.capitalize() for part in name.split("_")) + "Config"
        app_config = f"""from django.apps import AppConfig


class {class_name}(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "{name}"
"""

        registrar = """from ninja_extra import NinjaExtraAPI


def register(api: NinjaExtraAPI) -> None:
    return None
"""

        return {
            "__init__.py": "",
            "apps.py": app_config,
            "admin.py": "",
            "models.py": "",
            "api/__init__.py": "",
            "api/register.py": registrar,
            "api/schemas.py": "",
            "api/controllers/__init__.py": "",
            "services/__init__.py": "",
            "migrations/__init__.py": "",
            "tests/__init__.py": "",
            "tests/test_models.py": "",
            "tests/test_services.py": "",
            "tests/test_api.py": "",
        }
