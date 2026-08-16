#!/usr/bin/env python3
"""Record a gallery GIF from a built ROM — the standard clip format.

Every clip under docs/img/ follows one contract:

  - drive the exact committed .sfc DETERMINISTICALLY with frame_step
    (never a wall-clock free-run), so a recording is reproducible
  - capture every 3rd emulated frame -> 20 Hz sampling of 60 fps play
  - assemble at duration=50 ms/frame -> 20 fps playback, so ONE GIF
    SECOND == ONE GAMEPLAY SECOND (no slow motion, no duplicated frames)
  - 256x239 frames, one shared <=128-color palette, loop forever, < 2 MB
  - drive at full gameplay speed: gentle "showcase" inputs read as a
    frame-rate drop at 1:1 time (the split_h lesson, 2026-07-19)

Library use (choreographed clips — fire patterns, kills, scene arcs):

    from tools.record_gallery_clip import record_clip, hold, STEP

    # hold pad-1 left for the take, keep the densest 56 captures
    record_clip("build/x.sfc", "clip.gif",
                drive=hold(left=True), captures=100, window=56)

    # custom drive: called once per capture, must advance STEP frames —
    # take_screenshot pays the rest of EVERY (see SHOT_FRAMES below)
    def drive(runner, i):
        runner.frame_step(STEP, b=(i % 20 == 0))   # tap B once a second
    record_clip("build/shmup.sfc", "clip.gif", drive=drive, captures=160)

...AND A DRIVE READS THE ROM'S STATE, NOT A FRAME SCHEDULE. Both examples
above are schedule-shaped and both are the easy case. A clip that has to
REACH something — a tile, a scene change, a boss phase — cannot count frames
to it: an atomic slide finishes after the button changes, and the ROM's own
tick drifts against any fixed plan. Two attempts produced a plausible
GIF that never entered the town that way. Drive off state the way the tests
do — walk until the camera reports the tile, idle until the wipe reports idle.
Worked example: tools/record_m7x_clip.py.

CLI (held-button clips):

    python tools/record_gallery_clip.py build/x.sfc clip.gif \\
        --captures 100 --window 56 --hold left --hold2 right
"""
import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vendor.mesen_runner import MesenRunner  # noqa: E402

EVERY = 3            # capture every 3rd emulated frame (60 fps -> 20 Hz)
DURATION_MS = 50     # 20 fps playback == real time when EVERY == 3
SIZE_LIMIT = 2 * 1024 * 1024
PALETTE_COLORS = 128

# THE SHOT COSTS A FRAME ON THIS HARNESS, AND THE 1:1 GUARANTEE IS THE
# DIFFERENCE. A runner that captured the composite as it stood would put
# exactly STEP frames between captures, so 50 ms of
# playback holds 3 frames of gameplay — 1:1, exactly as the contract says.
# This runner absorbs the presentation lag instead (mesen_runner.py's
# take_screenshot: `if self._frame_stepping: self._advance_emulated(1)`), so
# the vendored arithmetic silently became 3 driven + 1 for the shot = FOUR
# emulated frames per capture, and every clip recorded through it plays 4/3 =
# 1.33x fast. MEASURED on build/mode7_flight.sfc, 2026-08-16: 20 captures
# consumed 80 emulated frames, i.e. 1.000 s of GIF for 1.333 s of gameplay.
#
# The contract is right; the arithmetic under it drifted on vendoring. So the
# drive advances STEP and the shot pays the rest, a capture is EVERY frames
# again, and `record_clip` now MEASURES that rather than trusting it — the
# same treatment the size budget already gets.
SHOT_FRAMES = 1      # what runner.take_screenshot costs while frame-stepping
STEP = EVERY - SHOT_FRAMES      # ...so this is what a drive must advance


def hold(**buttons):
    """A drive that holds the given pad-1 buttons every frame of the take."""
    def drive(runner, i):
        runner.frame_step(STEP, **buttons)
    return drive


