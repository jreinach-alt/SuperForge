# 08 — Feature Register & Architecture Map (spec)

> Status: LIVE — the format and rules docs/09 is generated against, and what a new feature must declare

**This file is the spec, not the artifact.** The artifact is
[`docs/09_feature_register.md`](09_feature_register.md): read this one for
*why* the register exists and what it must prove; read `09` for what it found.

**Why it exists, in one sentence:** there is a good record of what this engine
must eventually *support* and, without the register, none at all of what it
currently *supplies* — so nothing connects a demanded feature to the
declaration model that would have to express it, and that disconnect has
already hidden a blocking gap (§2).

---

## 1. The gap, precisely

Two halves exist. Nothing joins them.

**Demand** — a catalogue of rails, each with the features it composes, the hard
combinations proven on hardware, measured footprints, and scene structure. It
defines the vocabulary: BG · SPR · TXT · OBJ-HUD · M7 · M7-persp · M7-affine ·
SPLIT · STREAM · GRAD · CM · POOL · SAVE · AUD.

**Supply** — the directories under `engine/features/`, and the claim classes
`allocator/schemas.py` models: `vram` · `dp` · `wram` · `cgram` · `oam` ·
`hdma` · `dma` · `dma_init` · `rom` · `reg` · `spc` · `sram`.

Without an artifact mapping demand → supply → claim class, none of these
questions has an answer you can look up:

- Which demanded features are built, partially built, or not started?
- Which feature supplies GRAD? (Answer: `rgb_gradient`, and only it. An earlier
  draft of this spec answered "two of them, `rgb_gradient` and `sky_band`" —
  wrong, and the correction is instructive: `sky_band` declares **zero**
  `claims.hdma` and its own `feature.toml` says "Costs NO HDMA channel". It is
  a BG texture layer that a gradient happens to colour. Being adjacent in a
  rendered frame is not supplying the same demand term.)
- Does a demanded feature need a claim class that **does not exist**?
- Where does a *new* feature go, and what does it have to declare?

The fourth question is the one that keeps costing time. The rules are real and
enforced — by the build failing — but without this they live nowhere a new
author reads.

## 2. The gap is load-bearing, not theoretical

Cross-referencing the two halves for the first time surfaces a blocker:

> `split_h_irq_grad_demo` is a **proven** rail. Its whole mechanism is a
> seam-scanline IRQ that supplies the band origin, which **frees an HDMA
> channel** — 3 channels busy instead of 6 — and spends it on a per-line
> COLDATA gradient.
>
> **There is no IRQ claim class.** A composition already proven on hardware
> cannot be declared in the current model.

