#!/usr/bin/env python3
"""gen_col_flags.py — the world's collision flag table, DERIVED.

Emits (byte-identical on re-run, pure integer math):
  col_flags.bin     256 bytes: one flag byte per world tile id

The world blob is 512x512 tile ids at ONE BYTE PER TILE (gen_m7_assets.
world_map), so a 256-entry table indexed by the raw tile id is TOTAL — every
id a world byte can hold has an entry. A col_map whose world holds WIDER tile
ids has to mask them (`& $FF`) to index a 256-entry table, which silently
aliases two distinct ids onto one flag byte and leaves the asset author
carrying the rule "keep distinct flagged tile ids <= 255". One-byte ids design
that trap out instead of documenting it.

WHY DERIVED, NOT AUTHORED:

    gen_m7_assets already exposes the tile semantics as named sets, and its
    own comment (DRIVABLE_TILE_IDS, gen_m7_assets.py:220-223) records WHY:
    tests kept re-declaring the set, and one carrying its own {2,3,6}
    silently counted "driving on the centre line" as "off the road" on
    exactly the sides whose line tile was new.

    A hand-authored flag table is a second copy of that same set, with the
    same drift, plus an asset's provenance burden (docs/11_font_assets.md
    §4) for something with no artistry in it. Deriving keeps ONE definition:
    change the map's tile vocabulary and the flags follow in the same build.

The flag BITS (col_map design review decision D3) are declared in
engine/features/col_map_rom/feature.toml and mirrored here. A byte rather
than a single solid bit because the four rails that demand col_map
(mode7_explore, platformer_stream, m7_dungeon, m7_oshoot) need more than
"solid": platformer_stream distinguishes SOLID / PLATFORM / HAZARD. The
lookup costs the same either way — it returns the byte it loaded, and the
caller masks the bit it cares about.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_m7_assets as world                              # noqa: E402

# --- the flag bits -----------------------------------------------------------
# Mirrored in engine/features/col_map_rom/feature.toml, which is where they
# are DECLARED. Keep the two together.
FLAG_DRIVABLE = 1 << 0      # the car belongs here: road, centre line, start
FLAG_TRACK    = 1 << 1      # part of the course surface: DRIVABLE + kerbs

TABLE_ENTRIES = 256         # total over a one-byte tile id, by construction


def flag_for(tile_id: int) -> int:
    """The flag byte for one tile id, from the generator's OWN semantic sets.

    Note the lattice: every DRIVABLE tile is also TRACK, and a kerb is TRACK
    without being DRIVABLE. That is a real two-bit distinction, not two names
    for one predicate — which is why the byte earns its second bit here and
    not just in principle."""
    f = 0
    if tile_id in world.DRIVABLE_TILE_IDS:
        f |= FLAG_DRIVABLE
    if tile_id in world.TRACK_TILE_IDS:
        f |= FLAG_TRACK
    return f


def col_flags() -> bytes:
    """The 256-byte table. Exposed so tests can read the derivation from the
    generator instead of re-declaring it — the same reason gen_m7_assets
    exposes palette() and DRIVABLE_TILE_IDS.

    A test asserting the SHIPPED ROM against this function checks the upload
    path. It does NOT check the semantics: for that the col_map tests use
    coordinates hand-derived from the octagon's band arithmetic, which touch
    neither this function nor world_map()."""
    return bytes(flag_for(i) for i in range(TABLE_ENTRIES))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    table = col_flags()
    assert len(table) == TABLE_ENTRIES
    # Every id the world blob actually emits must be classified by one of the
    # generator's sets; an id that reaches here with no flag is a vocabulary
    # change that never reached the semantics. Cheap, and it fails the BUILD.
    unclassified = sorted(t for t in set(world.world_map()) if table[t] == 0
                          and t in world.TRACK_TILE_IDS)
    assert not unclassified, f"TRACK tile ids with no flag: {unclassified}"

    (out / "col_flags.bin").write_bytes(table)
    flagged = sum(1 for b in table if b)
    print(f"col flags -> {out} ({TABLE_ENTRIES} entries, {flagged} flagged)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
