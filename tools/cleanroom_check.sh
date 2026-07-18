#!/usr/bin/env bash
# =============================================================================
# cleanroom_check.sh — clean-room NAME TRIPWIRE (cheap CI floor, NOT a guarantee).
# =============================================================================
# WHAT THIS IS: a fast, non-exhaustive denylist scan for retail game / company /
# eliminated-lineage names in committed text AND inside committed zips' text
# members. It is a HYGIENE FLOOR and a provenance SIGNAL — a hit means "someone
# referenced a retail name, look closer," not "a copyright was infringed."
#
# WHAT THIS IS *NOT*: a completeness guarantee. A wordlist can never be complete
# (it silently shipped "Contra III" in 5 files before the names were added here),
# and a NAME is the LOW-risk artifact anyway. The HIGH-risk artifacts — copied or
# ripped ASSETS, and broken THIRD-PARTY ATTRIBUTION — are guarded by the
# COMPLETE control: tools/provenance_check.py (the reproducible-assets gate, which
# enumerates every blob and FAILs any opaque one) plus the publish-time semantic
# review (see docs/cleanroom_policy.md). Run all three; this is just the cheapest.
#
# Run from the repo root: bash tools/cleanroom_check.sh [tree_root]
# Exit 0 = no tripwire hit. Any hit prints file:line and exits 1.
# =============================================================================
set -uo pipefail

ROOT="${1:-.}"
cd "$ROOT"

FAIL=0

# --- Reviewed-references allowlist (conscious exemptions) --------------------
# A tripwire that hard-failed on every legitimate genre/platform descriptor in
# shipping docs would be unusable as a CI floor, so a NARROW, REVIEWED allowlist
# exempts lines a human already cleared (e.g. "overhead-shooter, Contra III
# style" as mechanism language, or "Super Nintendo" as the platform name). Each
# entry is `relpath<TAB>fixed-substring`; a hit on that file is dropped ONLY if
# the matching line contains the substring. New/unreviewed hits still trip.
# Adding an entry is a CONSCIOUS act — it means "I read this and it is a
# mechanism description / platform name, not branding or copied content."
# The allowlist is documented in docs/cleanroom_policy.md.
ALLOWLIST="tools/cleanroom_allow.txt"
_allow_filter() {  # stdin: grep "file:line:content" hits; stdout: non-exempt hits
    if [ ! -f "$ALLOWLIST" ]; then cat; return; fi
    local line file rest sub exempt ar af
    while IFS= read -r line; do
        file="${line%%:*}"; file="${file#./}"
        rest="${line#*:}"             # strip leading "file:"
        exempt=0
        while IFS=$'\t' read -r ar asub; do
            [ -z "$ar" ] && continue
            case "$ar" in \#*) continue ;; esac
            af="${ar#./}"
            if [ "$af" = "$file" ] && [ -n "$asub" ] && \
               printf '%s' "$line" | grep -qF -- "$asub"; then
                exempt=1; break
            fi
        done < "$ALLOWLIST"
        [ "$exempt" -eq 0 ] && printf '%s\n' "$line"
    done
}

