# Lesson 2 — Your idea against the envelope

*Matches Try-it prompt 2. The task: triage a game idea into **proven / near /
new / doesn't-fit**, with a citation for every claim and an honest no where a
no is the answer. This is a reading step — nothing is built.*

## The sources, in read order

1. [`docs/capability_envelope.md`](../capability_envelope.md) — what the
   library already proves, game by game. Your bucket (a) is mostly a lookup
   here.
2. [`docs/hardware_for_your_idea.md`](../hardware_for_your_idea.md) — what the
   machine itself will and will not do, each "no" paired with the nearest
   proven alternative. Your bucket (d) starts here.
3. [`docs/01_substrate_reference.md`](../01_substrate_reference.md) — the
   budget numbers everything is argued against.
4. [`docs/09_feature_register.md`](../09_feature_register.md) — the feature
   register: per capability, **built / PARTIAL / not built**, and §5's
   what-it-would-take notes for the unbuilt ones.
5. **`game.toml` headers, as case law.** Every game's toml opens with what the
   game proves and a "NOT COMPOSED, each for a reason" block — recorded
   rulings on which features compose and why the rest were refused. When your
   idea resembles a shipped game, its header has already argued half your
   assessment. Open the two or three nearest ones and cite them.

## The four buckets, and the standard of evidence for each

- **(a) Proven** — name the game in `game/` that demonstrates the part, and
  the test that pins it. "A platformer exists" is not the claim; "landing-snap
  physics, proven by `jumper`, asserted in `tests/test_jumper.py`" is.
- **(b) Near** — existing features composed in a new way. This is *per-rail
  work* (docs/09's own vocabulary): your game's scenes, state and glue — real
  authorship, but no new engine mechanism and no new claim class.
- **(c) New engine work** — and the cost stated as **what it would claim**:
  walk the twelve claim classes (`vram`, `wram`, `dp`, `cgram`, `oam`, `hdma`,
  `rom`, `dma`, `dma_init`, `reg`, `spc`, `sram`) and name the ones the
  mechanism needs. If it needs no new claim *class*, say so — that is the
  register's track record for most "new" features, and it bounds the risk.
- **(d) Doesn't fit** — the part fights the machine, not the engine. **The
  honest no names the nearest proven alternative**: "no whole-layer runtime
  mirror — the fitting shape is 'gravity flips, the picture stays put', which
  everything in bucket (a) already serves" is an answer; a bare "no" is not.

## The honest-no discipline

- **Cite numbers, not vibes.** The pins in `allocator/substrate.toml` are
  measured: 5,952 VBlank bytes/frame, a 305,348 master-clock worst-case
  60 fps frame, ~28–37k CPU cycles of headroom. "Two full-height perspective
  cameras don't fit" is arithmetic against a measured join cost — say it that
  way, and it stops being an opinion.
- **Negative evidence is evidence.** If a capability appears nowhere — no
  feature, no claim, no test — say "nothing in this tree proves it" plainly
  rather than hedging. `docs/hardware_for_your_idea.md` makes the common nos
  citable; for the rest, a clean grep *is* the finding.
- **Don't sell.** The owner asked what fits. A doesn't-fit answer delivered
  with its nearest working alternative is more useful than an optimistic
  maybe that dies in lesson 5, where the frame budget is measured.

## Two traps in the assessment itself

- **The allocator proves collision-freedom, not sufficiency.** A feature can
  allocate cleanly beside your scene and still be unable to express what you
  need — its own code may pin the very register or behaviour you wanted to
  drive. The register rows record known cases; when in doubt, **read the
  feature's ASM** before promising it (rule of the house: to know what our
  tools do, open the tool).
- **Not everything is modelled.** docs/01 states what the substrate model does
  *not* cover — the per-scanline sprite limit (32 sprites / 34 slivers per
  line) is the sharp one. A crowded horizontal line of sprites needs a hand
  count, not a claim.

## The deliverable

Four labelled buckets. Every entry carries a citation — a game, a test, a
feature dir, a register row, or a measured pin. For (d), each entry ends with
the nearest proven alternative and the design adjustment that reaches it. Two
or three open questions back to the owner (which half of the idea leads, what
trade they prefer) close it out — recommend a default so work can continue.
