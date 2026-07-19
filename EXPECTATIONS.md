# What using this kit is actually like

You are deciding whether this kit is worth your troubleshooting effort. Fair.
This page is the honest answer: the bug classes you should expect on this
platform, the ten-minute path through the worst one, what is deliberately not
here yet, and how to tell our bugs from yours. Every worked example below is
a real bug from this kit's own history — the gates exist because we hit them
first. (`docs/troubleshooting.md` is the symptom-indexed companion: go there
when something is misbehaving *right now*; read this page to know what's
normal before it does.)

## The width churn — the platform's #1 silent-corruption class

The 65816 runs the accumulator and index registers in either 8-bit or 16-bit
mode, controlled by two CPU flags (M and X) that code toggles with
`sep`/`rep`. The assembler cannot see runtime control flow: ca65 tracks width
line by line down the source file, while the CPU tracks it path by path.
Wherever two paths with different widths meet at one label, the assembler
picks one encoding — and if the CPU arrives in the other mode, instruction
decode goes out of sync. An immediate operand swallows the next opcode, or a
stray `$00` byte executes as BRK (a software interrupt you never wrote). The
damage lands far from the cause, which is why the symptoms read like ghosts:

- state corrupts nowhere near any code you changed;
- a store "never happens" though the instruction is right there in the source;
- the ROM boots, then everything downstream of one branch is garbage;
- code that worked for weeks breaks after an unrelated edit (the edit added a
  new path into a shared label).

**You will hit one of these.** Everyone who writes 65816 does — we did,
repeatedly, which is why the kit ships a linter for it. If you stay on the
`sf_*` macros the front door handles width by construction; the moment you
hand-write asm between macro calls, this class is in play. Here is a real
diagnosis from our history, start to finish:

A demo's frame loop dispatched work off a compare chain — `cmp`/`bne` per
frame number, every branch ending in `bra @after_dispatch`. Two new branches
were added that stored single bytes (so they switched to 8-bit accumulator
with `sep #$20`) and jumped to the shared label like all the rest. Symptom:
the ROM still booted — the boot marker was in memory — but every value the
demo recorded afterward read back as random garbage. First suspicion, wrong:
the engine call added the same day; reverting it changed nothing. Second
move, ten seconds:

    $ make width-check
    demo.asm:84: [multipath-label] label '@after_dispatch' reached from
    multiple width modes {(a16/i16), (a8/i16)} but has no explicit
    .a8/.a16/.i8/.i16 annotation within 5 lines

That is the whole bug. The old paths arrived at `@after_dispatch` in 16-bit
mode; the new ones arrived in 8-bit. The assembler, tracking sequentially,
had encoded the `cmp #240` after the label as a 2-byte 8-bit compare; the
CPU, arriving 16-bit, consumed 3 bytes — and from there every "instruction"
was mis-framed data until a `$00` executed as BRK. The fix is one line at
each end of the width contract:

        rep #$20                ; restore the label's width before leaving
        bra @after_dispatch
        ...
    @after_dispatch:
        .a16                    ; WIDTH-RISK: every path must arrive 16-bit

That is the ten-minute path: recognize the fingerprint (garbage far from the
cause; a phantom store; boots-then-breaks), run `make width-check`, read the
finding, restore the contract it names, rebuild, rerun the template's test.
The gate flags the three shapes this class takes — multi-path labels without
a width annotation, `tax`/`tay` carrying a dirty accumulator high byte into
an index register, and width-toggling macros without a stated
`; WIDTH-RISK:` contract. Every `WIDTH-RISK` comment you see in the engine
and macros marks a contract that exists because this class bit us there.

Honesty about the gate's edges: width-check catches the annotation class,
not every width-adjacent bug. A push in one width popped in another (the
stack drifts a byte per iteration until a return address is clobbered), or
an 8-bit add whose carry the next compare silently discards — those passed
our linter too and cost us real debugging hours. The defense the templates
model is the same one we use: small steps, and an emulator boot with a
memory read after each one.

## The byte-order cousin (it isn't endianness)

The 65816 is little-endian — low byte at the lower address, consistently: in
memory, in the instruction stream, in how a 16-bit `sta` writes its two
bytes. The platform will not surprise you there. Two things *feel* endian-ish
and actually bite; both are hardware contracts, not byte-order bugs:

**Write-twice PPU registers.** Scroll registers and the Mode 7 matrix
(M7A–M7D) are 16-bit values behind 8-bit ports: you write the SAME address
twice, low byte then high byte, and an internal latch remembers which half
you are on. Real bug: a scene switch left a scroll register holding the old
scene's value, and a single-write "reset" left the latch half-advanced — the
*next* write landed as a high byte. The kit resets these with two writes on
purpose:

    stz $210D               ; BG1HOFS low  — write-twice port
    stz $210D               ; BG1HOFS high — same address, second half

