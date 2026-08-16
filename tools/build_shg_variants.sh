#!/usr/bin/env bash
# Build split_h_irq_grad_demo's -D control variants. The generic make rule
# cannot pass a define, so they live here — the tools/build_seam_irq_variants.sh
# shape.
#
# TWO controls, and between them they carry both halves of this rail's evidence:
#
#   shg_nograd   SHG_NO_GRAD=1      the GRADIENT FLIP control: the same rail
#                with no COLDATA table, no gradient channel bit in HDMAEN and
#                no colour math. The rendered BLUE channel must go FLAT here
#                while it ramps on the subject — without this build, "blue
#                ramps down the floor" could be satisfied by anything that
#                happens to darken with depth, and the plane's own perspective
#                does exactly that in green. It is also the SUBJECT SIDE of
#                the gold comparison below, because a gradient row would
#                differ from a control that structurally cannot have one.
#
#   shg_origin   SHG_HDMA_ORIGIN=1  the GOLD control: band 2's origin through
#                the classic origin channel pair (non-repeat [112,X,Y][1,X,Y]
#                [0] tables, in the HDMAEN mask) instead of the IRQ +
#                pre-armed GP-DMA path. main.asm makes it imply SHG_NO_GRAD
#                (a build with no freed channel has nothing to spend), which
#                is why its partner above is the no-grad build and not the
#                subject. No IRQ, no SF_IRQ_VECTOR (this build exercises
#                header.inc's NMI_STUB default), no VTIME write. The headline
#                assertion: shg_nograd vs shg_origin framebuffers
#                BYTE-IDENTICAL on absolute frames, WITH BOTH CAMERAS MOVING
#                — a strictly stronger statement than the frozen equality
# proved, because a stamper that dropped a live value
#                is invisible to a still.
#
# NOT built here, and why:
#   -DSHG_FREEZE       exists as a switch in shg_cam.asm for a future bisect,
#                      but needs no ROM: `Machine` lands on an ABSOLUTE frame
#                      by construction, so the moving comparison above is
#                      well-defined without freezing either side.
#   -DIRQ_INTERLEAVE   the write-twice-ValueLatch tear control. A
#                      falsify plant does the same job at zero registration
#                      cost and requires named tests to go RED
#                      (`stage-byte-interleave`, tools/plants/).
#
# Run from the repo root, AFTER `make split_h_irq_grad_demo` (the assets and
# the emitted map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/shg
VROM=vendor/rom
SRC=game/split_h_irq_grad_demo/main.asm

INC="-I $MAP -I $VROM -I game/split_h_irq_grad_demo
     -I engine/features/scene_mgr -I engine/features/fade
     -I engine/features/irq -I engine/features/shg_floor
     -I engine/features/shg_cam -I engine/features/shg_grad"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_shg_variants: run 'make split_h_irq_grad_demo' first ($MAP is missing)" >&2
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
    nograd)  build_variant shg_nograd -D SHG_NO_GRAD=1 ;;
    origin)  build_variant shg_origin -D SHG_HDMA_ORIGIN=1 ;;
    all)     build_variant shg_nograd -D SHG_NO_GRAD=1
             build_variant shg_origin -D SHG_HDMA_ORIGIN=1 ;;
    *) echo "usage: $0 [nograd|origin|all]" >&2; exit 2 ;;
esac
