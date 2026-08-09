"""Read-only observation of Hermes' durable volume marker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .evidence import VolumeVisibility


@dataclass(frozen=True, slots=True)
class VolumeMarkerObservation:
    marker_path: str
    marker_exists: bool
    visibility: VolumeVisibility


def marker_within_volume(marker_path: str | Path, volume_root: str | Path) -> bool:
    marker = Path(marker_path).resolve()
    root = Path(volume_root).resolve()
    try:
        marker.relative_to(root)
    except ValueError:
        return False
    return True


def observe_volume_marker(
    marker_path: str | Path,
    *,
    volume_root: str | Path = "/opt/data",
) -> VolumeMarkerObservation:
    """Inspect marker visibility without creating or modifying any file."""

    marker = Path(marker_path)
    root = Path(volume_root)
    if not marker_within_volume(marker, root):
        raise ValueError("volume marker must remain under the Hermes volume root")
    exists = marker.is_file()
    if not root.exists():
        visibility = VolumeVisibility.ABSENT
    elif not exists:
        visibility = (
            VolumeVisibility.READ_ONLY
            if not os.access(root, os.W_OK)
            else VolumeVisibility.READ_WRITE
        )
    elif os.access(marker, os.W_OK):
        visibility = VolumeVisibility.READ_WRITE
    else:
        visibility = VolumeVisibility.READ_ONLY
    return VolumeMarkerObservation(str(marker), exists, visibility)


def marker_namespace(run_id: str) -> PurePosixPath:
    if not run_id or "/" in run_id or ".." in run_id:
        raise ValueError("run_id cannot escape the marker namespace")
    return PurePosixPath("/opt/data/.allies-proof/fnd-004") / run_id


__all__ = [
    "VolumeMarkerObservation",
    "marker_namespace",
    "marker_within_volume",
    "observe_volume_marker",
]
