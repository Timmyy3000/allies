from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_startdomain_dry_run_does_not_write(tmp_path: Path, capsys):
    call_command(
        "startdomain",
        "sample_domain",
        directory=str(tmp_path),
        dry_run=True,
    )

    assert not (tmp_path / "sample_domain").exists()
    assert "Would create" in capsys.readouterr().out


def test_startdomain_creates_standard_shape(tmp_path: Path):
    call_command("startdomain", "sample_domain", directory=str(tmp_path))

    app = tmp_path / "sample_domain"
    expected = [
        "apps.py",
        "models.py",
        "api/register.py",
        "api/controllers/__init__.py",
        "services/__init__.py",
        "migrations/__init__.py",
        "tests/test_api.py",
    ]
    assert all((app / path).exists() for path in expected)
    assert 'name = "sample_domain"' in (app / "apps.py").read_text()


def test_startdomain_points_to_the_api_root(tmp_path: Path, capsys):
    call_command("startdomain", "sample_domain", directory=str(tmp_path))

    assert "config/api.py" in capsys.readouterr().out
    assert (Path(__file__).resolve().parents[2] / "config" / "api.py").exists()


@pytest.mark.parametrize("name", ["", "not-valid", "class"])
def test_startdomain_rejects_invalid_names(tmp_path: Path, name: str):
    with pytest.raises(CommandError):
        call_command("startdomain", name, directory=str(tmp_path))