# Paths never scanned: build outputs, the fetched emulator core cache, git
# metadata, python caches, and this gate itself (it necessarily contains the
# patterns). The shipped policy doc (docs/cleanroom_policy.md) discusses the risk
# model and the gate vocabulary itself, so it is excluded from the name scan; it
# is mechanism-only (names no retail title) by design, but excluding it keeps the
# self-reference from tripping the gate.
EXCLUDES=(--exclude-dir=build --exclude-dir=.git --exclude-dir=Mesen
          --exclude-dir=__pycache__ --exclude-dir=.pytest_cache
          --exclude=cleanroom_check.sh --exclude=cleanroom_policy.md
          --exclude=cleanroom_allow.txt --exclude=provenance_manifest.toml
          --exclude=provenance_check.py
          # split tooling — carries the scrub vocabulary + lineage terms BY
          # DESIGN, and is removed from the materialized tree by dryrun_split.sh
          # (never ships). Excluded so the gate stays clean when run in the bare
          # staging overlay (e.g. from the edit-time hook) too.
          --exclude=scrub_split.py --exclude=dryrun_split.sh
          # the fullsnes hardware reference — FETCHED by setup.sh into
          # docs/reference/ (git-ignored, never committed; licensing per
          # NOTICE). The gate scans the working tree, so after a networked
          # setup.sh run the fetched copy is present on disk; without this
          # exclusion `make check` fails on every fresh machine right after
          # its own setup step (found 2026-07-18 — the June dev sandbox
          # blocked the fetch host, so setup + gate had never both
          # succeeded in one tree before). The forbidden-FILE-CLASS check
          # below keeps failing on a fullsnes file at any OTHER path.
          --exclude=fullsnes.htm --exclude=fullsnes.txt)

# --- 1. Eliminated-lineage vocabulary (widened list — S4 paper cut) ---
LINEAGE='\b(lua|pico-?8|native[_-]emitter|interpreter|bytecode)\b'
LINEAGE_HITS=$(grep -rInEi "${EXCLUDES[@]}" "$LINEAGE" . | _allow_filter)
if [ -n "$LINEAGE_HITS" ]; then
    echo "$LINEAGE_HITS"
    echo "cleanroom: FAIL — eliminated-lineage vocabulary found (above)"
    FAIL=1
fi

# --- 2. Commercial game / company names (word-bounded, NON-EXHAUSTIVE) ---
# Word-bounded because bare substrings false-positive ('chrono' in
# 'synchronously'). EXTEND this freely — it is a floor, never trusted as the
# ceiling. Names added 2026-06 from the recovery-gate audit are marked (R).
COMMERCIAL='\b('
# --- games ---
COMMERCIAL+='f-?zero|gradius|castlevania|top gear|pilotwings|chrono trigger|'
COMMERCIAL+='final fantasy|super metroid|zelda|donkey kong|dkc|mega ?man|'
COMMERCIAL+='secret of mana|seiken densetsu|rudra|mario|smk|rpm racing|'
COMMERCIAL+='star[ -]?fox|metroid|kirby|battletoads|silius|space ?harrier|'
COMMERCIAL+='out ?run|super ?scaler|galaxy ?force|after ?burner|'
# (R) recovery-gate audit additions — missing retail names the old list lacked
COMMERCIAL+='contra|axelay|street ?racer|dragon ?ball|but[oō]uden|'
COMMERCIAL+='air ?strike ?patrol|r-?type|parodius|darius|actraiser|'
# --- companies / publishers (R) ---
COMMERCIAL+='nintendo|konami|capcom|squaresoft|enix|sega|'
# --- sample packs / hardware / music-rip sources ---
COMMERCIAL+='juno-?106|linndrum|dx-?7|yamaha|roland|korg|legowelt|zophar|snesmusic'
COMMERCIAL+=')\b'
COMMERCIAL_HITS=$(grep -rInEi "${EXCLUDES[@]}" "$COMMERCIAL" . | _allow_filter)
if [ -n "$COMMERCIAL_HITS" ]; then
    echo "$COMMERCIAL_HITS"
    echo "cleanroom: FAIL — commercial / company name found in committed text (above)"
    FAIL=1
fi

