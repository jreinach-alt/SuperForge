"""Pure-Python checks on SuperForge Dungeons' REFERENCE MODELS (no ROM yet).

runtime: ~3 s — 1,000 generated floors with flood-fill validation.

These models (tools/dungeons/) are the oracles the future ROM tests compare
WRAM/VRAM against, so their own contract is pinned here: the PRNG's period and
golden values, the generator's reachability invariant and draw-count bound,
and the loot record's bit layout. Spec: docs/dungeons/.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "dungeons"))
import levelgen  # noqa: E402
import loot  # noqa: E402
import prng  # noqa: E402


def test_xorshift16_full_period():
    x, n = 1, 0
    while True:
        x = prng.step(x)
        n += 1
        if x == 1:
            break
    assert n == 0xFFFF


def test_xorshift16_golden_values():
    # Pinned by hand: from 1, x^=x<<7 -> $0081, x^=x>>9 -> $0081,
    # x^=x<<8 -> $8181. The ROM's PRNG test asserts this sequence out of WRAM.
    st = prng.Stream(1)
    assert [st.next16() for _ in range(4)] == [0x8181, 0x6021, 0xE999, 0x2E0B]


def test_level_seed_never_zero():
    assert all(prng.level_seed(s, f) for s in range(0, 0x10000, 97) for f in range(16))


def test_below_is_one_draw_and_in_range():
    st = prng.Stream(0xACE1)
    for n in (1, 2, 3, 7, 200, 256):
        before = st.draws
        assert 0 <= st.below(n) < n
        assert st.draws == before + 1


@pytest.fixture(scope="module")
def templates():
    return levelgen.load_templates()


def test_every_template_type_present(templates):
    assert {t.type for t in templates} == set(levelgen.TYPES)


@pytest.mark.parametrize("seed", range(1, 101))
def test_generated_floors_are_valid(templates, seed):
    for floor in range(0, 10):
        lv = levelgen.generate(seed, floor, templates)
        assert levelgen.validate(lv) == [], (seed, floor)
        assert len(lv.tiles) == 64 * 64
        assert lv.draws <= 96          # the ROM budget assumes a bounded stream use
        assert sum(1 for t, *_ in lv.spawns if t == levelgen.MARKERS["B"]) == 1


def test_generation_is_deterministic(templates):
    a = levelgen.generate(0xBEEF, 3, templates)
    b = levelgen.generate(0xBEEF, 3, templates)
    assert a.tiles == b.tiles and a.spawns == b.spawns and a.draws == b.draws


def test_loot_record_layout():
    g = loot.load()
    r = loot.Roller(g)
    st = prng.Stream(0x1234)
    for i in range(2000):
        rec = r.roll(st, floor=i % 12, player=i & 1)
        assert len(rec) == 4
        base = g["by_id"][rec[0]]
        for b in rec[2:]:
            if b:
                assert 1 <= (b & 7) <= 3
                ench = next(e for e in g["enchant"] if e["id"] == b >> 3)
                assert base["slot"] in ench["slots"]
        if base["slot"] == "artifact":
            assert rec[2] == rec[3] == 0
        assert not (rec[2] and rec[3] and rec[2] >> 3 == rec[3] >> 3), "duplicate enchant"


def test_weight_tables_sum_to_256():
    g = loot.load()
    assert sum(g["drops"]["slot_weights"].values()) == 256
    assert sum(g["power"]["offset_weights"]) == 256
    assert sum(g["rarity"]["weights"].values()) == 256


def test_template_lint_is_clean(templates):
    # Spec 03 §6. This lint caught start_cross walling off its own N door on
    # its first run — a defect 20,000 generated floors never exercised,
    # because the start cell's N side never gets a door in today's walk.
    assert levelgen.lint_templates(templates) == []


def test_template_lint_fires_on_a_blocked_door():
    t = levelgen.Template("plant", "normal", levelgen.N | levelgen.S, 1, False,
                          ["#" * 14] + ["......e......."] + ["." * 14] * 12)
    assert any("door N" in e for e in levelgen.lint_templates([t]))


def test_actions_agree_with_the_combat_spec():
    # actions.toml is read by BOTH the Blender script and the game; these are
    # the durations docs/dungeons/05 fixes. A retimed action must move both.
    import tomllib
    p = os.path.join(os.path.dirname(__file__), "..", "tools", "dungeons", "art", "actions.toml")
    with open(p, "rb") as f:
        act = tomllib.load(f)["action"]
    for name, a in act.items():
        assert len(a["hold"]) == a["frames"], name
        assert all(len(v) == a["frames"] for v in a["keys"].values()), name
    assert sum(act["roll"]["hold"]) == 8                  # 05 §1.3
    assert act["swing"]["hold"][:2] == [4, 4]             # 05 §1.1 wind-up, active
    streamed = sum(act[k]["frames"] for k in ("idle", "walk", "roll", "hurt", "downed"))
    assert streamed * 3 == 33                             # 07 §2 / 02 §1.2
