# 99 — Color-math composition: the screen/blend vocabulary

> Status: LIVE — `claims.screen` + `claims.blend` (C5), landed 2026-08-25.
> The thirteenth and fourteenth claim classes (`allocator/schemas.py`), the
> per-scene composition and refusal set (`allocator/allocate.py`,
> `compose_screen_blend`), and the writer-side consent that lets scene code
> write the composed state (the synthesized ownership claim in each scene's
> `symbol_map.json` reg union).

## 1. The problem: one blender, whole-port claims

Four write-only PPU ports program what the screen shows and how it blends:
`TM` $212C (main-screen layer enables), `TS` $212D (sub-screen layer
enables), `CGWSEL` $2130 (the blender's control), `CGADSUB` $2131 (the
blender's operation + per-layer math enables). All four are `(port, WHOLE)`
rows in `REGISTER_FOOTPRINT` — one owner per scene each — and that is
correct, permanently: they are write-only, so read-modify-write is
impossible, every writer must supply the whole byte, and a per-layer `TM_BG3`
sub-register would be a mask that lies (the single-blind-write test,
`schemas.py`'s footprint header; `COLDATA` passes that test because its
plane-select bits travel in the written data — these four fail it).

The consequence, measured on this tree before the vocabulary landed: every
background feature claims `TM` whole, and five features claim
`CGWSEL`+`CGADSUB` whole. So no two color-math users can ever compose, and a
sub-screen blend cannot be decomposed at all — one feature would have to own
`TM`, `TS`, `CGWSEL`, `CGADSUB` *and* both layers itself, which is a
monolith, not a composition.

The fix is not a finer mask — the mask would lie. It is a finer
**declaration**: features declare per-layer intent, the allocator composes
the four byte values per scene, proves the composition against the one-unit
hardware, and refuses what the silicon cannot express. Ownership moves from
the port to the thing actually contended: the layer binding and the math
enable bit.

## 2. The hardware model

Re-derived from the Mesen2 source on disk (`/tmp/Mesen2/Core/SNES/`), per
the house rule that register encodings come from the emulator source, not
from a summary. All references are to `SnesPpu.cpp` in this checkout unless
named otherwise.

| fact | where |
|---|---|
| `TM = value & $1F` main-screen layer enables; `TS` the same for sub | :2175-2183 |
| layer bit positions: BG1=0, BG2=1, BG3=2, BG4=3, OBJ=4 | `SnesPpu.h:22` (`SpriteLayerIndex = 4`); the per-layer shifts at :944-945, :977-978 |
| `CGWSEL`: b7-6 clip-to-black window mode, b5-4 prevent-math window mode, b1 addend source (1 = sub screen, 0 = fixed color), b0 direct color | :2199-2205 |
| window-mode encoding: never=0, outside=1, inside=2, always=3 | `SnesPpuTypes.h:13-19` (`ColorWindowMode`) |
| `CGADSUB`: b7 subtract, b6 halve, b5-0 per-layer math enables | :2207-2212 |
| math-enable bits: b3-0 = BG1..BG4 (`ColorMathEnabled >> layerIndex`), b4 = OBJ, b5 = backdrop (`RenderBgColor`) | :993, :962, :924 |
| OBJ pixels blend ONLY from palettes 4-7 (`_spritePalette[x] > 3`); palettes 0-3 opt out per sprite | :962 |
| the math gates the MAIN-screen pixel by its winning layer; sub-screen membership grants no enable | :993 (flags set at main-screen render) |
| ONE blender: one add/sub select, one halve, one addend source, one clip mode, one prevent mode — all global per frame | :1302-1380 (`ApplyColorMathToPixel`) |
| clip-to-black zeroes the main pixel AND disables halving for that pixel | :1307-1326 |
| addend = sub screen with an EMPTY sub pixel: hardware substitutes the FIXED COLOR and disables halving | :1354-1361 |
| mode 5/6 hi-res: math applies to BOTH buffers, each against the shifted neighbour | :1279-1293 |

Two rows are load-bearing for the refusal set. The empty-sub fallback
(:1354-1361) is why a sub-source blend with no sub-designated layer is a
declaration that lies — the blend never sees its declared source. And the
main-screen gating (:993) is why a math enable for a layer that is not on
the main screen is inert — the bit sits set and no pixel ever qualifies
through it.

## 3. The vocabulary

Two claim classes, declared in `feature.toml` like every other claim,
composed per scene like every other claim.

```toml
[[claims.screen]]          # a LAYER-to-SCREEN designation, per layer
layer = "bg2"              # bg1 | bg2 | bg3 | bg4 | obj
on    = "sub"              # main | sub | both

[[claims.blend]]           # the blender's programming
op      = "add"            # add | sub                  (CGADSUB b7: sub = 1)
half    = true             # optional, default false    (CGADSUB b6)
source  = "sub"            # sub | fixed                (CGWSEL b1: sub = 1)
math    = ["bg1", "backdrop"]  # layers gated into math (CGADSUB b5-0)
clip    = "never"          # optional: never|outside|inside|always (CGWSEL b7-6)
prevent = "never"          # optional: same domain      (CGWSEL b5-4)
```

A screen claim binds one layer to one screen; the binding has one owner per
scene. A blend claim programs the blender; its five **global** fields (`op`,
`half`, `source`, `clip`, `prevent`) describe the one blender, and its
`math` list holds per-layer enable bits, each with one owner per scene. Two
blend claims that agree on every global field compose — each gates its own
layers in.

## 4. Composition

Per scene, over the union of the scene's features and the globals (the same
union every ownership check runs over):

