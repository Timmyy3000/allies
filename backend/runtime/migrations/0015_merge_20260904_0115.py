from typing import ClassVar

from django.db import migrations


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("runtime", "0014_profile_memory_seed_v2"),
        ("runtime", "0014_reserve_server_terminal_sequence"),
    ]

    operations: ClassVar[list] = []
