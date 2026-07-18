"""film_strip.py — stitch N captured frames into ONE labeled montage PNG.

The reusable generalization of the established side-by-side PIL-paste montage
primitive (tools/bless_golden.py::_side_by_side, which composites a before|after
pair) to an arbitrary N-frame grid. The platformer_stream rail captured an owner-
validation film strip with the ad-hoc 2-frame paste (docs/dx_paper_cuts.md
"Mode-1 streaming S2b-M2b"); this is the committed, reusable form.

Pair it with MesenRunner.capture_frames (which grabs frames at given offsets):

    from infrastructure.test_harness.mesen_runner import MesenRunner
    from infrastructure.test_harness.film_strip import film_strip

    r = MesenRunner()
    paths = r.capture_frames("build/game.sfc", [0, 60, 120, 180], "/tmp/frames")
    film_strip(paths, "build/game_filmstrip.png",
               labels=["boot", "1s", "2s", "3s"], cols=4)

No host-project coupling — depends only on Pillow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Union

_PathLike = Union[str, Path]


def film_strip(
    frame_paths: Sequence[_PathLike],
    dest: _PathLike,
    *,
    labels: Optional[Sequence[str]] = None,
    cols: Optional[int] = None,
    gap: int = 4,
    bg: tuple = (32, 32, 32),
    label_h: int = 12,
    label_color: tuple = (235, 235, 235),
) -> str:
    """Paste-grid N captured frames into one montage PNG and return the dest path.

    Args:
        frame_paths: ordered frame image paths (e.g. from capture_frames).
        dest: output PNG path.
        labels: optional per-frame captions (drawn in a strip above each frame).
                Shorter/longer than frame_paths is tolerated (missing -> blank).
        cols: grid columns. Default: a single horizontal strip (cols == N) when
              N <= 6, else a roughly-square grid (ceil(sqrt(N))).
        gap: pixels between cells.
        bg: montage background RGB.
        label_h: height of the label strip above each frame (0 -> no labels).
        label_color: label text RGB.

    Raises:
        ValueError: if frame_paths is empty.
    """
    from PIL import Image, ImageDraw

    paths = [Path(p) for p in frame_paths]
    if not paths:
        raise ValueError("film_strip: frame_paths is empty")

    n = len(paths)
    if cols is None:
        if n <= 6:
            cols = n
        else:
            import math
            cols = math.ceil(math.sqrt(n))
    cols = max(1, int(cols))
    rows = (n + cols - 1) // cols

    imgs = [Image.open(p).convert("RGB") for p in paths]
    cw = max(im.width for im in imgs)
    ch = max(im.height for im in imgs)
    has_labels = bool(labels) and label_h > 0
    cell_h = ch + (label_h if has_labels else 0)

    total_w = cols * cw + (cols + 1) * gap
    total_h = rows * cell_h + (rows + 1) * gap
    comp = Image.new("RGB", (total_w, total_h), bg)
    draw = ImageDraw.Draw(comp) if has_labels else None

    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        x = gap + c * (cw + gap)
        y = gap + r * (cell_h + gap)
        if has_labels:
            cap = labels[i] if labels and i < len(labels) else ""
            if cap and draw is not None:
                draw.text((x + 1, y + 1), str(cap), fill=label_color)
            y += label_h
        comp.paste(im, (x, y))

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    comp.save(dest)
    return str(dest)
