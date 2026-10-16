"""The showcase clips are pinned to the ROMs that produced them.

WHY THIS FILE EXISTS, as an incident rather than a principle:
`gif_mode7_explore.gif` and `gif_meteor_event.gif` sat on the README for
seven weeks showing defects that had already been fixed -- an avatar standing
beside the crossroads she was standing on, a town whose exit tile rendered
below the visible picture, and an ALL-BLACK FRAME at index 93 which was the
mode-swap flicker, looping. Every gate was green that entire time, because no
gate looked at a GIF. The one artifact a visitor sees before any code had no
ratchet on it at all. Auditing for that on 2026-10-16 then found two MORE
stale clips nobody had noticed, `mode7_flight` (the README's hero image) and
`m7_oshoot`.

WHAT IS CHECKED, AND WHY IT IS THE CHEAP QUESTION. `docs/img/gif_provenance.json`
records, per clip, the ROM it was recorded from and that ROM's md5. These
tests assert the recorded digest still matches the ROM that builds today.
That is deliberately NOT the sharp question -- the sharp question is whether
the PICTURE moved, and the way to ask it is to re-record and compare. That
gate was measured and rejected on 2026-10-16: `record_gallery_clip` drives
`MesenRunner`, which boots under RamState::Random with nothing seeding it
("mt19937 seeded from std::random_device ONCE PER PROCESS; varies every run"
-- its own note). Eleven of fifteen clips re-record byte-identical; `racer`
and `railshooter` do not, and not by a frame or two: same frame COUNT, but
109 of 261 and 253 of 257 frames differ between two runs. A re-record gate
would therefore carry a standing red, and a gate that cries wolf gets
ignored -- which is how the clips rotted in the first place.

THE COST OF THE CHEAP QUESTION, STATED SO NOBODY IS SURPRISED BY IT: a change
to any shared feature moves every rail's ROM without necessarily moving a
pixel, and this will report all fifteen. Each such report is TRUE -- the ROM
behind the clip did change -- and clearing one is 9 seconds of
`python3 tools/record_pres_gif.py <rail>`. Over-reporting and never lying
beats precise and flaky; it is the same trade `toy-bad` and `rom-unbacked`
already make.

The provenance file is written BY the recorder, never by hand, and only when
it writes the shipped clip -- a `--out /tmp/...` comparison run leaves it
alone, so a throwaway recording cannot bless whatever ROM happens to be
built.
"""
import hashlib
import json
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
IMG = SUPERFORGE / "docs" / "img"
PROVENANCE = IMG / "gif_provenance.json"


def _book():
    return json.loads(PROVENANCE.read_text())


def _shipped():
    return sorted(p.name[4:-4] for p in IMG.glob("gif_*.gif"))


def test_every_shipped_clip_has_provenance_and_vice_versa():
    """The join, both ways -- this is the half that cannot be skipped.

    A new clip that nobody recorded provenance for is a clip outside the
    ratchet, which is the state the whole README was in until today. An entry
    whose clip was deleted is a stale promise. Neither needs a ROM on disk to
    detect, so this runs in any clone."""
    book, shipped = _book(), _shipped()
    assert sorted(book) == shipped, (
        f"provenance and docs/img disagree.\n"
        f"  clips with no entry: {sorted(set(shipped) - set(book))}\n"
        f"  entries with no clip: {sorted(set(book) - set(shipped))}\n"
        f"Record the clip (`python3 tools/record_pres_gif.py <rail>`), which "
        f"writes the entry, or delete the stale entry.")


@pytest.mark.parametrize("rail", sorted(_book()) if PROVENANCE.exists() else [])
def test_the_clip_on_disk_is_the_one_that_was_recorded(rail):
    """The GIF has not been edited, re-compressed or swapped since recording.

    Cheap and absolute: no emulator, no build, just the bytes. It catches the
    hand-optimised GIF that nothing else would notice."""
    entry = _book()[rail]
    actual = hashlib.md5((IMG / f"gif_{rail}.gif").read_bytes()).hexdigest()
    assert actual == entry["gif_md5"], (
        f"gif_{rail}.gif is not the file the recorder wrote "
        f"(recorded {entry['gif_md5']}, on disk {actual}). Re-record it "
        f"rather than editing a clip in place.")


@pytest.mark.parametrize("rail", sorted(_book()) if PROVENANCE.exists() else [])
def test_the_clip_was_recorded_from_the_rom_that_builds_today(rail):
    """THE RATCHET. The clip's ROM and the tree's ROM are the same bytes.

    Skips when the ROM is not built, because a plain `pytest tests/` in a
    fresh clone has built nothing -- but the landing gate builds every rail
    before the suite runs, so there it is the gate it is meant to be."""
    entry = _book()[rail]
    rom = SUPERFORGE / "build" / entry["rom"]
    if not rom.exists():
        pytest.skip(f"{rom.name} is not built — run `make` for its rail; "
                    f"the landing gate builds every rail before the suite")
    actual = hashlib.md5(rom.read_bytes()).hexdigest()
    assert actual == entry["rom_md5"], (
        f"gif_{rail}.gif was recorded from {entry['rom']} md5 "
        f"{entry['rom_md5']}, but that ROM now builds to {actual}. The clip "
        f"may be showing behaviour the engine no longer has — which is "
        f"exactly how two of these ended up advertising fixed defects for "
        f"seven weeks. Re-cut it:\n"
        f"    python3 tools/record_pres_gif.py {rail}\n"
        f"and commit the GIF with the provenance entry it rewrites.")