```
TM      = OR of layer bits where on ∈ {main, both}
TS      = OR of layer bits where on ∈ {sub, both}
CGADSUB = (op == "sub") << 7  |  half << 6  |  OR of math-layer bits
CGWSEL  = clip << 6  |  prevent << 4  |  (source == "sub") << 1
```

`CGWSEL` bit 0 (direct color) always composes 0 — a stated limit (§8).

A scene with screen claims and **no** blend claims composes
`CGWSEL = $30` / `CGADSUB = $00`: prevent-mode "always", the state
`vendor/rom/ppu_reset.inc` establishes at boot, in which the math unit is
structurally off. That off state appears in the allocation report and in
`symbol_map.json`, but **no symbol is emitted for it**: ownership is
per-half (§7), a scene with no blend claims does not own `CGWSEL`/`CGADSUB`,
and publishing `ES_SCR_<ID>_CGWSEL` for a port another feature owns would
hand scene code a value that is not this composition's to write. §6 states
the emission rule; the composed state is what the scene owns, and only that.

**The composed state is per scene, and nothing carries it across an edge.**
A scene that composes a blend programs the blender on enter; a successor
that composes no blend half and has no raw `CGWSEL`/`CGADSUB` owner writes
neither port and **inherits the previous scene's blend**. `ppu_reset.inc`
runs once, from the CPU bootstrap (`vendor/rom/init.inc`), so the boot off
state is not re-established at a transition. Carrying the off state is the
rail's obligation, discharged either way round: give the successor a blend
claim composing the off state it wants, or leave the port to a raw owner
that disarms itself at scene exit (`rgb_gradient.asm`'s `rg_disarm` is the
shape). The allocator does not refuse this — persistence across an edge can
be deliberate, a blend held through a fade — but it **warns**, per edge, in
the allocation report (§5).

Worked example — one feature designates `bg1 -> main` and `obj -> main`,
another designates `bg2 -> sub` and declares
`op = "add", half = true, source = "sub", math = ["bg1", "backdrop"]`:

```
TM      = $11    ; bg1 (bit 0) | obj (bit 4)
TS      = $02    ; bg2 (bit 1)
CGADSUB = $61    ; half (bit 6) | backdrop (bit 5) | bg1 (bit 0), add -> b7 = 0
CGWSEL  = $02    ; source = sub (bit 1), clip/prevent never, direct color 0
```