# --- 3. Commercial names INSIDE committed zips' text members (audit gap) ---
# The text grep above skips binaries, so a retail name in a zip's metadata.json /
# README / prompt slips through (the audit found "Chrono Trigger / Final Fantasy"
# inside examples/itch_cc0/...persp.zip's metadata.json). Extract each zip's TEXT
# members to stdout and run the same denylist. unzip is part of the toolchain
# (setup.sh); if it is absent, warn rather than silently skip.
if command -v unzip >/dev/null 2>&1; then
    while IFS= read -r -d '' zip; do
        # List members, keep likely-text ones, grep their content for the names.
        while IFS= read -r member; do
            case "$member" in
                */) continue ;;  # directory entry
                *.json|*.txt|*.md|*.xml|*.csv|*.ini|*.cfg|*.yaml|*.yml|*README*|*LICENSE*|*.nfo)
                    hit=$(unzip -p "$zip" "$member" 2>/dev/null \
                          | grep -InEi "$COMMERCIAL" || true)
                    if [ -n "$hit" ]; then
                        # In-zip exemption: an allowlist line `zip<TAB>member`
                        # (member as the fixed substring) clears a REVIEWED zip
                        # member. Conscious act — see docs/cleanroom_policy.md.
                        zkey="${zip#./}"
                        if grep -qF -- "$(printf '%s\t%s' "$zkey" "$member")" \
                               "$ALLOWLIST" 2>/dev/null; then
                            continue
                        fi
                        echo "$zip :: (in-zip) $member"
                        echo "$hit" | sed 's/^/    /'
                        FAIL=1
                    fi
                    ;;
            esac
        done < <(unzip -Z1 "$zip" 2>/dev/null)
    done < <(find . -path ./build -prune -o -path ./.git -prune -o \
                 -path ./tools/Mesen -prune -o -name '*.zip' -print0)
    if [ "$FAIL" -eq 1 ]; then
        : # message already printed per-hit; the gate fails below.
    fi
else
    echo "cleanroom: WARN — unzip not found; SKIPPING in-zip name scan (install unzip)."
fi

# --- 4. Forbidden file classes (committed-tree scan) ---
# Built ROMs are rebuilt on demand; MesenCore is fetched/built by setup.sh;
# music rips and the fullsnes reference must never be committed. Commercial-NAMED
# media files are also blocked by name (the text grep skips binaries).
# The ONE exemption: docs/reference/fullsnes.* — setup.sh's canonical fetch
# destination (git-ignored; see NOTICE). A fullsnes file at any other path
# still fails.
BADFILES=$(find . -path ./build -prune -o -path ./.git -prune -o \
    -path ./tools/Mesen -prune -o \
    -path './docs/reference/fullsnes.*' -prune -o \
    \( -name '*.sfc' -o -name '*.rsn' -o -name '*.spc' -o \
       -name 'MesenCore.*' -o -name 'fullsnes.*' -o \
       -iname '*zophar*' -o -iname '*(EMU)*' -o \
       -iname '*f-zero*' -o -iname '*fzero*' -o -iname '*gradius*' -o \
       -iname '*castlevania*' -o -iname '*battletoads*' -o \
       -iname '*contra*' -o -iname '*axelay*' -o -iname '*actraiser*' -o \
       -iname '*r-type*' -o -iname '*parodius*' -o -iname '*darius*' -o \
       -iname '*mega*man*' -o -iname '*mario*' -o -iname '*metroid*' -o \
       -iname '*zelda*' -o -iname '*top*gear*' -o -iname '*pilotwings*' -o \
       -iname '*ff[0-9]*' -o -iname '*final*fantasy*' -o \
       -iname '*chrono*' -o -iname '*linndrum*' -o -iname '*juno*' -o \
       -iname '*dx7*' -o -iname '*legowelt*' -o -iname '*snesmusic*' \) -print)
if [ -n "$BADFILES" ]; then
    echo "$BADFILES"
    echo "cleanroom: FAIL — forbidden file class committed (above)"
    FAIL=1
fi

# --- 5. Oversized media (>2MB needs a human look; licensing tripwire) ---
BIG=$(find . -path ./build -prune -o -path ./.git -prune -o \
    -path ./tools/Mesen -prune -o -type f -size +2M -print)
if [ -n "$BIG" ]; then
    echo "$BIG"
    echo "cleanroom: FAIL — file over 2MB committed (review + allowlist consciously)"
    FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
echo "cleanroom: clean (name tripwire only — NOT a completeness guarantee; see provenance_check.py + publish-time review)"