def quantize_take(frames):
    """The contract's ONE SHARED <=128-COLOUR PALETTE — over the WHOLE take.

    The clause is right and is unchanged; how it was reached was not, in two
    ways that compound, and both show up worst on exactly the clips a gallery
    wants most (anything whose CGRAM moves — a day/night clock, a fade, a
    palette cycle, a colour-math wash):

      * the palette was median-cut from FRAME 0 ALONE and then imposed on the
        rest of the take, so any colour the clip acquires later has no entry
        to land on;
      * `Image.quantize(palette=...)` DITHERS BY DEFAULT (Floyd-Steinberg), so
        those misses did not merely flatten, they scattered — and dither noise
        is close to incompressible, which is how the quality failure also
        became a SIZE failure.

    MEASURED on build/mode7_flight.sfc, 150 captures, 2026-08-16 (the take
    holds 1,336 distinct RGB values because HDMA rewrites CGRAM per scanline
    and the day/night clock walks it under the clip):

        frame-0 palette + FS dither   2.60 MB   mean |RGB err| 10.66/255
        take palette,  no dither      1.21 MB   mean |RGB err|  2.50/255
        take palette 256, no dither   1.28 MB   mean |RGB err|  1.07/255
        per-frame local, exact        1.38 MB   mean |RGB err|  0.00/255

    So: one shared palette, 128 colours, built from every frame, no dither.
    Inside the budget it used to blow, four times closer to the picture the
    emulator drew, and still the format's own clause. A rail whose CGRAM
    never moves is unaffected — its take palette IS its frame-0 palette.
    """
    w, h = frames[0].size
    strip = Image.new("RGB", (w, h * len(frames)))
    for i, f in enumerate(frames):
        strip.paste(f, (0, i * h))
    base = strip.quantize(colors=PALETTE_COLORS)
    return [f.quantize(palette=base, dither=Image.Dither.NONE) for f in frames]


def _motion(a, b):
    """Changed-sample count between two frames (stride-4 grid)."""
    w, h = a.size
    pa, pb = a.load(), b.load()
    return sum(1 for y in range(0, h, 4) for x in range(0, w, 4)
               if pa[x, y] != pb[x, y])


