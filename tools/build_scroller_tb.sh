#!/usr/bin/env bash
# Build scroller's PROTOTYPE-TIMEBASE variants (docs/96 §4). The generic make
# rule cannot pass a define, so they live here — the tools/build_shg_variants.sh
# shape.
#
# FIVE ROMS, ONE PER CANDIDATE SCHEME. Each is the shipped rail plus one
# `-D SF_TICK=n`; with no define the same source assembles to
# `build/scroller.sfc` byte for byte, which is the reversibility property
# docs/94 §4 clause 1 asks for and is asserted below rather than claimed.
#
#   1 tb_lump       6 logic ticks per 5 frames under PAL. The scheme docs/95 §4
#                   refuted on the TIGHTEST rail's budget; here the budget is
#                   not the obstacle, so what it measures is its parity.
#   2 tb_accum6_5   one tick per frame, the per-frame step scaled by 6/5 in 8.8
#                   with the fraction carried between frames.
#   3 tb_accum      the same, scaled by the MEASURED frame ratio 1.201804.
#   4 tb_intscale   one tick per frame, the step scaled and rounded to the
#                   NEAREST integer: round(2 x 1.2018) = 2.
#   5 tb_intup      the same rounded UP: 3.
#
# Run from the repo root, AFTER `make scroller` (the assets and the emitted
# map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/scr
VROM=vendor/rom
SRC=game/scroller/main.asm
ASM="$SRC $(ls game/scroller/scenes/*.asm) $(ls engine/features/*/*.asm)"

INC="-I $MAP -I $VROM -I game/scroller \
     -I engine/features/scene_mgr -I engine/features/input \
     -I engine/features/oam_sprites -I engine/features/fade \
     -I engine/features/scroller_bg -I engine/features/scroller_obj"

build_one() {          # $1 = name, $2 = SF_TICK value
    local name=$1 mode=$2
    python3 allocator/no_literals.py --map $MAP/symbol_map.json $ASM >/dev/null
    # `-g` + `-Ln` emit the VICE label file tools/measure_tb_cost.py reads.
    # They add debug info to the OBJECT, not to the raw binary — and the
    # control arm's `cmp` below is what proves that rather than assuming it.
    ca65 --cpu 65816 -g $INC ${mode:+-D SF_TICK=$mode} \
         --bin-include-dir $BUILD/assets -o "$BUILD/$name.o" "$SRC"
    ld65 -C $VROM/lorom_512k.cfg -Ln "$BUILD/$name.lbl" \
         -o "$BUILD/$name.sfc" "$BUILD/$name.o"
    python3 tools/fix_checksum.py "$BUILD/$name.sfc" >/dev/null
    printf '  %-22s %s\n' "$name.sfc" "$(md5sum "$BUILD/$name.sfc" | cut -d' ' -f1)"
}

echo "scroller timebase variants:"
# The CONTROL arm first: no define at all, through this same recipe. It must
# come out byte-identical to `make scroller`'s image, or the guards leak and
# every parity number below is measured against a moved baseline.
build_one scroller_tb_off ""
if ! cmp -s "$BUILD/scroller_tb_off.sfc" "$BUILD/scroller.sfc"; then
    echo "FAILED: the flag-off build is NOT byte-identical to build/scroller.sfc" >&2
    exit 1
fi
echo "  (flag-off arm is byte-identical to build/scroller.sfc — guards do not leak)"
build_one scroller_tb_lump      1
build_one scroller_tb_accum6_5  2
build_one scroller_tb_accum     3
build_one scroller_tb_intscale  4
build_one scroller_tb_intup     5
