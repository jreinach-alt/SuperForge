# Template Readability Contract

Every game under `templates/` is a teaching artifact: a newcomer to SNES
development must be able to open `main.asm` and follow it top to bottom. This
is the measurable bar — rules are numbered so reviews cite violations
precisely (`R3 at main.asm:341`), and each ends with a **Check** a cleanup
pass is verified against, not vibed.
**Scope:** every `.asm` file a template ships (`templates/<name>/`) plus its
README (R7); engine and macro sources keep their own conventions.
**Behavior-neutral gate:** a readability pass edits comments, label names,
banners, READMEs — never behavior. Check: the rebuilt `.sfc` is byte-identical
(`md5sum` before/after); if code or data order must move, the template's tests
and `make width-check` must pass instead.

## R1 — file-top "how to read this file" header

`main.asm` opens with one banner-framed block containing, in order:
1. **What the game is** — 1–3 sentences, plain words, genre first.
2. **Controls** — a `Controls:` line covering every button the game reads.
3. **File layout** — the major section banners (R2) listed in file order.
4. **Frame loop pointer** — name the label ("`game_loop` is the
   once-per-frame heartbeat; start reading there").
5. **Build line** — `Build: make <name>` + the `LDCFG:` sentinel if non-default.

Check: all five present before the first assembler directive (`.p816`). Deep
design essays move next to the code they explain — the header is a map.

## R2 — section banners

Major sections use the three-line `; ===` banner; sub-steps use one-line
`; --- ... ---`. Major names come from this vocabulary, optionally qualified
after an em-dash (`PER-FRAME UPDATE — game scene`):

    INIT · MAIN LOOP · PER-FRAME UPDATE · INPUT · DRAW · SUBROUTINES · DATA

Check: every instruction sits under a major banner; names use the vocabulary;
DATA is last; the header's file-layout list (R1.3) matches the banners
present, in the same order.

## R3 — hardware registers explained at first use

Every raw store to a hardware register ($21xx PPU, $42xx CPU control, $43xx
DMA) is commented at its FIRST use in each file with (a) the register's
mnemonic and plain-words name, (b) why it is written now with this value —
`sta $2115  ; VMAIN (VRAM port mode): advance 1 word per high-byte write`.
Later stores may be terse (mnemonic + short note) but never bare. Stores
inside `sf_*` macros are exempt — the macro name is the explanation.
Check: for each unique $21xx/$42xx/$43xx address in a file, the first
`sta`/`stz`/`stx` targeting it carries a same-line or immediately-preceding
comment naming the register and the why.

## R4 — no internal-process jargon

Shipped comments explain the code to a newcomer — never the project's history
to a teammate. Banned: sprint/step tags ("S3", "GAP-2"), phase numbers,
audit/review/PR references, iteration markers ("v2", "NEW:"), owner/agent
references. When history encodes a real constraint, rewrite it as the hardware
or design reason it stands for ("BG2's DMA machinery transports the level's
page 1 — the sky must live elsewhere").
Check: `grep -nE '\bS[0-9]\b|GAP-[0-9]|[Pp]hase [0-9]|\bv[0-9]\b|\bsprint\b|\baudit\b|PR #'`
returns zero hits on the template's files (a rare plain-English collision
stands only if the review agrees it reads naturally to an outsider).

## R5 — naming

- Constants: `SCREAMING_SNAKE` equates, each with a same-line comment giving
  meaning and unit (`SPEED_CAP = $0140  ; top speed, 8.8 fixed = 1.25 px/frame`).
- Routines: `lower_snake_case` labels named for what they do (`enemy_init`).
- Branch/loop targets inside a routine: ca65 cheap locals (`@pal_loop`), named
  for what they iterate or decide — never numbered (`loop1`, `@l2`).
- No magic numbers: a raw operand that isn't a register store (R3) or a
  self-evident count gets a named equate or a deriving comment.

Check: no numbered labels; routine-internal targets are `@` locals; every
equate line carries a comment.

## R6 — width-contract comments stay, in two languages

`; WIDTH-RISK:` markers, `; WIDTH-LINT: ok — ...` overrides, and
`.a8/.a16/.i8/.i16` annotations are load-bearing (the width linter reads
them); never delete or reword their contract half. Each WIDTH-RISK marker also
carries one plain-English sentence ("this label is reached while the CPU reads
8-bit values; the annotation keeps assembler and CPU in sync"), and the file's
first width annotation gets a one-line explainer of the 8/16-bit mechanic.
Check: every `WIDTH-RISK` comment contains a sentence free of register/flag
notation; `make width-check` still passes; no marker removed.

## R7 — every showcase template ships a README.md

`templates/<name>/README.md` with exactly four sections: **What it is** (1–3
sentences + a controls table) · **What it teaches** (the hardware topics and
kit features demonstrated, linking the `lib/macros/` groups and guides it
exercises) · **Three things to tweak** (the 3 most obvious knobs: named
constant or label, where it is, what visibly changes — real symbols only) ·
**How it's verified** (`make <name>`, `tests/test_<name>.py`, the run one-liner).
Check: file exists; four sections present; every symbol and path it names
exists in the tree.

## R8 — worked example

BEFORE (realistic density — unexplained ports, jargon, unscoped label):

        ; --- S4 pal upload (per S2 spec; see GAP-7) ---
        sep #$20
        .a8
        stz $2121
        ldx #$0000
    ploop:
        .a8
        lda f:dpal, x
        sta $2122
        inx
        cpx #32
        bne ploop

AFTER (same bytes, per this contract):

        ; --- Load the dungeon palette into CGRAM, the PPU's color memory:
        ;     set the start index once, then stream bytes (2 per color).
        ;     Safe now — the screen is force-blanked, so the PPU isn't
        ;     reading colors mid-frame. ---
        sep #$20
        .a8                     ; 8-bit accumulator: these ports take bytes
        stz $2121               ; CGADD (CGRAM address): start at color 0
        ldx #$0000
    @pal_loop:
        .a8                     ; branch target: re-assert CPU width (R6)
        lda f:dungeon_pal, x
        sta $2122               ; CGDATA (CGRAM data): write; index auto-advances
        inx
        cpx #32                 ; 16 colors x 2 bytes each
        bne @pal_loop