Corollary: finish one register's pair before touching the next. Several of
these ports share the internal latch, so interleaving two registers' writes
scrambles both. The `sf_*` macros sequence this for you; when you write raw
registers, pair-then-move-on is the contract.

**Reading 16-bit values one byte at a time.** The controller state lands as
a 16-bit word at `$4218` (low byte) / `$4219` (high byte). A demo read
`$4219` expecting the A button there: no crash, no error — the warp just
never fired. A is bit 7 of the LOW byte; B is bit 15 of the word, up in the
high byte. Which buttons live in which half is the controller's shift order
— look it up (`engine/input_handler.asm` has the bit table; the `btn` macro
decodes it for you), don't guess halves. The fix that sticks: read the whole
word in 16-bit mode (`rep #$20` + `lda $4218`) and mask against 16-bit
constants. Same discipline for your own variables: two 8-bit reads of a
16-bit counter are safe only if nothing can update it between them — if the
NMI handler owns it, read it 16-bit wide.

## Declared gaps (what is not here yet)

- **Composed split-mode scenes are v1.1.** What ships today, all
  emulator-tested: the scanline-IRQ seam primitive (`sf_irq`), the
  `sf_split_h`/`sf_split_v` macro families, a demo rail per geometry (plain,
  color/gradient, matrix, and perspective seams), and two seamless 2-player
  rails (`split_h_2p_demo`, `split_v_fight`). What does not exist yet:
  showcase scenes that compose several PPU modes into one continuous
  scripted sequence. The pieces are here; the composition layer is not.
- **Audio ships where it is wired, not everywhere.** Two rails play sound
  today: the flagship `platformer` (music + sound effects) and the `rpg`
  (music). The other rails are silent by design; the audio subsystem itself
  (`sf_music`/`sf_sfx` over the vendored TAD driver) is macro-group-tested,
  and wiring it into a silent rail follows the flagship's pattern.
- **PAL runs frame-locked logic ~17% slower.** Templates tie game logic to
  the frame interrupt; on a 50 Hz console that means uniformly slower
  gameplay — not glitches — while music tempo holds (the sound CPU keeps its
  own region-independent timers). Test it: `SF_REGION=pal` forces PAL timing
  in the harness. `JAM.md` has the full region story.
- **The harness is Linux (including WSL).** The `.sfc` files run anywhere;
  the build-and-verify pipeline (`tools/setup.sh`, `make check`, the pytest
  suite) expects Linux. No native Windows or macOS harness.

## Emulator vs hardware

"Verified" here means: boots under Mesen2 (cycle-accurate), with power-on
RAM randomized on every boot (`SF_HW_POWERON` can widen that to PPU-latch
randomization, or force all-zeros while you debug), and a test that reads
the rendered output — VRAM, OAM, CGRAM bytes, or a screenshot — never a
proxy variable. That discipline catches the classes that historically kill
homebrew on real consoles: uninitialized reads that a zero-filling emulator
would hide, PPU writes outside VBlank, DMA misuse, frame-budget overruns.
What it cannot promise: we have not run every template on every console
revision and flashcart. The final word is still a real console — if you run
a template on one, tell us what you saw; pass or fail, that report has
value. And the rule we hold ourselves to, which we recommend: when behavior
looks like an emulator bug, it is your code (or ours) until you have
reproduced it on a second emulator (bsnes) and can name the exact hardware
mechanism.

## Your code or ours — and how to report it

Fast triage, in order:

1. `make check` on an unmodified clone. It runs every gate (clean-room,
   provenance, width, direct-page) plus the full suite. Fails → our bug or
   a setup gap; either way we want it — open an issue with the tail of the
   output.
2. Reproduce on the nearest unmodified template. The stock rail shows it →
   likely ours: open an issue with the template name, steps, and what you
   observed (a screenshot or memory read beats prose).
3. Only your changes show it → the gates are your friend, locally and in
   seconds: `make width-check` and `make zp-check` catch the two
   silent-corruption classes this platform is famous for. Then debug by
   reading hardware state (MesenRunner `read_bytes`, `take_screenshot`,
   `docs/troubleshooting.md`'s probe ladder) — not by staring at source.
4. Reporting: a reproduced bug → a GitHub issue (template, steps,
   expected/observed, emulator + commit). "Is this normal?", design
   questions, partial repros → GitHub Discussions. Real-console reports —
   pass or fail — are always welcome in either place.

The churn documented here is the platform, not a defect in it. The 65816
gives you two register widths and 8-bit ports onto a 16-bit world; the cost
is a bug class with a known fingerprint and a ten-second gate. We wrote this
page so your first bad evening is spent on your game, not on discovering any
of this the hard way.