The scanline-IRQ class had already been recorded elsewhere as an unmodelled
taxonomy gap — but as an abstract someday item (*"nothing in microzero claims
mid-frame IRQ"*), not as *"a rail we already demand has no expressible
declaration."* The two facts sat in two documents and nobody had joined them.

**And it is not the only one.** Seeding the mapping found a *second* missing
claim class — CPU-written PPU register ownership — which was **already live in
the tree**, with two features writing PPU registers no claim covered. See
**§3.1.2**. Two missing classes found by two passes over the same join is the
argument for the join itself: neither was visible from either half alone.

**Treat this as the register's first acceptance test:** a register that does
not surface the IRQ gap on its first pass is not doing its job.

## 3. Deliverable

### 3.1 The register

One row per demanded feature. Columns:

| column | content |
|---|---|
| **feature** | the vocabulary term (BG, SPLIT, STREAM, …) |
| **supplied by** | `engine/features/*` dir(s), or **not built** |
| **claim classes needed** | from the supplying feature's `feature.toml`, or *derived* for unbuilt ones |
| **classes missing** | any needed class the allocator does not model — **the blocking column** |
| **demanded by** | the rails that need it, with the measured footprint that binds |
| **phase** | when it is scheduled |
| **status** | built · partial · not built · **blocked (missing class)** |

The live mapping is `09` §1.1/§1.2 — **verify and correct it; do not re-derive
it from a blank table.** It is a set of correspondence judgements with no
oracle (nothing fails if they are wrong), and several depend on facts learned
by hitting a build error rather than by reading the tree.

Note the shapes it must be able to express, which are already present:

- **one feature → many dirs**: the register must be able to express it, but
  **the tree may currently contain no instance.** This bullet once cited
  GRAD = `rgb_gradient` + `sky_band`; that was wrong, and the obvious
  replacements do not hold either. `bg_text` + `text_dp` + `font_rom` looks
  like three dirs supplying TXT, but `text_dp` and `font_rom` are a *companion*
  and a *blob* — supporting dependencies, not co-suppliers, and the distinction
  is exactly the one the next two bullets draw. **So treat this as a shape the
  schema must permit, and record honestly whether any row actually uses it.**
  "No instance today" is a valid, useful answer; a manufactured one is not.
- **one dir → supporting role, not a feature**: `world_rom`, `pose_rom`,
  `car_rom`, `font_rom` are ROM blobs; `text_dp` and `enter_scr` are global
  companions holding claims on behalf of shared code (§3.2).
- **demanded but absent**: the register must be able to say so — including for
  **hires (Mode 5/6) text**, which the demand vocabulary has no term for at all
  (§3.4 B3).
- **partially supplied**, which the status column must distinguish from absent.

Supporting dirs that are **not** features must be registered as such, or they
read as unaccounted-for: ROM blobs, engine infrastructure, single-word claims,
game logic. `text_dp` and `enter_scr` are **global companions holding claims on
behalf of top-level shared code** — that is the §3.2 rule, and it is the entry
most likely to be got wrong, because nothing in the tree explains it.

#### 3.1.2 The second missing claim class: CPU-written PPU register ownership

The IRQ gap (§2) was found by joining demand to supply. Seeding the mapping
found a second one, and unlike IRQ this one was **live in the tree already**,
which ranked it above IRQ for scheduling.

Nine claim classes existed at the time. Every one of them described a resource
claimed either by an HDMA channel (`hdma`), a DMA transfer (`dma`,
`dma_init`), or a memory region (`vram`/`dp`/`wram`/`cgram`/`oam`/`rom`).
**None of them described a PPU register the CPU writes directly.** So a feature
that writes a static register once at scene enter — the commonest thing an SNES
feature does — declared nothing, and the contention checker could not see it.

Two live instances, both found by reading the ROM against its declaration:

| feature | CPU-writes | declared |
|---|---|---|
| `sky_band` | `$2108` BG2SC, `$210B` BG12NBA, BG2HOFS, BG2VOFS | nothing — its only `registers` entry was `["VMDATAL","VMDATAH"]` on a `dma_init` claim |
| `rgb_gradient` | `$2130` CGWSEL, `$2131` CGADSUB | nothing — its `registers` entries were the three `COLDATA_*` planes on `hdma` claims |

`sky_band`'s `feature.toml` was explicit that it knew: *"Register ownership:
`$2108` (BG2SC), `$210B` (BG12NBA) and `$210F`/`$2110` (BG2 scroll) are written
by nothing else in the game — ppu_reset zeroes them at boot and no other feature
touches them."* That is a **correct fact asserted in a comment**, which is
precisely the shape of thing this repo exists to move into the allocator. It was
true then; nothing checked it; and the second BG feature to land would have
broken it silently.

This is the same class as `claims.dma_init` — a real hardware write that the
model had no vocabulary for, discovered by cross-checking declaration against
implementation — and the fix had the same shape.

> **This class has since SHIPPED as `claims.reg`**, with a writer-side
> ownership pass in `allocator/no_literals.py`. `09` §2.1 is the live account.
> The paragraph above is kept because it is the worked example of *how the
> register is supposed to find a missing class*, which is what this spec is
> asking for.

**Order matters: establish the mapping before building the generator.** The
spec asks for the supply half to be generated (§3.3), and a generator is the
more satisfying thing to build — but a well-engineered table of wrong
correspondences is worse than a hand-checked right one, and the generator's
shape depends on distinctions above (feature vs blob vs companion) that only
exist once the mapping is settled.

### 3.2 The architecture map

Prose, short, and it must answer *"I am adding a feature — what do I do?"*
Contents, all of which are otherwise learned by failing the build:

1. **Claim scope follows the CODE's include scope.** A feature whose `.asm` is
   included inside a scene's `.scope` declares its own scene-scoped claims
   (`sky_band`, `player_car`). A feature whose `.asm` is included at top level
   in `main.asm` — *"engine feature runtimes (shared code, global symbols
   only)"* — **cannot see a scene-scoped symbol**, so its claims must live on a
   global companion feature: `font_up` sits on `text_dp`, and `mode7_floor`'s
   two upload shapes sit on `enter_scr`. Getting this wrong is an
   undefined-symbol assembly error whose message says nothing about scope.
