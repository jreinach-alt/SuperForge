#!/usr/bin/env python3
"""proof_platformer.py — the rendered proof for.

Renders four panels from the BUILT binary (title · gameplay with the two
parallax bands separated · GAME OVER · YOU WIN) into one sheet, plus a second
sheet showing the same scene at two camera positions so the band separation is
legible side by side rather than asserted.

Everything is frame-stepped through tests/plf_drive.py, so the panels are the
same on every run — which is what makes a proof rendered from a binary with a
recorded md5 mean anything.

Usage: python3 tools/proof_platformer.py [outdir]
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "tests"))
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from PIL import Image, ImageDraw  # noqa: E402

from mesen_runner import MesenRunner  # noqa: E402
import plf_drive as D  # noqa: E402

PAD, LABEL_H = 8, 14


def sheet(panels, path, cols=2):
    """Label each panel and tile them, so the proof says what it shows."""
    w, h = panels[0][1].size
    rows = (len(panels) + cols - 1) // cols
    out = Image.new("RGB",
                    (cols * w + (cols + 1) * PAD,
                     rows * (h + LABEL_H) + (rows + 1) * PAD),
                    (18, 18, 22))
    d = ImageDraw.Draw(out)
    for i, (label, im) in enumerate(panels):
        cx, cy = i % cols, i // cols
        x = PAD + cx * (w + PAD)
        y = PAD + cy * (h + LABEL_H + PAD)
        d.text((x, y + 2), label, fill=(210, 210, 220))
        out.paste(im, (x, y + LABEL_H))
    out.save(path)
    print(f"  -> {path}")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else SUPERFORGE / "docs" / "img")
    out.mkdir(parents=True, exist_ok=True)
    r = MesenRunner()

    def grab(name):
        p = out / f"_tmp_{name}.png"
        r.take_screenshot(str(p))
        im = Image.open(p).convert("RGB")
        p.unlink()
        return im

    # --- the title, on a cart with no continue to offer --------------------
    D.to_title(r)
    D.clear_save(r)
    D.to_title(r)
    D.settle(r)
    title = grab("title")

    # --- gameplay, at a camera where the two bands are half a period apart --
    D.enter_play(r)
    D.wait_grace(r)
    cam0 = grab("cam0")
    D.jump_arc(r, 168, hold_frames=30)
    D.walk_to(r, 256)
    r.frame_step(2)
    assert D.u16(r, D.CAM) == 128, "the drive did not park the camera at 128"
    cam128 = grab("cam128")

    # --- an ending: lose the run ------------------------------------------
    for _ in range(D.LIVES):
        if D.scene_now(r)[0] != D.SCENE_PLAY:
            break
        D.die_into_the_pit(r)
    assert D.wait_scene(r, D.SCENE_OVER), "the run did not end"
    over = grab("over")

    # --- and the other one: play the level ---------------------------------
    D.press(r, start=True)
    assert D.wait_scene(r, D.SCENE_TITLE)
    D.enter_play(r)
    D.win_route(r)
    assert D.wait_scene(r, D.SCENE_WIN), "the win route did not reach the card"
    win = grab("win")
    r.debug_resume()
    r.stop()

    sheet([("title", title),
           ("gameplay — camera 128, clouds at 1/8 and hills at 3/8", cam128),
           ("GAME OVER (three pit falls)", over),
           ("YOU WIN (all six coins, closed-loop bot)", win)],
          out / "platformer_proof.png")
    sheet([("camera 0", cam0), ("camera 128", cam128)],
          out / "platformer_parallax.png")


if __name__ == "__main__":
    main()
