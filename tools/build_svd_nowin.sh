#!/usr/bin/env bash
# Build split_v_demo's -D proof variant. The generic make rule cannot pass -D,
# so it lives here — the same shape tools/build_split_h_2p_variants.sh has.
#
# ONE variant, and the count is the headline. The obvious shape of this rail
# needs FOUR (-DNO_WINDOW, -DOBJ_CLIP, -DAUTODEMO, -DDIAGONAL): a per-half OBJ
# clip and a diagonal seam have nowhere but a build flag to live if the
# composition is not declared. Here those two are runtime MODES over one
# declared composition (the same HDMA channel reading a different table), and
# -DAUTODEMO's job is done by the lockstep harness driving pads on absolute
# frames. What does NOT collapse into a mode is the control:
#
#   svd_nowin  SVD_NOWIN=1  the window recipe compiled OUT — no W12SEL, no
#              TMW, no seam channel — so BG1 (camera A) fills the whole screen
#              and the vertical split COLLAPSES. Every assertion that reads
#              the rail's two-region signature or its seam bar must FAIL on
#              this ROM. That is what makes those assertions non-vacuous: a
#              screen with two visibly different halves is a claim about the
#              WINDOW, and without a build that removes the window, "the two
#              halves differ" could be satisfied by any picture with detail on
#              both sides of x = 128.
#
# It has to be a separate BINARY rather than a fourth mode: a control the code
# under test can write is not a control. The mode word lives in the same DP the
# window code reads, so a "window off" mode would be the same program claiming
# both results.
#
# Run from the repo root, AFTER `make split_v_demo` (the assets and the emitted
# map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/svd
VROM=vendor/rom
SRC=game/split_v_demo/main.asm

INC="-I $MAP -I $VROM -I game/split_v_demo
     -I engine/features/scene_mgr -I engine/features/fade
     -I engine/features/input -I engine/features/input2
     -I engine/features/oam_sprites
     -I engine/features/svd_bg -I engine/features/svd_obj"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_svd_nowin: run 'make split_v_demo' first ($MAP is missing)" >&2
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

build_variant svd_nowin -D SVD_NOWIN=1
