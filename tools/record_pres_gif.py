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
import json
import sys
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.record_gallery_clip import record_clip, DURATION_MS  # noqa: E402
from tools.gif_seam import seam  # noqa: E402

# --all records the SHOWCASE. A scenario module that is not on this list is
# still a rail and still records — `record_pres_gif.py <name>` goes straight to
# it — it just does not ship a clip, so --all does not write one nothing cites.
# `mill_direct` is the first entry here that is NOT a rail: it is mill's own
# variant ROM, with one declaration different and no `game/` directory, so
# `rail_registered` does not see it and should not. It is on the list for the
# reason the list exists — a clip nothing refreshes goes stale in silence.
RAILS = ("mode7_flight", "m7_oshoot", "split_v_fight",
         "mode7_explore", "meteor_event", "boss_saucer", "railshooter",
         "racer", "split_h_2p_demo", "lakeside", "heathaze", "smelter",
         "mill", "mill_direct", "aurora")


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


PROVENANCE = ROOT / "docs" / "img" / "gif_provenance.json"


def _remember(rail, rom_name, rom_md5, gif_path, stored):
    """Record which ROM this clip came from, so a later build can disagree.

    THE CLIP IS THE ONE ARTIFACT A VISITOR SEES BEFORE ANY CODE, AND NOTHING
    WATCHED IT. `gif_mode7_explore.gif` and `gif_meteor_event.gif` sat on the
    README for seven weeks showing defects that had been fixed -- an avatar
    standing off the crossroads, a town exit below the visible picture, and an
    all-black frame which was the transition flicker, looping. Every gate was
    green throughout, because no gate looked. This file is what
    `tests/test_gif_provenance.py` reads to make that impossible twice.

    WHY A STORED ROM DIGEST AND NOT A RE-RECORD. Comparing a fresh recording
    against the committed one is the sharper question -- it asks whether the
    PICTURE moved rather than whether the ROM did -- and it is the wrong gate
    to build, because `record_gallery_clip` boots through `MesenRunner` under
    RamState::Random with nothing seeding it (its own note: "mt19937 seeded
    from std::random_device ONCE PER PROCESS; varies every run"). Measured
    here on 2026-10-16: ten of fifteen clips re-record byte-identical and four
    do not, so a re-record gate would carry a standing red that teaches people
    to ignore it. A digest comparison runs no emulator and cannot flake.

    The cost of the cheaper question is that it is CONSERVATIVE: an audio-only
    change moves every rail's ROM without moving a pixel, and this will report
    all of them. That is a true statement each time -- the ROM behind the clip
    changed -- and clearing it is 9 seconds of `record_pres_gif.py <rail>`.
    A gate that over-reports and never lies beats one that is precise and
    flaky, which is the same trade `toy-bad` and `rom-unbacked` already make.
    """
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    try:
        book = json.loads(PROVENANCE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        book = {}
    book[rail] = {
        "rom": rom_name,
        "rom_md5": rom_md5,
        "gif_md5": hashlib.md5(Path(gif_path).read_bytes()).hexdigest(),
        "stored_frames": stored,
    }
    PROVENANCE.write_text(
        json.dumps(book, indent=2, sort_keys=True) + "\n")
    return PROVENANCE


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
    # Only the SHIPPED clip gets remembered. A `--out /tmp/...` run is a
    # comparison or a spike, and must not rewrite the provenance of a file it
    # did not replace -- that would let a throwaway recording silently bless
    # whatever ROM happens to be built.
    if Path(out_dir).resolve() == (ROOT / "docs" / "img").resolve():
        book = _remember(rail, rom.name, rom_md5, path, stored)
        print(f"  {rail}: provenance -> {book.relative_to(ROOT)}")
    return size


def bless(rail, reason):
    """Re-pin a clip to today's ROM WITHOUT re-recording it.

    THE REMEDY FOR THE RATCHET'S CONSERVATISM, and the reason it is safe to
    have a conservative ratchet at all. `tests/test_gif_provenance.py` asks
    whether the ROM moved, not whether the picture did, so any change to a
    shared feature reports every clip. Re-cutting all fifteen to clear that
    costs megabytes of binary churn for clips whose pixels never moved -- git
    stores a whole new blob per GIF, so a 2 KB difference is a 400 KB commit.

    This writes the provenance entry from the clip ALREADY ON DISK and the ROM
    that builds now, and stores the REASON, which is required. It is the same
    shape as `# WALL-CLOCK: ok -- <reason>` and `# MAP: ok -- <reason>`: an
    override that a human signs. Rubber-stamping it is a regression, and the
    reason is what a reviewer reads.

    USE IT ONLY WHEN THE PICTURE IS KNOWN UNCHANGED -- which for a rail whose
    recording reproduces means re-recording to a scratch directory and getting
    the same bytes. For a rail whose recording does NOT reproduce (measured
    2026-10-16: `racer`, `railshooter` and others vary run to run under
    RamState::Random), there is no such check available, and the honest move
    is to re-cut rather than to bless.
    """
    mod = importlib.import_module(f"tools.gif_scenarios.{rail}")
    rom = ROOT / "build" / f"{mod.ROM}.sfc"
    if not rom.exists():
        raise SystemExit(f"record_pres_gif: {rom} is not built")
    gif = ROOT / "docs" / "img" / f"gif_{rail}.gif"
    if not gif.exists():
        raise SystemExit(f"record_pres_gif: {gif} does not exist — record it")
    stored = Image.open(gif).n_frames
    book = _remember(rail, rom.name,
                     hashlib.md5(rom.read_bytes()).hexdigest(), gif, stored)
    entry = json.loads(book.read_text())[rail]
    entry["blessed"] = reason
    whole = json.loads(book.read_text())
    whole[rail] = entry
    book.write_text(json.dumps(whole, indent=2, sort_keys=True) + "\n")
    print(f"  {rail}: blessed against {rom.name} "
          f"{entry['rom_md5'][:8]} — {reason}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rails", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "docs" / "img"))
    ap.add_argument("--proofs", default=None)
    ap.add_argument("--bless", metavar="REASON",
                    help="re-pin the named rails to today's ROM WITHOUT "
                         "re-recording, storing REASON. Only when the picture "
                         "is known unchanged — see bless().")
    a = ap.parse_args()
    rails = list(RAILS) if a.all else a.rails
    if not rails:
        ap.error("name a rail, or pass --all")
    if a.bless:
        if not a.bless.strip():
            ap.error("--bless needs a reason; a bare stamp is the regression")
        for r in rails:
            bless(r, a.bless.strip())
        return
    total = sum(record(r, a.out, a.proofs) for r in rails)
    if len(rails) > 1:
        print(f"\n{len(rails)} GIFs, {total / 1e6:.2f} MB total")


if __name__ == "__main__":
    main()