2. **Which claim class for which mechanism** — including the distinctions that
   had to be established: `claims.hdma` phase `active` (per-scanline register
   owner, exclusive) vs phase `vblank` (serialised NMI queue entry, shared) vs
   `claims.dma_init` phase `forced_blank` (one-shot enter-time upload, no
   exclusivity because scene_mgr masks NMI and clears HDMAEN first).
3. **What is a claim and what is not.** The claim owns the *destination* ports.
   DMAP's fixed-source bit (`$08`) is a source-side detail and is deliberately
   not declared — the reflex when a gate complains is to widen the declaration
   until it stops, and that would model a source detail as a claimed resource.
4. **The register-encoding rule**: BBAD/DMAP come from the declaration as
   emitted symbols (`ES_H_<CLAIM>_BBAD` / `_DMAP`, `ES_D_*` for dma_init).
   Hand-narrating an encoding is the same violation as hand-narrating an
   address. Two guarded exceptions exist and are documented at their sites.
5. **Init contract + test contract** per new feature.

### 3.3 Generation, not authorship

The supply half — dirs, claims, deps, scope, and the missing-class column —
**must be generated from the tree**, or it drifts the week after it is written.
Shipped as `make register` against `09` §3's `BEGIN/END GENERATED` block, with
a test asserting the committed copy matches a fresh generation (the same shape
as `make measure` checking pins).

The demand half (rails, footprints, phase) is hand-maintained, because it
encodes intent rather than fact.

### 3.4 Worked examples — two split-mode compositions, stress-tested

Both were run against the model by hand before the register existed. Between
them they produced four findings, which is the case for building it: **every
one of these is a question a designer would otherwise answer by writing code
and discovering the answer from a build failure.** They are promoted into §5
acceptance so the register is required to reproduce them.

#### A. Mode 1 HUD band on top, Mode 7 world map below

**Verdict: fits, mostly built — it is microzero's race scene**, the
`split_h_demo` rail shape.

| need | supplied by | claims |
|---|---|---|
| the band split | `split_band` | 2× `hdma` active — BGMODE (direct) + TM (indirect) |
| the M7 plane | `mode7_floor` | `vram` (M7 region), `cgram` pinned at 0, `rom` |
| the transform | `mode7_persp` | 2× `hdma` active — M7A/M7B, M7C/M7D (mode 3) |
| the HUD text | `bg_text` | `vram`, `cgram` |

