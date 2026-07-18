"""Done-conditions for the platformer flagship — the full game, start to
soft restart.

The win test drives the COMPLETE 6-coin route with the closed-loop bot
(tests/_platformer_bot.py): both one-way platforms, the stepping stone, the
seam ledge (ghost stomped mid-route, after observing it patrol ACROSS the
page seam), both pits crossed, the WIN scene rendered — then the soft
restart: START -> title -> START -> a FRESH game (coins respawned, ghosts
revived, state reset) with no power cycle. Scene music switches are
asserted on the engine's TAD mirrors (the audio_test gate owns the
audible-WAV proof).
"""
import time
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
from tests import _platformer_bot as bot

ROOT = Path(__file__).resolve().parent.parent
WR = MemoryType.SnesWorkRam

SCENE, LIVES, COINS = 0x1804, 0x1800, 0x1802
E2X = 0x46
TAD_SONG = 0x016C
SONG_TITLE, SONG_GAME = 3, 2          # Song::chords / Song::ode_to_joy


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    # v3 save/continue persists battery SRAM to platformer.srm ACROSS test
    # modules (the emulator is process-global; the .srm flushes at ROM
    # unload). This module's documented baseline is a VIRGIN cart — no
    # save, no CONTINUE line on the title. bot.virgin_srm flushes-then-
    # deletes any stale .srm (see its docstring for why a bare unlink is
    # not enough). Within the module, test_pits_to_game_over banks a coin
    # and writes a save — later boots HERE legitimately show the CONTINUE
    # line; no assertion in this module reads that title region.
    bot.virgin_srm(r, ROOT / "build" / "text_test.sfc")
    yield r
    r.stop()


def _rom():
    p = ROOT / "build" / "platformer.sfc"
    assert p.exists(), f"{p} not built — run `make platformer` first"
    return str(p)


def _shot(r, path="/tmp/_plat.png"):
    r.take_screenshot(path)
    return Image.open(path).convert("RGB")


def _white_text_in(img, x0, y0, x1, y1):
    px = [img.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1, 2)]
    return any(p[0] > 200 and p[1] > 200 and p[2] > 200 for p in px)


def _start(r):
    r.set_input(0, start=True)
    r.run_frames(4)
    r.set_input(0)
    r.run_frames(20)


def test_title_renders_with_music(runner):
    runner.load_rom(_rom(), run_seconds=1.0)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    assert bot.st(runner)["sc"] == 0
    img = _shot(runner)
    assert _white_text_in(img, 64, 84, 200, 100), "title text not rendered"
    assert _white_text_in(img, 72, 116, 184, 132), "PRESS START not rendered"
    assert runner.read_bytes(WR, TAD_SONG, 1)[0] == SONG_TITLE, "title music not loaded"


def test_full_win_route_then_soft_restart(runner):
    runner.load_rom(_rom(), run_seconds=1.0)
    _start(runner)
    s = bot.st(runner)
    assert (s["sc"], s["lv"], s["co"]) == (1, 3, 0)
    assert runner.read_bytes(WR, TAD_SONG, 1)[0] == SONG_GAME, "game music not loaded"

    # seam crossing observed live before the bot engages the ledge ghost
    seen = set()
    for _ in range(30):
        x = runner.read_u16(WR, E2X)
        seen.add(x < 256)
        runner.run_frames(8)
        if len(seen) == 2:
            break
    assert len(seen) == 2, "ledge ghost never crossed the page seam"

    final = bot.win_route(runner, log=lambda *a: None)
    assert final["sc"] == 3, f"did not reach the WIN scene: {final}"
    assert final["co"] == 6
    assert final["e2"] == 0, "the ledge ghost was not stomped en route"
    runner.run_frames(45)            # v2: scene entry fades in from black
    img = _shot(runner)
    assert _white_text_in(img, 88, 100, 180, 116), "YOU WIN! not rendered"

    # soft restart: win -> title -> FRESH game (no power cycle)
    _start(runner)                                   # -> title
    assert bot.st(runner)["sc"] == 0
    assert runner.read_bytes(WR, TAD_SONG, 1)[0] == SONG_TITLE, "title music on return"
    _start(runner)                                   # -> new game
    s = bot.st(runner)
    assert (s["sc"], s["lv"], s["co"], s["e2"], s["px"]) == (1, 3, 0, 1, 24), \
        f"soft restart did not reset the game: {s}"
    # the level reloaded: coin A exists again and is collectable
    bot.walk_to(runner, 54)
    assert bot.st(runner)["co"] == 1, "coins did not respawn on restart"


def test_pits_to_game_over_freeze_and_recover(runner):
    runner.load_rom(_rom(), run_seconds=1.0)
    _start(runner)
    # hold right: spawn -> pit1 -> respawn, three times over (i-frames
    # don't gate pits), until the scene flips to GAME OVER
    runner.set_input(0, right=True)
    deadline = time.time() + 90
    while bot.st(runner)["sc"] == 1 and time.time() < deadline:
        runner.run_frames(10)
    runner.set_input(0)
    s = bot.st(runner)
    assert s["sc"] == 2 and s["lv"] == 0, f"pits never reached game over: {s}"
    runner.run_frames(45)            # v2: scene entry fades in from black
    img = _shot(runner)
    assert _white_text_in(img, 84, 100, 180, 116), "GAME OVER not rendered"
    # gameplay input is dead; START still works (back to the title)
    _start(runner)
    assert bot.st(runner)["sc"] == 0, "START on game over did not return to title"


def test_ghost_contact_costs_a_life(runner):
    runner.load_rom(_rom(), run_seconds=1.0)
    _start(runner)
    # stand still: ghost1's ground beat sweeps through the spawn area
    deadline = time.time() + 45
    while bot.st(runner)["lv"] == 3 and time.time() < deadline:
        runner.run_frames(10)
    s = bot.st(runner)
    assert s["lv"] == 2, f"ghost contact never registered: {s}"
    assert s["px"] == 24, "hurt did not respawn the player"
