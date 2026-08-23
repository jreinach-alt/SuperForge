"""tools/rate_oracle.py — the per-frame drive hook.

WHAT IS UNDER TEST. The oracle drives every rail from a SECONDS-indexed pad
script, and the module header argues at length for why that is load-bearing.
`drive` is the alternative for a measurement that cannot be written as a list
because it has to READ the machine to decide: a callable invoked once per
frame as `drive(frame_index, machine)`, returning that frame's pad or None.

TWO PROPERTIES, AND THE SECOND IS THE ONE THAT MATTERS. That the resolver
picks the callback is cheap to check and proves nothing on its own — a hook
that is called and whose pad never reaches the console is exactly the
proxy-variable pass CLAUDE.md rule 2 forbids. So the second group boots a
real ROM and reads the OUTPUT the oracle itself measures on that rail
(`patrol`'s `US_PX`, the word the oracle's `player_x` observable reads, which
`pat_solid_box` commits only when the tentative box is clear) and requires
that it move ONLY across the frames the callback pressed on.

THE NON-VACUITY CONTROL IS THE SAME RUN'S SECOND HALF. The callback returns
None after frame `PRESSED`, and `US_PX` must then be pinned to the last
value. Without that half, "the input landed" is satisfied by a rail that
walks on its own.

LOCKSTEP-NATIVE, no wall clock: every wait is `Machine.advance(1)`, and the
boot lands on an absolute frame by construction.
"""
import json
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tools"))

import rate_oracle as RO             # noqa: E402
from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "patrol.sfc"
BOOT = 90                            # an absolute frame, well past the fade
PRESSED = 12                         # frames the callback holds RIGHT for
RELEASED = 12                        # ...and frames it presses nothing


# --- the resolver, with no machine in sight ---------------------------------

def test_a_rail_with_only_a_script_still_drives_by_seconds():
    """The default path is untouched: the pad is the last mark at or before
    the frame's own real-time instant, and the frame index is ignored."""
    pad_for = RO._driver({"script": [(0.0, {}), (0.5, {"right": True})]})
    assert pad_for(0, 0.25, None) is None          # `_script_at`'s empty pad
    assert pad_for(999, 0.75, None) == {"right": True}


def test_a_drive_callback_receives_the_frame_index_and_the_machine():
    seen, handle = [], object()
    pad_for = RO._driver({"drive": lambda f, m: seen.append((f, m)) or
                                                {"a": f % 2 == 0}})
    assert pad_for(0, 0.0, handle) == {"a": True}
    assert pad_for(1, 99.0, handle) == {"a": False}
    assert seen == [(0, handle), (1, handle)]


def test_a_drive_callback_may_return_none_for_no_input():
    assert RO._driver({"drive": lambda f, m: None})(0, 0.0, None) is None


@pytest.mark.parametrize("rail, why", [
    ({"script": [(0.0, {})], "drive": lambda f, m: None}, "both"),
    ({}, "neither"),
])
def test_declaring_both_or_neither_is_refused(rail, why):
    """Silently resolving either mistake produces a measurement that looks
    finished — a rail with neither drives no input at all and reads a rail
    standing still as a rail running slow."""
    with pytest.raises(SystemExit) as e:
        RO._driver(rail)
    assert why in str(e.value)


# --- the same hook, against a booted console --------------------------------

@pytest.fixture(scope="module")
def driven():
    """One boot, driven by a `drive` callback, everything sampled.

    Returns (calls, xs) where `calls` is what the callback was handed and
    `xs[i]` is `US_PX` after the i-th driven frame.
    """
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make patrol` first")
    jmap = json.loads(
        (SUPERFORGE / "build" / "pat" / "symbol_map.json").read_text())
    px = RO._sym(jmap, "US_PX", "play")["start"]

    calls = []

    def drive(frame, machine):
        calls.append((frame, machine))
        return {"right": True} if frame < PRESSED else None

    m = Machine(str(ROM))
    try:
        m.advance(BOOT)                          # an absolute frame, no input
        pad_for = RO._driver({"drive": drive})
        xs = []
        for frame in range(PRESSED + RELEASED):
            m.advance(1, pad1=pad_for(frame, 0.0, m))
            xs.append(int.from_bytes(
                m.read_bytes(MemoryType.SnesWorkRam, px, 2), "little"))
        yield calls, xs, m
    finally:
        m.close()


def test_the_callback_is_invoked_once_per_frame_in_order(driven):
    calls, xs, m = driven
    assert [f for f, _ in calls] == list(range(PRESSED + RELEASED))
    assert all(handle is m for _, handle in calls)


def test_the_callbacks_input_lands_on_the_console(driven):
    """The pressed half: `US_PX` — the word the oracle's own `player_x`
    observable reads — advances on every frame the callback pressed RIGHT
    on."""
    _, xs, _ = driven
    pressed = xs[:PRESSED]
    assert all(b > a for a, b in zip(pressed, pressed[1:])), pressed
    assert pressed[-1] > pressed[0]


def test_returning_none_presses_nothing(driven):
    """The control, from the same run: once the callback stops pressing the
    player is pinned. A pad the hook never delivered would leave the whole
    trace flat and pass the case above by accident; a pad it never RELEASED
    would leave it climbing and fail here."""
    _, xs, _ = driven
    released = xs[PRESSED:]
    assert released == [released[0]] * len(released), released