def densest_window(frames, length):
    """Start index of the contiguous `length` captures with the most motion."""
    if length >= len(frames):
        return 0
    step = [_motion(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    best_s, best_v = 0, -1
    run = sum(step[:length - 1])
    for s in range(len(frames) - length + 1):
        if s:
            run += step[s + length - 2] - step[s - 1]
        if run > best_v:
            best_s, best_v = s, run
    return best_s


def record_clip(rom, out_path, drive=None, captures=160, window=None,
                window_start=None, settle_frames=60, hold2=None, runner=None):
    """Record `captures` samples (EVERY frames apart) from `rom` into a gif.

    `drive(runner, i)` is called once per capture and must advance STEP
    emulated frames — take_screenshot pays the remaining SHOT_FRAMES, so a
    capture is EVERY frames of the ROM's time and playback is 1:1 (default:
    idle hold()). `hold2` is a dict of pad-2 buttons held for the whole take
    (set_input persists across steps). Returns (path, n_frames, size_bytes);
    asserts the size budget AND the real-time guarantee.
    """
    drive = drive or hold()
    own = runner is None
    if own:
        runner = MesenRunner()
    try:
        # EMULATED frames, so the clip starts at the same instant of the
        # ROM on every host — a gallery clip is a picture.
        runner.boot_rom(str(rom), frames=settle_frames)
        if hold2:
            runner.set_input(1, **hold2)
        frames = []
        with runner.frame_stepping():
            with tempfile.TemporaryDirectory() as td:
                shot = str(Path(td) / "cap.png")
                first = runner.ppu_frame_count()
                for i in range(captures):
                    drive(runner, i)
                    runner.take_screenshot(shot)
                    frames.append(Image.open(shot).convert("RGB").copy())
                consumed = runner.ppu_frame_count() - first
    finally:
        if own:
            runner.stop()

    # THE REAL-TIME GUARANTEE, MEASURED. `captures * DURATION_MS` of playback
    # is only `captures * EVERY` frames of gameplay if the drive advanced STEP
    # every time; a drive that advances the wrong count produces a clip that
    # looks fine and is silently in slow motion or sped up, which is the one
    # thing this format promises it is not. So the PPU's own counter says.
    want = captures * EVERY
    assert consumed == want, (
        f"the take consumed {consumed} emulated frames, not {want} "
        f"({captures} captures x {EVERY}): playback would be "
        f"{consumed / want:.3f}x gameplay speed, not 1:1. A drive advances "
        f"STEP ({STEP}) frames per call — take_screenshot pays the other "
        f"{SHOT_FRAMES}.")

    if window:
        # PIN THE START, OR LET THE METRIC PICK IT — and the pin exists because
        # the metric is not always reproducible. densest_window takes an ARGMAX,
        # and a take with a still stretch has a TIE PLATEAU: measured on
        # meteor_event, starts 24..40 all score exactly 28881, because the first
        # 24 captures are pixel-identical and contribute nothing either way. So
        # ONE changed sample anywhere moves the whole window and rewrites the
        # file. And samples do change: this runner boots with RamState::Random,
        # which its own block comment calls "mt19937 seeded from std::random_
        # device ONCE PER PROCESS; varies every run" — unlike Machine, nothing
        # here seeds it. Measured over 14 recordings of meteor_event: the
        # windowed clip produced 3 distinct md5s (12/1/1), while the SAME take
        # unwindowed produced one md5 12 times out of 12.
        #
        # So a windowed clip that must be reproducible names its start, and gets
        # it by running densest_window once and pinning the answer.
        s = densest_window(frames, window) if window_start is None else window_start
        frames = frames[s:s + window]
        print(f"  window: {window} of {captures} captures from {s} "
              f"({'pinned' if window_start is not None else 'densest'})")

    quantized = quantize_take(frames)
    out_path = Path(out_path)
    # NOTE: PIL merges identical consecutive frames into one stored frame
    # with the durations summed — total playback time stays exactly
    # len(frames) * DURATION_MS (real time), while the file shrinks.
    quantized[0].save(out_path, save_all=True, append_images=quantized[1:],
                      duration=DURATION_MS, loop=0, optimize=True)
    size = out_path.stat().st_size
    assert size < SIZE_LIMIT, f"{out_path} is {size} B (budget {SIZE_LIMIT})"
    stored = Image.open(out_path).n_frames
    print(f"{out_path}: {len(frames)} captures -> {stored} stored frames "
          f"({len(frames) * DURATION_MS / 1000:.1f} s real time), {size} B "
          f"[{consumed} emulated frames driven, 1:1 verified]")
    return out_path, len(frames), size


def _buttons(names):
    return {n: True for n in names} if names else None


def main():
    ap = argparse.ArgumentParser(
        description="Record a gallery GIF from a built ROM (standard format).")
    ap.add_argument("rom")
    ap.add_argument("out")
    ap.add_argument("--captures", type=int, default=160)
    ap.add_argument("--window", type=int, default=None,
                    help="keep only the densest N captures (motion metric)")
    ap.add_argument("--settle", type=int, default=60,
                    help="EMULATED frames to boot before recording starts")
    ap.add_argument("--hold", nargs="*", default=None,
                    help="pad-1 buttons held every frame (e.g. left b)")
    ap.add_argument("--hold2", nargs="*", default=None,
                    help="pad-2 buttons held for the whole take")
    a = ap.parse_args()
    drive = hold(**_buttons(a.hold)) if a.hold else None
    record_clip(a.rom, a.out, drive=drive, captures=a.captures,
                window=a.window, settle_frames=a.settle,
                hold2=_buttons(a.hold2))


if __name__ == "__main__":
    main()