**Finding A1 — "world map" is M7-affine, which was only PARTIALLY supplied.** A
world-map transform is normally static or rotating uniform affine (an RPG
overworld), not per-scanline perspective. `mode7_floor` supplies the plane —
VRAM region, palette, CHR — but at the time **no feature owned setting a static
M7A–D matrix**, so M7-affine's row was *partial*, not *built*. It is also
**cheaper in channels**: a matrix set once at scene enter needs no HDMA claim at
all, so this composition is 2 active channels rather than 4. (`m7_affine` has
since shipped and owns exactly that; `09`'s row carries the close.)

#### B. Mode 5 text box on top, Mode 1 town below

**Verdict: the shape fits and reuses the same mechanism, but it was BLOCKED on
register vocabulary, and it exposes a hole in the demand vocabulary itself.**

Mechanically identical to A: one HDMA channel writing BGMODE per band.

**Finding B1 — do not build a second splitter; generalise `split_band`.**
`split_band` already owns BGMODE, and owns it `band = "scene"` (the whole
frame — the seam lives in the table, not the band). A Mode 5 / Mode 1 split is
therefore *not a second claim*, it is the same claim with different table
values. The correct move is to parameterise `split_band`'s
then-hardcoded Mode-1-over-Mode-7 table. **This is the duplicative-path case the
register exists to prevent:** without it, an author sees a feature named for
Mode-1-over-Mode-7 and reasonably writes their own splitter, and the collision
gate will not object, because two disjoint-band BGMODE claims are physically
legal. (`split_band` has since been generalised exactly this way, with five
includer-bound symbols and no defaults.)

**Finding B2 — BLOCKED: the BG base registers were not in the vocabulary.**
Mode 5 is hires with different BG depths, so the text band and the town band
want different tilemaps and CHR bases — meaning `BGnSC` and/or `BG12NBA` must
change at the seam, which is a per-scanline write, which is an `hdma` claim. At
the time, `allocator/schemas.py` knew none of `BG1SC`/`BG2SC`/`BG3SC`/
`BG12NBA`/`BG34NBA`/`CGADD`, and `_parse_registers` raised a `SchemaError`
listing the known names. That is the designed behaviour — **loud, not silent**.
Adding them is small; knowing you need to before starting is the point.

> **Since corrected:** three of those four landed with the `claims.reg` class
> itself. Only `CGADD` is still absent, and it is the CGRAM address port, which
> `claims.cgram` already expresses. `09` §1 carries the correction — and the
> lesson is that paragraph's own: **a doc that names absent vocabulary goes
> stale the moment the vocabulary lands, and nothing gates it.**

**Finding B3 — the DEMAND vocabulary has no term for hires text.** The
vocabulary has TXT (BG-layer text) and nothing for Mode 5/6 hires text. The
demand catalogue under-represents that gap because its rails were chosen for
their *composition* shapes rather than for the BG modes they run in — no rail
in the catalogue performs a Mode 5 split at all. Composition B is therefore
genuinely new territory, and the register must be able to say so rather than
implying TXT covers it.

**Finding B4 — an unmeasured hardware assumption, which must be probed first.**
Whether `BGnSC` can be safely changed mid-frame by HDMA (switching tilemap base
at a seam) is *not established here*, and CLAUDE.md's measure-don't-estimate
rule applies. The existing split already carries a seam artifact that was
asserted rather than fixed (line 44 renders backdrop, AGENTS.md), and a change
to a **hires** mode at a seam may carry its own. **Probe before feature**, in
the shape of `vendor/probes/probe_vb2reg` — do not let a register row imply the
composition is available until the probe says the mechanism works.

## 4. Why this and not a documentation pass

Considered and rejected: a prose documentation pass. The prose here is already
good — `AGENTS.md` has "anti-patterns this project has already paid for", and
`tests/test_decl_impl_channels.py`'s docstring documents why two earlier
versions of itself were wrong. Stubs are not the problem either: 8
TODO/FIXME/stub markers across the whole tree.

Also considered and superseded: a generated *inventory* (gated sources, tool
ownership, parser count). It would have caught a census gap — `probe_vb2reg` is
gated from a **test**, not the Makefile, which is why a Makefile-only census
missed it — and that check is worth keeping as a by-product. But an inventory of
files cannot surface a **missing claim class**, which is the blocking kind of
gap. The register subsumes it.

The repo's own thesis applies: you do not document that a composition is
collision-free, you make the build prove it. Prose that is not executable has
failed here twice already — the `forced_blank` precondition was
true-but-only-in-a-comment until it became a test, and a background-agent rule
in `CLAUDE.md` was confidently wrong for two phases.

## 5. Acceptance

1. Every feature in the demand vocabulary has a row.
2. Every `engine/features/*` dir appears as a supplier, a supporting blob, or a
   global companion — **none unaccounted for**. Two dirs supplying one feature
   is legal and must be visible *if any row uses it*; "no instance in the tree
   today" is an acceptable answer and must not be papered over with a
   manufactured pair (§3.1 — the GRAD example that used to sit here was wrong).
   The same claim supplied twice is a finding.
3. **Both missing claim classes appear in the missing-class column**: the
   scanline IRQ (§2) and **CPU-written PPU register ownership** (§3.1.2). The
   second is ranked first — it was live in the tree, with `sky_band` and
   `rgb_gradient` named as instances, whereas IRQ blocks a rail not yet built.
4. **The §3.4 worked examples reproduce.** The register must, without anyone
   re-deriving them by hand:
   - show **M7-affine's status honestly** — the plane supplied, the static
     matrix accounted for (finding A1);
   - show any register name the allocator's vocabulary lacks as **blocked**
     rather than merely unbuilt (finding B2) — and keep that distinct from
     registers that **are** in the vocabulary and are therefore merely
     *unclaimed* (§3.1.2);
   - show **`split_band` as the sole active-phase owner of BGMODE**, frame-wide,
     so a second splitter reads as duplication rather than a new feature
     (finding B1);
   - carry a term for **hires (Mode 5/6) text** distinct from TXT, marked as
     vendored rather than greenfield (finding B3).

   A register that answers "can I build a Mode 5 text box over a Mode 1 town?"
   with anything other than *"the split mechanism exists and is owned by
   `split_band`; you need these register names added; and the mid-frame BGnSC
   change is unmeasured — probe it first"* has not met this criterion.
5. The supply half regenerates from the tree and a test enforces agreement.
6. The architecture map answers "where does a new feature go" without the
   author needing to assemble to find out.
7. A short section names what each *unbuilt* demanded feature would need,
   flagging any other missing claim class before it blocks a phase.

## 6. Non-goals

- Not a rewrite of the demand catalogue, which is the demand source of truth.
- Not an API reference. The register is about *placement and claims*.
