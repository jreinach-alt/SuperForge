#!/usr/bin/env python3
"""Record the README presentation GIFs — one choreographed clip per rail.

Usage:  python3 tools/record_pres_gif.py <rail> [<rail>...] [--all]
        python3 tools/record_pres_gif.py mode7_flight --proofs /tmp/proofs

Options:
        --out DIR      where gif_<rail>.gif lands             (default docs/img)
        --proofs DIR   also drop <rail>_{a,b,c}.png — the GIF's OWN first /
                       middle / last frames, decoded back out of the written
                       file, which is the eyeball surface CLAUDE.md rule 3 asks
                       for on a rendered artifact

THIS IS A DISPATCHER, NOT A RECORDER. `tools/record_gallery_clip.py` is the
recorder and its docstring is the format contract: deterministic frame_step,
a capture every 3rd emulated frame, 50 ms/frame so ONE GIF SECOND IS ONE
GAMEPLAY SECOND, 256x239, one shared <=128-colour palette, loop forever,
under 2 MB, and driven at FULL gameplay speed because gentle showcase inputs
read as a frame-rate drop at 1:1 time. Everything here goes through it.

What lives here is the part that is per-rail: the CHOREOGRAPHY. Each
`tools/gif_scenarios/<rail>.py` is one rail's drive — what it holds, what it
waits for, and why those beats. They read the ROM's STATE rather than
counting frames to an event, because a fixed plan drifts against the ROM's
own tick and produces a plausible clip of the wrong thing (the friction log
2026-08-06; tools/record_m7x_clip.py is the worked example).

EVERY CLIP HERE IS ONE SHARED <=128-COLOUR PALETTE, the contract's clause,
unrelaxed. Recording the lead rail is what found that the clause was being
reached wrongly — the palette came from frame 0 alone and the quantiser
dithered by default, which on a rail whose CGRAM moves (mode7_flight's
day/night clock) scattered the last third of the clip into orange noise and
pushed the file to 2.60 MB. The fix is in the recorder
(record_gallery_clip.quantize_take): same clause, built over the whole take,
no dither, 1.21 MB. No rail here needs an escape hatch.
"""
import argparse
import hashlib
import importlib
import sys
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.record_gallery_clip import record_clip, DURATION_MS  # noqa: E402
from tools.gif_seam import seam  # noqa: E402

RAILS = ("mode7_flight", "m7_oshoot", "microzero", "split_v_fight",
         "mode7_explore", "meteor_event", "boss_saucer", "railshooter",
         "racer")


def _stats(path):
    """Raw captures, stored frames, and the static fraction — RAW, not stored.

    PIL merges identical consecutive captures into one stored frame with the
    durations summed, so counting motion on the FILE makes the number true by
    construction (a post-merge measurement can never see a static transition;
    the first reading of an early clip was "0% near-static" against an
    honest 36%). The raw capture count is recoverable from the per-frame
    durations, so recover it.
    """
    im = Image.open(path)
    caps = [max(1, f.info.get("duration", DURATION_MS) // DURATION_MS)
            for f in ImageSequence.Iterator(im)]
    raw, stored = sum(caps), len(caps)
    return raw, stored, (raw - stored) / max(1, raw - 1)


def _proofs(path, proof_dir, rail):
    """First / middle / last, decoded back OUT of the written GIF.

    Deliberately not the in-memory captures: the artifact that ships is the
    GIF, so what a human looks at is read back through the quantiser and the
    writer. A palette defect that only exists in the file is then visible in
    the proof instead of hidden by it. `middle` is the middle of PLAYBACK
    TIME, not of the stored-frame list, which the merge makes different.
    """
    proof_dir = Path(proof_dir)
    proof_dir.mkdir(parents=True, exist_ok=True)
    im = Image.open(path)
    caps = [max(1, f.info.get("duration", DURATION_MS) // DURATION_MS)
            for f in ImageSequence.Iterator(im)]
    cum, acc = [], 0
    for c in caps:
        acc += c
        cum.append(acc)
    half = acc // 2
    mid = next(i for i, c in enumerate(cum) if c >= half)
    out = []
    for tag, idx in zip("abc", (0, mid, len(caps) - 1)):
        im.seek(idx)
        p = proof_dir / f"{rail}_{tag}.png"
        im.convert("RGB").save(p)
        out.append((idx, p))
    return out


def record(rail, out_dir, proof_dir):
    mod = importlib.import_module(f"tools.gif_scenarios.{rail}")
    rom = ROOT / "build" / f"{mod.ROM}.sfc"
    if not rom.exists():
        raise SystemExit(f"record_pres_gif: {rom} is not built — run `make {rail}`")
    rom_md5 = hashlib.md5(rom.read_bytes()).hexdigest()
    out = Path(out_dir) / f"gif_{rail}.gif"
    out.parent.mkdir(parents=True, exist_ok=True)

    kw = dict(drive=mod.make_drive(), captures=mod.CAPTURES,
              settle_frames=getattr(mod, "SETTLE", 60))
    if getattr(mod, "WINDOW", None):
        kw["window"] = mod.WINDOW
        if getattr(mod, "WINDOW_START", None) is not None:
            kw["window_start"] = mod.WINDOW_START
    if getattr(mod, "HOLD2", None):
        kw["hold2"] = mod.HOLD2
    path, n, size = record_clip(str(rom), out, **kw)
    raw, stored, static = _stats(path)
    print(f"  {rail}: rom {rom.name} md5 {rom_md5}")
    print(f"  {rail}: {raw} raw captures -> {stored} stored, "
          f"{100 * static:.0f}% fully-static raw transitions, "
          f"gif md5 {hashlib.md5(path.read_bytes()).hexdigest()}")
    # THE LOOP SEAM, MEASURED ON THE WRITTEN FILE. The clip loops forever, so
    # the join from its last frame back to its first is the one cut a viewer
    # actually sees, and it is the one no other number here covers. Reported
    # every time rather than checked once: a choreography edit that reopens the
    # seam is otherwise invisible until someone watches the gallery.
    mad, pct, lum0, lum1, _ = seam(path)
    print(f"  {rail}: loop seam mad {mad:.2f}/255, {pct:.1f}% of pixels "
          f"past 16 — ends at luma {lum0:.1f} (first) / {lum1:.1f} (last)")
    if proof_dir:
        for idx, p in _proofs(path, proof_dir, rail):
            print(f"  {rail}: proof stored-frame {idx:3d} -> {p}")
    return size


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rails", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
    ap.add_argument("--proofs", default=None)
    a = ap.parse_args()
    rails = list(RAILS) if a.all else a.rails
    if not rails:
        ap.error("name a rail, or pass --all")
    total = sum(record(r, a.out, a.proofs) for r in rails)
    if len(rails) > 1:
        print(f"\n{len(rails)} GIFs, {total / 1e6:.2f} MB total")


if __name__ == "__main__":
    main()
