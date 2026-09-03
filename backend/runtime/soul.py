from pathlib import Path
from string import Template

_SOUL_TEMPLATE = Template(
    Path(__file__).with_name("default_allies_soul.md").read_text(encoding="utf-8")
)


def render_default_allies_soul(*, name: str, job: str, personality: str) -> str:
    return _SOUL_TEMPLATE.substitute(
        ALLY_NAME=name,
        ALLY_JOB=job,
        ALLY_PERSONALITY=personality,
    )
