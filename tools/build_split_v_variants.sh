#!/usr/bin/env bash
# Build the split_v_fight -D proof variants. The generic make rule cannot pass
# -D, so these live here — the same shape the other variant scripts in this
# directory have, and for the same reason.
#
# WHY STATIC BUILDS AT ALL. The rail's headline claim is that a merged view is
# PIXEL-IDENTICAL to a no-split view. Proving that from the interactive build
# would mean capturing two running ROMs at the same instant and hoping the
# spread had settled in both — a race the assertion would lose intermittently
# and pass most of the time, which is worse than no test. Freezing the swept
# variable removes the race entirely:
#
#   sv_hold_merge  SV_HOLD=20   dx=40  -> spread eases to 0  (fully MERGED)
#   sv_hold_split  SV_HOLD=100  dx=200 -> spread eases to 36 (SPLIT, bar shown)
#   sv_nowin       SV_NOWIN + SV_HOLD=20  the no-split REFERENCE: window off,
#                  BG3 off the main screen. hold_merge must diff to ~0
#                  against this — that IS the seamlessness proof.
#   sv_cross       SV_HOLD=-100 the CROSSED state: a negative hold puts
#                  fighter 1 to the RIGHT of fighter 2, so the split must
#                  follow the swap (blue LEFT, red RIGHT).
#   sv_autodemo    SV_AUTODEMO  self-running: the fighters march wall to wall
#                  through each other, so one boot plays the whole
#                  separate / merge / side-swap cycle.
#
# Run from the repo root, AFTER `make split_v_fight` (the assets and the
# emitted map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/sv
VROM=vendor/rom
SRC=game/split_v_fight/main.asm

INC="-I $MAP -I $VROM -I game/split_v_fight
     -I engine/features/scene_mgr -I engine/features/input
     -I engine/features/input2 -I engine/features/oam_sprites
     -I engine/features/fade
     -I engine/features/split_v_bg -I engine/features/split_v_obj
     -I engine/features/region -I engine/features/tick_scale
     -I vendor/tad -I assets/audio/export"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_split_v_variants: run 'make split_v_fight' first ($MAP is missing)" >&2
    exit 1
fi

build_variant() {
    local name="$1"; shift
    # shellcheck disable=SC2086
    ca65 --cpu 65816 $INC --bin-include-dir "$BUILD/assets" "$@" \
        -o "$BUILD/$name.o" "$SRC"
    ld65 -C "$VROM/lorom_512k.cfg" -o "$BUILD/$name.sfc" \
        "$BUILD/$name.o" "$BUILD/sv_tad_wrapper.o" "$BUILD/sv_tad_data.o"
    python3 tools/fix_checksum.py "$BUILD/$name.sfc" >/dev/null
    echo "built $BUILD/$name.sfc"
}

build_variant sv_hold_merge -D SV_HOLD=20
build_variant sv_hold_split -D SV_HOLD=100
build_variant sv_nowin      -D SV_NOWIN=1 -D SV_HOLD=20
build_variant sv_cross      -D SV_HOLD=-100
build_variant sv_autodemo   -D SV_AUTODEMO=1
