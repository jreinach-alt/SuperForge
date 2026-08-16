#!/usr/bin/env bash
# Build the SuperForge LOCKSTEP MesenCore (docs/53 D-DH2).
#
# The shared tree at /tmp/Mesen2 is used by other sessions on this box and is
# NEVER touched: this script copies it to a private tree, applies the lockstep
# patches there, and builds that copy. The result is a superset core — every
# stock export unchanged, eight lockstep exports added — bound by this repo's
# harness via SF_MESEN_CORE / the Machine core_path parameter.
#
# Idempotent: an already-patched tree is not re-patched; an up-to-date build
# is a fast no-op relink check. Usage:
#
#   bash vendor/mesen_patches/apply.sh [pristine-src] [patched-dst]
#
# Defaults: src=/tmp/Mesen2, dst=/tmp/Mesen2-lockstep. The built core lands at
# <dst>/InteropDLL/obj.linux-x64/MesenCore.so and is cached to
# tools/Mesen/MesenCore-lockstep.so (gitignored, survives a wiped /tmp).
#
# What the patches are (see README.md here for the mechanism):
#   lockstep_core_edits.patch — Debugger.cpp break-sleep observability,
#       EmuSettings.h ReseedRng, VideoDecoder.h IsFrameDecodePending
#   LockstepSync.h            — new header (the two observability atomics)
#   LockstepApiWrapper.cpp    — new InteropDLL translation unit: the eight
#       exports (LoadRomParked, RunFramesSync, SetPowerOnSeed, ...)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
SRC="${1:-/tmp/Mesen2}"
DST="${2:-/tmp/Mesen2-lockstep}"
CACHE="$REPO_ROOT/tools/Mesen/MesenCore-lockstep.so"
SO="$DST/InteropDLL/obj.linux-x64/MesenCore.so"

if [ ! -d "$DST" ]; then
    if [ ! -d "$SRC" ]; then
        echo "ERROR: pristine Mesen2 tree not found at $SRC (run tools/setup.sh first)" >&2
        exit 1
    fi
    echo "Copying $SRC -> $DST (private patch tree; the shared tree stays pristine)..."
    cp -a "$SRC" "$DST"
fi

# Apply the three-file edit patch once (marker: the LockstepSync include).
if ! grep -q "LockstepSync" "$DST/Core/Debugger/Debugger.cpp"; then
    echo "Applying lockstep_core_edits.patch..."
    (cd "$DST" && patch -p1 --no-backup-if-mismatch) < "$HERE/lockstep_core_edits.patch"
fi

# The two new files are copied unconditionally — cp is the update path.
cp "$HERE/LockstepSync.h" "$DST/Core/Debugger/LockstepSync.h"
cp "$HERE/LockstepApiWrapper.cpp" "$DST/InteropDLL/LockstepApiWrapper.cpp"

echo "Building the lockstep core (incremental; cold build ~10 min)..."
(cd "$DST" && make core -j"$(nproc)")

# Pipe-free on purpose — `nm | grep -q` under `set -euo pipefail` dies of
# SIGPIPE (rc 141) at the first match and reads as "symbol absent".
EXPORTS="$(nm -D "$SO")"
for sym in RunFramesSync LoadRomParked SetPowerOnSeed FlushVideoFrame \
           TakeScreenshotToFile LockstepBreakSleepDepth LockstepParkGeneration; do
    case "$EXPORTS" in
        *" $sym"*) ;;
        *) echo "ERROR: built core at $SO lacks export $sym" >&2; exit 1;;
    esac
done

mkdir -p "$(dirname "$CACHE")"
cp "$SO" "$CACHE"
echo "OK: lockstep core built at $SO (cached to $CACHE)"
echo "Bind it with: export SF_MESEN_CORE=$SO"
