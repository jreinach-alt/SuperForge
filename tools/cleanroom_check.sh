#!/usr/bin/env bash
# =============================================================================
# cleanroom_check.sh — clean-room NAME TRIPWIRE (a cheap floor, NOT a guarantee)
# =============================================================================
# WHAT THIS IS: a fast, non-exhaustive denylist scan of committed text — and of
# the text members of committed zips — for retail game, company and hardware
# brand names. A hit means "someone wrote a name that wants a second look", not
# "a copyright was infringed".
#
# WHAT THIS IS *NOT*: a completeness guarantee. A wordlist can never be
# complete, and a NAME is the LOW-risk artifact anyway. The HIGH-risk artifacts
# are copied ASSETS and broken THIRD-PARTY ATTRIBUTION, and neither is
# something a grep can settle — they are guarded by NOTICE, by the per-pack
# provenance READMEs under vendor/art/, and by reading the diff. Run this
# because it is the cheapest of the three, not because it is the strongest.
#
# It prints its REACH on every run — text files swept, allowlist entries
# consumed — so a pass that swept nothing, or that was quietly talked out of
# every hit, reads as disarmed rather than as clean.
#
# Run from the repo root:  bash tools/cleanroom_check.sh [tree_root]
# Exit 0 = no tripwire hit. Any hit prints file:line and exits 1.
# `make cleanroom` runs it as the first gate in the block.
# =============================================================================
set -uo pipefail

ROOT="${1:-.}"
cd "$ROOT" || exit 1

FAIL=0

# --- Reviewed-references allowlist (conscious exemptions) --------------------
# A tripwire that hard-failed on every legitimate technical term would be
# unusable, so a NARROW allowlist exempts lines a human has already read. Each
# entry is `relpath<TAB>fixed-substring`; a hit in that file is dropped ONLY if
# the matching line contains the substring. New or moved hits still trip.
# Adding an entry is a CONSCIOUS act — it means "I read this line and it is
# mechanism language, not branding and not copied content."
ALLOWLIST="tools/cleanroom_allow.txt"
ALLOW_TALLY="$(mktemp)"
trap 'rm -f "$ALLOW_TALLY"' EXIT
_allow_filter() {   # stdin: "file:line:content" hits; stdout: non-exempt hits
    if [ ! -f "$ALLOWLIST" ]; then cat; return; fi
    local line file exempt ar asub af
    while IFS= read -r line; do
        file="${line%%:*}"; file="${file#./}"
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
        if [ "$exempt" -eq 0 ]; then
            printf '%s\n' "$line"
        else
            printf 'x' >> "$ALLOW_TALLY"
        fi
    done
}

# Paths never scanned: build output, the fetched emulator core cache, git
# metadata, python caches, and this gate plus its allowlist (both necessarily
# spell the denylist out in full).
EXCLUDES=(--exclude-dir=build --exclude-dir=.git --exclude-dir=Mesen
          --exclude-dir=__pycache__ --exclude-dir=.pytest_cache
          --exclude=cleanroom_check.sh --exclude=cleanroom_allow.txt)

