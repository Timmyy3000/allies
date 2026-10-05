from math import ceil
from pathlib import Path

from PIL import Image


FRAME_SIZE = 64
COLUMNS = 16
IDENTITIES = ("boxy", "ghosty", "rocky", "rolly")

app_root = Path(__file__).resolve().parents[1]
source_root = app_root / "assets" / "allies" / "gifs" / "optimized"
output_root = app_root / "assets" / "allies" / "sprites"
output_root.mkdir(parents=True, exist_ok=True)

for identity in IDENTITIES:
    source_path = source_root / f"ally-idle-{identity}.gif"
    output_path = output_root / f"ally-idle-{identity}.png"

    with Image.open(source_path) as source:
        frame_count = source.n_frames
        rows = ceil(frame_count / COLUMNS)
        sheet = Image.new("RGBA", (COLUMNS * FRAME_SIZE, rows * FRAME_SIZE))

        for frame_index in range(frame_count):
            source.seek(frame_index)
            frame = source.convert("RGBA").resize(
                (FRAME_SIZE, FRAME_SIZE), Image.Resampling.LANCZOS
            )
            x = (frame_index % COLUMNS) * FRAME_SIZE
            y = (frame_index // COLUMNS) * FRAME_SIZE
            sheet.alpha_composite(frame, (x, y))

        sheet.save(output_path, optimize=True)
