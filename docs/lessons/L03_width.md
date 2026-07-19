# L03 — The 65816's one weird trick: 8/16-bit width

## The idea

The 65816 runs its accumulator and index registers in either 8-bit or 16-bit
mode, switched at runtime by two CPU flags (M and X) that code toggles with
`sep`/`rep`. Width changes what instructions *mean*: in 16-bit mode
`lda #$0140` is a 3-byte instruction; in 8-bit mode the same opcode takes a
1-byte operand. The assembler must know the width to encode each line — but
it can only track your *source file*, top to bottom (`.a8`/`.a16` annotations
tell it), while the CPU tracks the *path actually executed*. Wherever two
paths in different widths meet at one label, the assembler picks one
encoding; if the CPU arrives in the other mode, instruction decode goes out
of sync and the bytes after the label get mis-framed — an operand swallows
the next opcode, garbage executes, and the damage lands far from the cause.

This is the platform's #1 silent-corruption class, and the kit treats it as
first-class churn: [`../../EXPECTATIONS.md`](../../EXPECTATIONS.md) opens
with it, including a real diagnosed case from the kit's own history. Two
defenses ship: the `sf_*` macros assert their own width on entry (right by
construction), and a linter — `make width-check` — that walks every path and
flags contracts your annotations don't cover. Let's plant the real bug.

## See it live

From the kit root, confirm the gate is green, then plant the bug. In
`examples/move_sprite/main.asm`, the Up branch does 16-bit math; a plausible
"optimization" — Y fits in a byte, so switch that branch to 8-bit — is our
plant. Apply exactly this diff (around line 102):

```diff
     btn #BTN_UP
     beq @no_up
-    rep #$20
-    .a16
+    sep #$20
+    .a8
     lda PLAYER_Y
```

Both edited lines are *internally consistent* — the annotation matches the
`sep` — so the assembler is happy. The trap is the join: the branch-not-taken
path arrives at `@no_up` in 16-bit mode, the fall-through now arrives in
8-bit. Run the gate:

```bash
make width-check
```

Observed, verbatim:

    examples/move_sprite/main.asm:70: [multipath-label] label 'game_loop' reached from multiple width modes {(a16/i16), (a8/i16)} but has no explicit .a8/.a16/.i8/.i16 annotation within 5 lines
    examples/move_sprite/main.asm:108: [multipath-label] label '@no_up' reached from multiple width modes {(a16/i16), (a8/i16)} but has no explicit .a8/.a16/.i8/.i16 annotation within 5 lines
    width-check: FAIL

Read the second finding first: `@no_up` is the join we broke. The first is
the poison spreading — from the ambiguous join, the loop-back edge now
reaches `game_loop` in two widths too. One wrong branch, two infected labels.

Now the uncomfortable part. Build and run it anyway:

```bash
make move_sprite
```

It assembles without a single error, boots, and the sprite still moves in
all four directions (engine-verified: stepped 30 frames of Up, OAM Y went
100 to 42). The demo *survives* because every macro it calls re-asserts width
on entry — and that is precisely why this class is dangerous: nothing at
build time or in a casual play-test tells you the contract is broken. The
linter is the only voice in the room. In code that does its own arithmetic
after a join, the same shape corrupts for real:
[`../../EXPECTATIONS.md`](../../EXPECTATIONS.md)'s worked example is this
exact pattern shipping in a demo — it still booted, then every value recorded
afterward read back as garbage, and the ten-second `make width-check` run
named the guilty label.

Revert your diff (restore `rep #$20` / `.a16`) and confirm:

```bash
make width-check
```

Observed: `width-check: clean (193 files)`.

## Exercise

Re-apply the plant, then fix it *forward* instead of reverting — keep the
8-bit branch body but honor the contract at the join:

```diff
     sbc #PLAYER_SPEED
     sta PLAYER_Y
+    rep #$20                    ; restore the label's width before the join
 @no_up:
+    .a16                        ; WIDTH-RISK: every path must arrive 16-bit
     spr_clear
```

Verified outcome: `make width-check` reports clean with the 8-bit branch
still in place — the linter never wanted 16-bit everywhere, only an honest
contract at every join. (Whether 8-bit math is *correct* here — the store now
updates only `PLAYER_Y`'s low byte — is a separate question, which is why the
shipped file keeps the branch 16-bit. Revert when done.)

## What breaks if…

**…you trust the linter to catch every width bug.** It won't, and the kit
says so plainly: `width-check` catches the annotation class — mismatched
joins, dirty-high-byte `tax`/`tay`, unmarked width-toggling macros. It does
not catch a value pushed in one width and popped in another (the stack drifts
a byte per iteration), or an 8-bit add whose carry the next compare silently
discards. Both passed this kit's linter historically and cost real debugging
hours ([`../../EXPECTATIONS.md`](../../EXPECTATIONS.md), "Honesty about the
gate's edges"). The working defense is layered: stay on the macros where you
can, keep the gate green where you hand-write, and after every small step
boot the ROM and read hardware state. When a ghost appears anyway — a store
that "never happens", garbage far from any edit — run the gate *first*; it is
the ten-second move that most often ends the hunt.

Next: [L04 — DMA](L04_dma.md), the other hardware contract the macros are
quietly honoring for you.
