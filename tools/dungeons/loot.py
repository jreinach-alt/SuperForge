"""loot.py — reference model of SuperForge Dungeons' gear roller.

Spec: docs/dungeons/04_gear_and_loot.md. ORACLE for the ROM's roller: for a
given stream state, floor and slot the ROM must emit the same 4-byte record
and consume the same number of draws.

The record stores the ROLL, never derived stats (stats come from ROM tables
at use time), so an item is exactly 4 bytes:

    byte 0  base id                (gear.toml [[base]].id; slot is implied)
    byte 1  power                  (0..255)
    byte 2  enchant 1: id<<3 | tier (id 0 = empty slot; tier 1..3, 0 = locked)
    byte 3  enchant 2: id<<3 | tier

Rarity is not stored, it is recoverable: unique iff the base is a unique;
rare iff enchant 2 is non-empty on a non-unique; common otherwise.
"""
from __future__ import annotations

import os
import sys
import tomllib

sys.path.insert(0, os.path.dirname(__file__))
import prng  # noqa: E402

HERE = os.path.dirname(__file__)
SLOTS = ("melee", "ranged", "armor", "artifact")


def load(path: str | None = None) -> dict:
    with open(path or os.path.join(HERE, "data", "gear.toml"), "rb") as f:
        d = tomllib.load(f)
    d["by_id"] = {b["id"]: b for b in d["base"]}
    d["ench_by_name"] = {e["name"]: e for e in d["enchant"]}
    for e in d["enchant"]:
        if not 1 <= e["id"] <= 31:
            raise ValueError(f"enchant {e['name']}: id must fit 5 bits")
    return d


def threat(gear: dict, floor: int) -> int:
    return min(1 + floor * gear["power"]["threat_per_floor"], 250)


def rarity_of(gear: dict, rec: bytes) -> str:
    if "of" in gear["by_id"][rec[0]]:
        return "unique"
    return "rare" if rec[3] else "common"


class Roller:
    """Per-player pity counters live here; the ROM keeps one byte per player."""

    def __init__(self, gear: dict):
        self.g = gear
        self.pity = [0, 0]

    def _ench_pool(self, slot: str, exclude: set) -> list:
        return [e for e in self.g["enchant"] if slot in e["slots"] and e["id"] not in exclude]

    def roll(self, st: prng.Stream, floor: int, player: int, slot: str | None = None,
             min_rarity: str = "common") -> bytes:
        g = self.g
        # draw 1: slot (skipped when the caller forces one)
        if slot is None:
            sw = g["drops"]["slot_weights"]
            slot = SLOTS[st.weighted([sw[s] for s in SLOTS])]
        # draw 2: rarity, with per-player pity and the floor gate
        rw = g["rarity"]["weights"]
        rar = ("common", "rare", "unique")[st.weighted([rw["common"], rw["rare"], rw["unique"]])]
        if rar == "unique" and floor < g["rarity"]["unique_min_floor"]:
            rar = "rare"
        if rar == "common" and (self.pity[player] >= g["rarity"]["pity_rare_after"] or min_rarity != "common"):
            rar = "rare"
        uniques = [b for b in g["base"] if b["slot"] == slot and "of" in b]
        if rar == "unique" and not uniques:      # artifacts have no uniques
            rar = "rare"
        self.pity[player] = self.pity[player] + 1 if rar == "common" else 0
        # draw 3: base
        if rar == "unique":
            base = uniques[st.below(len(uniques))]
        else:
            plain = [b for b in g["base"] if b["slot"] == slot and "of" not in b]
            base = plain[st.below(len(plain))]
        # draw 4: power
        p = g["power"]
        off = p["offset_base"] + st.weighted(p["offset_weights"])
        off += {"common": 0, "rare": p["rare_bonus"], "unique": p["unique_bonus"]}[rar]
        power = max(1, min(255, threat(g, floor) + off))
        e1 = e2 = 0
        if slot != "artifact":
            if rar == "unique":
                sig = g["ench_by_name"][base["signature"]]
                e1 = sig["id"] << 3 | 2
                pool = self._ench_pool(slot, {sig["id"]})
                e2 = pool[st.below(len(pool))]["id"] << 3 | 1      # draw 5
            else:
                pool = self._ench_pool(slot, set())
                first = pool[st.below(len(pool))]                   # draw 5
                e1 = first["id"] << 3 | 1
                if rar == "rare":
                    pool = self._ench_pool(slot, {first["id"]})
                    e2 = pool[st.below(len(pool))]["id"] << 3 | 1   # draw 6
        return bytes([base["id"], power, e1, e2])


def describe(gear: dict, rec: bytes) -> str:
    b = gear["by_id"][rec[0]]
    ids = {e["id"]: e["name"] for e in gear["enchant"]}
    ench = [f"{ids[x >> 3]} {'I' * (x & 7)}" for x in rec[2:] if x]
    return f"{b['name']:<14} P{rec[1]:<3} {rarity_of(gear, rec):<7} {', '.join(ench)}"


if __name__ == "__main__":
    g = load()
    r = Roller(g)
    st = prng.Stream(prng.level_seed(0x1234, 9))
    for f in (0, 3, 6, 9):
        for i in range(4):
            print(f"floor {f} p{i & 1}:", describe(g, r.roll(st, f, i & 1)))