# --- 1. Commercial game / company names (boundary-anchored, NON-EXHAUSTIVE) --
# Anchored rather than bare-substring because a bare substring false-positives
# ('chrono' inside 'synchronously', 'enix' inside 'phoenix'). The anchors are
# spelled out as "not an alphanumeric" instead of using `\b`, because `_` is a
# word character to `\b` — a `\b`-anchored pattern is blind to every name that
# is embedded in a snake_case identifier or a filename, which is where names
# actually turn up in a source tree (`mario_sprite.png`, `x_fzero_y` both walk
# straight past `\b`). Multiword titles take `[-_[:space:]]` as ONE separator
# class rather than a literal space, so `Secret-of-Mana` and `top_gear` are the
# same hit as the spaced spelling. EXTEND this list freely — it is a floor,
# never trusted as a ceiling.
_BL='(^|[^A-Za-z0-9])'          # left anchor:  start of line, or a non-alnum
_BR='([^A-Za-z0-9]|$)'          # right anchor: end of line, or a non-alnum
_S='[-_[:space:]]'              # one word-separator inside a multiword title
COMMERCIAL="${_BL}("
COMMERCIAL+="f-?zero|gradius|castlevania|top${_S}?gear|pilotwings|chrono${_S}?trigger|"
COMMERCIAL+="final${_S}?fantasy|super${_S}?metroid|zelda|donkey${_S}?kong|dkc|mega${_S}?man|"
COMMERCIAL+="secret${_S}of${_S}mana|seiken${_S}?densetsu|rudra|mario|smk|rpm${_S}?racing|"
COMMERCIAL+="star${_S}?fox|metroid|kirby|battletoads|silius|space${_S}?harrier|"
COMMERCIAL+="out${_S}?run|super${_S}?scaler|galaxy${_S}?force|after${_S}?burner|"
COMMERCIAL+="contra|axelay|street${_S}?racer|dragon${_S}?ball|but[oō]uden|"
COMMERCIAL+="air${_S}?strike${_S}?patrol|r-?type|parodius|darius|actraiser|"
# Added with the `smelter` rail (offset-per-tile). These are the shipping
# OFFSET-PER-TILE users the capability-map research named and this sprint
# consciously read the behaviour of before designing a per-column table —
# `yoshi` in particular, whose wavy-lava effect is the closest published
# precedent for what this rail draws. Reading how a stage looks is fine;
# NAMING it in a committed file is what this list refuses, and adding the
# names one worked from is how that stays true rather than merely unchecked.
COMMERCIAL+="yoshi|tetris${_S}?attack|panel${_S}de${_S}pon|aladdin|turrican|"
COMMERCIAL+="ghouls|sonic|frogger|"
COMMERCIAL+="nintendo|konami|capcom|squaresoft|enix|sega|"
COMMERCIAL+="juno-?106|linndrum|dx-?7|yamaha|roland|korg|legowelt|zophar|snesmusic"
COMMERCIAL+=")${_BR}"
COMMERCIAL_HITS=$(grep -rInEi "${EXCLUDES[@]}" "$COMMERCIAL" . | _allow_filter)
if [ -n "$COMMERCIAL_HITS" ]; then
    echo "$COMMERCIAL_HITS"
    echo "cleanroom: FAIL — commercial / company name in committed text (above)"
    FAIL=1
fi

# --- 1b. The same names ACROSS a comment WRAP ------------------------------
# A line-oriented grep is blind to a multiword name that a comment reflow broke
# in half: `; ... Secret-of` / `; Mana ...` is two clean lines and one dirty
# sentence, and the same is true of every `super metroid` / `top gear` /
# `final fantasy` in this list. That is not hypothetical — a prose sweep of
# this tree found the majority of one phrase's occurrences hiding on wrap
# boundaries. So the multiword half of the denylist is run a SECOND time over
# a NORMALISED view: each line is joined with the two that follow it, comment
# markers stripped, whitespace collapsed. A hit reports the FIRST line of the
# window, which is where a reader should start looking.
#
# Single-word names need no second pass — a wrap cannot split them — so this
# pass carries only the multiword entries, and its cost is one python pass
# over the text files rather than a second full grep.
JOIN_HITS=$(python3 - "$ALLOWLIST" <<'PYEOF' 2>/dev/null
import os, re, subprocess, sys
S = r'[-_\s]*'                     # the same separator class the line pass uses
NAMES = [S.join(w) for w in (
    ('top', 'gear'), ('chrono', 'trigger'), ('final', 'fantasy'),
    ('super', 'metroid'), ('donkey', 'kong'), ('mega', 'man'),
    ('secret', 'of', 'mana'), ('seiken', 'densetsu'), ('rpm', 'racing'),
    ('star', 'fox'), ('space', 'harrier'), ('out', 'run'),
    ('super', 'scaler'), ('galaxy', 'force'), ('after', 'burner'),
    ('street', 'racer'), ('dragon', 'ball'), ('air', 'strike', 'patrol'))]
PAT = re.compile(r'(^|[^A-Za-z0-9])(' + '|'.join(NAMES) + r')([^A-Za-z0-9]|$)', re.I)
MARK = re.compile(r'^\s*(?:[;#]+|//|\*|--|<!--)\s?')
SKIP = ('build/', '.git/', 'tools/Mesen/', '__pycache__/', '.pytest_cache/')
allow = []
try:
    for line in open(sys.argv[1], encoding='utf-8'):
        if line.startswith('#') or '\t' not in line:
            continue
        f, sub = line.rstrip('\n').split('\t', 1)
        allow.append((f.lstrip('./'), sub))
except OSError:
    pass
out = subprocess.run(['git', 'ls-files'], capture_output=True, text=True)
files = out.stdout.split() if out.returncode == 0 else []
if not files:                      # not a git tree (a scratch clone, say)
    files = [os.path.join(r, n) for r, _, ns in os.walk('.') for n in ns]
for rel in files:
    rel = rel.lstrip('./')
    if rel.startswith(SKIP) or 'cleanroom_' in rel:
        continue
    try:
        lines = open(rel, encoding='utf-8').read().split('\n')
    except (OSError, UnicodeDecodeError):
        continue
    for i in range(len(lines)):
        window = lines[i:i + 3]
        if len(window) < 2:
            break
        blob = ' '.join(MARK.sub('', w).strip() for w in window)
        blob = re.sub(r'\s+', ' ', blob)
        if not PAT.search(blob):
            continue
        if PAT.search(re.sub(r'\s+', ' ', MARK.sub('', lines[i]))):
            continue           # already caught by the line pass above
        if any(rel == af and sub in blob for af, sub in allow):
            continue
        print(f"{rel}:{i + 1}: (joined) {blob[:160]}")
PYEOF
)
if [ -n "$JOIN_HITS" ]; then
    echo "$JOIN_HITS"
    echo "cleanroom: FAIL — commercial name split across a comment wrap (above)"
    FAIL=1
