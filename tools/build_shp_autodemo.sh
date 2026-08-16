#!/usr/bin/env bash
# Build split_h_persp_demo's controller-free pilot ROM. The generic make rule
# cannot pass -D, so it lives here — the same shape tools/build_svd_nowin.sh
# and tools/build_split_h_2p_variants.sh have.
#
# ONE variant, and it RESTORES A DEFAULT rather than adding a behaviour. The
# reference rail ships no `-DAUTODEMO` at all — `build_split_h_persp_variants.sh`
# lists eleven builds (noseam, stillnoseam, latch, stilllatch, holdb, freeze,
# still, stillfixed, stillsame, sky, stillsky) and none of them is one, and the
# template reads no pad anywhere. It does not need an autodemo because its
# DEFAULT build IS one:
#
#   camera A   `FRAME_COUNTER * 4` masked to 8 bits — "auto-rotate (4
#              units/frame) -> full turn every 64 frames",
#              suppressed only by -DFREEZE.
#   camera B   `(FRAME_COUNTER >> 3) & 7` — "zoom-loop (advance every 8
#              frames)", suppressed only by -DHOLD_B.
#
# The shipping ROM replaced both with pad 1, deliberately: a free-running
# animation can only be SAMPLED, while a pad-driven one can be stopped, held
# and walked BACK, which is what makes "drive one axis and the other band must
# not move" assertable at all. This build hands the autonomous cameras back for
# piloting. It is `sh2_autocam`'s shape exactly — there too the shipping ROM is
# the pad-driven one and the -D restores the autonomous model
# (tools/build_split_h_2p_variants.sh:112) — and like it, it is NOT a
# non-vacuity control.
#
#   shp_autodemo  SHP_AUTODEMO=1  cam_input is compiled out; the heading steps
#                 +1 per frame (wrapping at 64) and the zoom is head >> 3.
#
# NO NEW STATE, AND THE RATES ARE EXACT. `pose_rom` here is
# indexed by 64 headings, so a
# full turn in 64 frames is +1 heading per frame — which makes SHP_HEAD the
# frame counter mod 64. The eight zooms cycle over those same 64
# frames, and `(frame & 63) >> 3` is `(frame >> 3) & 7`, so the zoom is a pure
# function of the heading. A dp claim that existed only in the -D build would
# shift the allocator's map and move the SHIPPING ROM's md5 for a variant it
# does not contain (split_v_fight's demo_walk pays the same toll,
# game/split_v_fight/scenes/fight.asm:326-330).
#
# THE SHIPPING ROM DOES NOT MOVE: every line is inside an `.ifdef
# SHP_AUTODEMO`, so `make split_h_persp_demo` still builds
# c0dde667da7c4a4d395be6d45846e055.
#
# Run from the repo root, AFTER `make split_h_persp_demo` (the assets and the
# emitted map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/shp
VROM=vendor/rom
SRC=game/split_h_persp_demo/main.asm

INC="-I $MAP -I $VROM -I game/split_h_persp_demo
     -I engine/features/scene_mgr -I engine/features/fade
     -I engine/features/input
     -I engine/features/shp_floor -I engine/features/shp_cam"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_shp_autodemo: run 'make split_h_persp_demo' first ($MAP is missing)" >&2
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

build_variant shp_autodemo -D SHP_AUTODEMO=1