## 5. The refusal set

An infeasible composition stops the build — that is the feature. Each
refusal names the claiming features and the hardware mechanism it protects.

- **R1 — one layer, one designation.** The same `layer` designated by two
  features in one scene refuses, **even when they agree on `on`**. TM/TS
  hold one enable bit per layer, and the ownership of that bit — not its
  value — is the resource: the same rule `claims.reg` applies to whole
  ports (docs/09 §2.1). One feature designates a layer; a second feature
  that needs it on screen depends on the first.
- **R2 — one blender.** Two blend claims in one scene disagreeing on any
  global field (`op`, `half`, `source`, `clip`, `prevent`) refuse. CGADSUB
  b7 is one add/subtract select for the whole screen, b6 one halve, CGWSEL
  b1 one addend source, b7-4 one clip and one prevent mode.
- **R3 — one math enable, one owner.** The same `math` layer named by two
  blend claims refuses — R1's rule on the CGADSUB axis.
- **R4 — a sub-source blend needs a sub screen.** `source = "sub"` in a
  scene with no sub-designated layer refuses. Where the sub screen has no
  pixel, the hardware substitutes the fixed color and disables halving
  (§2), so the blend would never see its declared source — a declaration
  that lies.
- **R5 — math gates main-screen pixels.** A `math` layer (other than
  `backdrop`, which is always the main screen's floor) that is not
  main-designated in the scene refuses: the enable bit would be inert. A
  raw `TM` claim cannot satisfy this — the composition proves only what
  the vocabulary declares.
- **R6 — two vocabularies, one port.** A raw `[[claims.reg]]` on TM or TS
  in a scene carrying any screen claim — or on CGWSEL or CGADSUB in a
  scene carrying any blend claim — refuses. The composed vocabulary
  synthesizes a per-scene ownership claim over the ports it composes, so
  this arises from the ordinary register-ownership intersection, not from
  a separate lint; the message names both claimants and the migration
  (§7).
- **R7 — a blender blending nothing.** A blend claim with an empty `math`
  list is refused at parse: CGADSUB b5-0 are the only gates that admit a
  pixel into the math, so with none set the claim declares intent no pixel
  can ever express.

One worked refusal, verbatim from the build (a raw-TM feature composed
beside a screen claim):

```
ALLOCATION FAILED: REGISTER ownership contention in scene 'beach':
floor_reg (engine:floor) claims ['TM'] as a raw [[claims.reg]], but this
scene also composes the screen/blend vocabulary over the same port
(screen_blend, screen/blend <- engine:sky) — two vocabularies, one
write-only port. Every writer of a write-only register supplies the WHOLE
byte, so the raw value and the composed value cannot both hold. Move the
raw claim into the vocabulary: a TM/TS designation becomes [[claims.screen]]
(layer, on) on the feature that owns the layer; CGWSEL/CGADSUB programming
becomes [[claims.blend]]
```

Beside the refusals, **warnings** land in the allocation report — real
hardware behaviour worth knowing, or a shape that is legal and sometimes
intended, so refusing it would be its own defect. Per scene: OBJ in `math`
(only sprite palettes 4-7 participate — per-sprite opt-out is a hardware
feature the author must plan palettes around); OBJ designated `sub`
(sprites become blend source material); and a screen claim on a BG layer
whose `BGnSC`/`BGnNBA` registers another feature claims in the same scene
(the designator should usually own the layer — a split shape is
conceivable). Per **edge**: a transition out of a blending scene into one
that composes no blend half and has no raw `CGWSEL`/`CGADSUB` owner, where
the blend therefore persists (§4). Each warning is counted in the
allocator's summary line beside the refusal checks, so a run that examined
nothing reads as having examined nothing rather than as clean.

## 6. Emission

For every scene carrying at least one vocabulary claim, the scene's
generated include gains a symbol **per port the composition owns**:

```
ES_SCR_<SCENEID>_TM / _TS          where the scene carries screen claims
ES_SCR_<SCENEID>_CGWSEL / _CGADSUB where it carries blend claims
```

each with a comment naming the contributing features and fields. A half the
scene composes nothing for emits a commented placeholder line instead of a
symbol, saying so. Scene-enter code writes the composed ports from these
symbols — never a narrated value: an encoding narrated at a write site is a
second, uncheckable copy of the claim, which is the same reason
`_SC_BASE`/`_NBA` and the channel `_BBAD`/`_DMAP` symbols exist.

**Emission follows ownership, and that is the whole rule.** The alternative
— emit all four wherever anything composes — puts the allocator in exactly
the position the rule forbids: a screen-only scene would publish
`ES_SCR_<ID>_CGWSEL = $30` for a port a raw claimant owns and programs, and
where that claimant opened the port with `scene_writes` (its ordinary
shape), the writer-side gate would accept a scene write of the allocator's
value over the owner's. A green build, a blanked blend. The symbol is the
permission slip; it is issued only for what the composition owns.

The composition also lands machine-readably: the scene's entry in
`symbol_map.json` gains a `screen_blend` object — all four values, the
`registers` the composition owns, and the contributing features — so a test
can assert a ROM's rendered state against the *declared* composition
instead of re-typing the values (the transition `edges` precedent), and can
tell a composed value from an off value the scene neither owns nor
publishes. And the synthesized ownership claim (`screen_blend`) enters the
scene's `reg` union with `scene_writes` consent for exactly the ports it
composes, which is what makes a scene file's `lda #ES_SCR_<ID>_TM` /
`sta a:$212C` pass the writer-side register gate. The same writes in a scene
that composes nothing still refuse.

## 7. Coexistence and migration

Raw `TM`/`TS`/`CGWSEL`/`CGADSUB` claims remain fully legal — every existing
composition in the tree is untouched, byte-identical, and `TM`, `TS`,
`CGWSEL`, `CGADSUB` all stay in `REGISTER_FOOTPRINT`. The seam between the
two vocabularies is refereed by R6, and it is deliberately asymmetric:

- the synthesized claim owns **TM/TS** only where the scene carries screen
  claims, and **CGWSEL/CGADSUB** only where it carries blend claims;
- so a raw `CGWSEL` claim composes beside a designation-only scene (the
  direct-color escape, §8), and a raw `TM` claim composes beside a
  backdrop-only blend (a fixed-color wash over raw-designated layers).

The migration rule, when a scene wants both vocabularies on one port: move
the raw claim into the new vocabulary. A feature's `TM`/`TS` intent becomes
`[[claims.screen]]` entries on the feature that owns the layer; its
`CGWSEL`/`CGADSUB` programming becomes a `[[claims.blend]]`. The refusal
message carries this rule, so the build teaches it at the moment it matters.

## 8. Stated limits

- **Direct color composes 0.** CGWSEL b0 is out of the vocabulary — no live
  demand. A direct-color scene keeps a raw `CGWSEL` claim and declares no
  blend claims (the asymmetry in §7 is what keeps that expressible).
- **TMW/TSW are out of the vocabulary.** Window masking of the designations
  ($212E/$212F) stays raw.
- **Per-scanline designation stays raw.** An HDMA rewrite of TM per
  scanline keeps the existing shape — a `[[claims.reg]]` with
  `seed = true` beside the `claims.hdma` claim, in a scene that does not
  compose the vocabulary on that port. The vocabulary has no per-scanline
  story, and composing screen claims against an active-phase TM/TS
  transfer refuses with a message that says exactly this.
- **Mode 5/6 half-application is untouched.** In hi-res modes the hardware
  applies math to both buffers against shifted neighbours (§2, :1279-1293);
  the vocabulary composes the same four bytes and models none of that.
- **The composition proves declarations, not writes.** The emitted symbols
  and the write consent exist so scene code CAN establish the composed
  state through the gate; whether a scene actually writes them is proven
  the way everything here is proven — on the emulator, by tests that read
  the rendered output.
