#!/usr/bin/env bash
# Build split_h_demo's controller-free pilot ROM. The generic make rule cannot
# pass -D, so it lives here — the same shape tools/build_svd_nowin.sh and
# tools/build_split_h_2p_variants.sh have, and for the same reason.
#
# ONE variant, and it is a PILOT BUILD rather than a non-vacuity control. The
# distinction matters because this repo's other -D ROMs are controls: they
# exist to make an assertion fail. This one exists so a human can watch the
# rail run with no controller attached:
#
#   shd_autodemo  SHD_AUTODEMO=1  the pad axes are compiled out and the camera
#                 heading steps itself — one ROT_SPD step every 4 frames, a
#                 full turn in 256 frames. That rate is one 256th of a turn per
#                 frame — NOT the 2-unit HELD-shoulder step — and one step of
#                 this rail's 64-heading base is four of those units.
#
# ONE THING ANIMATES, NOT TWO, because the second is a function of the first.
# A sweep could drive the camera AND an instrument fill bar on its own triangle
# wave — two independent state words. Here the instrument IS bg_text's 4-cell
# readout of the heading, reprinted on change, so the single autonomous heading
# step drives the floor band's matrix rebuild and the panel band's readout
# together. Both bands animate; there is nothing left over to sweep.
#
# The A-button split toggle is left armed and pad-driven on purpose: a
# self-toggling split would make the picture unstable to pilot, and the split's
# lifecycle is a separate subject with its own coverage. With no pad attached
# it never fires.
#
# THE SHIPPING ROM DOES NOT MOVE. Every line of the variant is inside an
# `.ifdef SHD_AUTODEMO`, and it declares no state of its own — the phase is
# read from `US_FRAMES`, the scene's existing heartbeat — so the allocator's
# map is identical and `make split_h_demo` still builds
# 47e687116da2d2b5c220a7fb4a19d793.
#
# Run from the repo root, AFTER `make split_h_demo` (the generated pose blobs
# and the emitted map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/shd
VROM=vendor/rom
SRC=game/split_h_demo/main.asm

INC="-I $MAP -I $VROM -I game/split_h_demo
     -I engine/features/scene_mgr -I engine/features/input
     -I engine/features/fade -I engine/features/bg_text
     -I engine/features/mode7_floor -I engine/features/split_band
     -I engine/features/mode7_persp"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_shd_autodemo: run 'make split_h_demo' first ($MAP is missing)" >&2
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

build_variant shd_autodemo -D SHD_AUTODEMO=1