fi

# --- 2. The same names INSIDE committed zips' text members -------------------
# The text greps above skip binaries, so a retail name in a zip's
# metadata.json / README slips straight through. Extract each zip's likely-text
# members and run the same denylist over them. unzip is part of the toolchain
# (tools/setup.sh); if it is absent, WARN rather than silently skip — a check
# that quietly does nothing is worse than one that is not there.
ZIPS=0
if command -v unzip >/dev/null 2>&1; then
    while IFS= read -r -d '' zip; do
        ZIPS=$((ZIPS + 1))
        while IFS= read -r member; do
            case "$member" in
                */) continue ;;
                *.json|*.txt|*.md|*.xml|*.csv|*.ini|*.cfg|*.yaml|*.yml|*README*|*LICENSE*|*.nfo)
                    hit=$(unzip -p "$zip" "$member" 2>/dev/null \
                          | grep -InEi "$COMMERCIAL" || true)
                    if [ -n "$hit" ]; then
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
else
    echo "cleanroom: WARN — unzip not found; SKIPPING in-zip name scan."
fi

# --- 3. Forbidden file classes (committed-tree scan) ------------------------
# ROMs are rebuilt on demand and never committed; MesenCore is fetched or built
# by tools/setup.sh; music rips and the fullsnes hardware reference must never
# be committed. Commercially-NAMED media is blocked by filename too, because
# the text greps above skip binaries. ('*contra*' exempts '*contract*', an
# ordinary English word that collides with a retail name.)
BADFILES=$(find . -path ./build -prune -o -path ./.git -prune -o \
    -path ./tools/Mesen -prune -o \
    \( -name '*.sfc' -o -name '*.smc' -o -name '*.rsn' -o -name '*.spc' -o \
       -name 'MesenCore.*' -o -name 'fullsnes.*' -o \
       -iname '*zophar*' -o -iname '*(EMU)*' -o \
       -iname '*f-zero*' -o -iname '*fzero*' -o -iname '*gradius*' -o \
       -iname '*castlevania*' -o -iname '*battletoads*' -o \
       \( -iname '*contra*' ! -iname '*contract*' \) -o \
       -iname '*axelay*' -o -iname '*actraiser*' -o \
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

# --- 4. Oversized files (>2 MB needs a human look; a licensing tripwire) ----
BIG=$(find . -path ./build -prune -o -path ./.git -prune -o \
    -path ./tools/Mesen -prune -o -type f -size +2M -print)
if [ -n "$BIG" ]; then
    echo "$BIG"
    echo "cleanroom: FAIL — file over 2MB committed (review, then allowlist it)"
    FAIL=1
fi

# --- Reach (printed pass or fail) -------------------------------------------
SWEPT=$(grep -rIl '' "${EXCLUDES[@]}" . 2>/dev/null | wc -l)
ALLOW_DEFINED=0
if [ -f "$ALLOWLIST" ]; then
    ALLOW_DEFINED=$(grep -cEv '^[[:space:]]*(#|$)' "$ALLOWLIST" || true)
fi
ALLOW_USED=$(wc -c < "$ALLOW_TALLY" | tr -d ' ')
echo "cleanroom: swept $SWEPT text files, $ZIPS zip(s); \
$ALLOW_USED hit(s) exempted by $ALLOW_DEFINED allowlist entr(y|ies)"

if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
echo "cleanroom: clean (name tripwire only — NOT a completeness guarantee)"
