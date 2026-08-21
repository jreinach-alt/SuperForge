#!/usr/bin/env bash
# Build railshooter's -D MEASUREMENT variant. The generic make rule cannot pass
# a define, so it lives here — the tools/build_shg_variants.sh shape.
#
# ONE probe, and it carries the whole of this rail's speed evidence:
#
#   rs_probe   RS_PROBE_MARKER=1   the SURFACE-SPEED probe: the same rail with
#              the measurement plane (`rs_map_probe.bin`) in place of the
#              shipping one. Identical 32 KB, identical geometry, identical
#              code — only the tile COLOURS differ: the magenta index is
#              re-spent so it marks the grid INTERSECTIONS and nothing else,
#              which turns "how many screen px per frame does the ground move
#              at row r" into a colour lookup plus a centroid instead of an
#              estimate. Its lattice period is the grid's own 32 world px,
#              under the plane's ~54-px visible depth, so one or two marker
#              rows are on screen at every instant at any rail speed.
#
#              It is the SUBJECT of the calibration case, not a control: the
#              case reads the SURFACE rate from these pixels and the PYLON rate
#              from the same run's OAM, on the same screen rows, and refuses a
#              divergence. Without it the ground's rate is only inferable from
#              a grid whose bands merge and whose colour the sky also uses.
#
#              The shipping ROM never contains the marker plane, and the case
#              proves the probe is a faithful stand-in by asserting the two
#              builds' pylon OAM trajectories are IDENTICAL frame for frame —
#              a probe that had perturbed the rail could not.
#
# Run from the repo root, AFTER `make railshooter` (the assets and the emitted
# map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/rs
VROM=vendor/rom
SRC=game/railshooter/main.asm

INC="-I $MAP -I $VROM -I game/railshooter
     -I engine/features/scene_mgr -I engine/features/input
     -I engine/features/fade -I engine/features/pool
     -I engine/features/split_band -I engine/features/oam_sprites
     -I engine/features/mode7_persp -I engine/features/rs_floor
     -I engine/features/sky_band -I engine/features/rs_obj
     -I engine/features/rs_logic
     -I engine/features/region -I engine/features/tick_scale"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_rs_probe: run 'make railshooter' first ($MAP is missing)" >&2
    exit 1
fi

build_variant() {
    local name="$1"; shift
    # shellcheck disable=SC2086
    ca65 --cpu 65816 $INC --bin-include-dir "$BUILD/assets" "$@" \
        -o "$BUILD/$name.o" "$SRC"
    ld65 -C "$VROM/lorom_512k.cfg" -o "$BUILD/$name.sfc" "$BUILD/$name.o"
    python3 tools/fix_checksum.py "$BUILD/$name.sfc" >/dev/null
    echo "built $BUILD/$name.sfc"
}

case "${1:-all}" in
    marker|all) build_variant rs_probe -D RS_PROBE_MARKER=1 ;;
    *) echo "usage: $0 [marker|all]" >&2; exit 2 ;;
esac
