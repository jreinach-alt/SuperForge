# 95 — Region support: the design

> Status: DESIGN. It answers [`docs/94`](94_region_support_spec.md) §5 and costs
> the tiers; it implements nothing. Nothing in `engine/`, `game/`, `vendor/rom/`
> or any existing test was changed. Two spikes were built and both were
> reverted; §12 says what they were and what they showed.
>
> `docs/94` is the source of record for the requirement; this file is the
> source of record for how to meet it, and for the two places the requirement
> as written cannot be met.

## 0. The four things to read first

**One.** *The PAL border is not observable in this harness, and no amount of
care will make it so.* Mesen hands back a 256×239 buffer for both regions and
crops the television's visible field out of the picture entirely. What IS
observable, exactly and from rendered pixels, is the **PPU's active line
count** — and that is region-independent. R1's criterion has to be restated
against it (§1.4). An unobservable criterion is how a whole tier ships broken.

**Two.** *Overscan is not free on NTSC, and the number is large.* Measured:
usable VBlank GP-DMA falls from **5,952 B to 3,520 B, −40.9%**, because
enabling overscan moves the VBlank start from line 225 to line 240 and NTSC
only has 262 lines to spend. On PAL it costs nothing measurable (the 8 KB probe
saturates either way). This is an independent, arithmetic reason the overscan
bit must be **PAL-only**, on top of the §4.1 reason.

**Three.** *Most per-scanline structures need no work at all, and the ones that
do are a trap.* A latched PPU register whose HDMA table runs out simply **holds
its last value** — which is exactly what a tail entry would write. Measured:
extending `rc_grad`'s 224-entry COLDATA table to 239 with a hold tail rendered
**pixel-identical** to the unextended table, on both a 224-line and a 239-line
display. What breaks is the **Mode 7 matrix** (a held matrix freezes the floor
— measured on two rails) and any generator that **rescales its curve** over the
new line count instead of continuing it (measured: the naive one-constant
extension moved **15,581 NTSC pixels**).

**Four.** *6-ticks-per-5-frames does not fit, and the near-coincidence is what
misleads.* On the tightest rail PAL returns **+14.8% to +17.4%** of usable
per-frame work, not the +19.1% the master-clock arithmetic suggests and not the
**+20%** the scheme demands — the difference is fixed NMI and sync overhead
that does not shrink with the frame. And the extra tick arrives in a **lump**:
two of the shipped ticks cost 515,264 mc against a 425,568 mc PAL frame. That
was measured directly, not computed (§4.3).

---

## 1. §5.1 — How is a PAL border observed at all?

### 1.1 It is not. The instrument does not exist and cannot be built here.

`docs/93` reported 256×239 for both regions and stopped there. Reading the
implementing code says why, and it is structural rather than incidental
(`/tmp/Mesen2/Core/SNES/SnesPpu.cpp`):

```cpp
void SnesPpu::SendFrame() {
    uint16_t height = _useHighResOutput ? 478 : 239;      // :1503
    if(!_overscanFrame) {
        int top = 7, bottom = 8;                          // :1508-1510
        memset(_currentBuffer, 0, width * top * ...);
        memset(_currentBuffer + width*(height-bottom), 0, width*bottom * ...);
    }
```
```cpp
void SnesPpu::ApplyHiResMode() {
    // "When overscan mode is off, center the 224-line picture in the center
    //  of the 239-line output buffer"
    uint16_t scanline = _overscanFrame ? (_scanline - 1) : (_scanline + 6);  // :1431-2
```

Neither line consults the console region. The buffer is 239 rows in both
regions; the picture is centred in it when the active area is 224 lines and
fills it when the active area is 239. **The television's visible field — 224
picture lines inside a 288-line PAL field against 224 inside a ~240-line NTSC
one — is cropped out before the harness ever sees a pixel.**

Measured, to be sure the source reading is not a story about the source. Same
ROM, same drive, both regions, `microzero`:

| build | region | picture rows | PNG sha |
|---|---|---|---|
| stock | ntsc | 7..230 | `83818b870988cfec` |
| stock | pal | 7..230 | `83818b870988cfec` |
| overscan spike | ntsc | 0..238 | `b6b4a1ebc39fe446` |
| overscan spike | pal | 0..238 | `b6b4a1ebc39fe446` |

The region moves nothing. The overscan bit moves everything.

### 1.2 What IS observable, and it is rendered output, not a proxy

Two independent witnesses, both read off the PNG:

* **the extent witness** — a 224-line active area lands on rows 7..230, with
  rows 0..6 and 231..238 forced black by `SendFrame`; a 239-line one lands on
  rows 0..238. Sufficient, but defeated by a rail whose top and bottom rows are
  genuinely black (`brawler`'s overscan capture: rows 224..238 came back solid
  black, §2.2).
* **the offset witness** — the *same content* sits exactly **7 rows higher**
  when the active area is 239 lines. Colour-independent, and it is the one that
  discharges the "did the taller frame move the shorter one?" question directly.
  Measured on `racer`: the 239-line capture is the 224-line capture shifted up
  7 rows over **all 224 picture rows, 0 mismatches**; the negative control (a
  different rail) reports 224 of 224 rows differing.

Both are shipped as `tools/active_lines.py` (report-only; §11).

### 1.3 Region liveness stays where `docs/93` put it

The knob is still provable — `mc_per_frame` reads **357,366 NTSC / 425,566
PAL**, reproduced by the new tool on `racer` — and the *console's own* region
flag is now measured in-ROM rather than read out of Mesen's source:

| `SF_REGION` | `$213F` as read by the ROM | bit 4 |
|---|---|---|
| `ntsc` | `$03` | clear |
| `pal` | `$13` | **set** |
| unset (header `$01`) | `$03` | clear |

Spike: seven bytes at `vendor/rom/ppu_reset.inc`'s SETINI site replaced with
`lda a:$213F` / `sta f:$7EF000` in a copy of `microzero.sfc`, read back from
WRAM after 60 frames. **R0's detection primitive works, today, and its
acceptance criterion is dischargeable with a seven-byte read.** (PPU version
reads 3 in both regions; bit 7 is the odd-frame flag, so the mask is `#$10`,
not a compare.)

### 1.4 R1's criterion, restated against something observable

> **R1′.** Under `SF_REGION=pal` a rail renders a **239-line active area**, and
> under `SF_REGION=ntsc` the same rail renders a 224-line one whose picture is
> **pixel-identical to its pre-change picture**. Both halves are read off
> captured frames:
>
> 1. **the taller frame is taller** — the PAL capture's picture occupies PNG
>    rows 0..238 (`tools/active_lines.py <rom>`; verdict `OVERSCAN`);
> 2. **the taller frame did not MOVE the shorter one** — the PAL capture equals
>    the NTSC capture shifted up 7 rows over all 224 picture rows
>    (`tools/active_lines.py --shift ntsc.png pal.png`; `mismatched_rows: 0`);
> 3. **the 15 new lines are authored, not held** — for each rail, its own
>    predictor names what rows 224..238 should show, and none of them may be a
>    byte-repeat of row 223 unless the predictor says so;
> 4. **NTSC did not move** — the rail's NTSC capture is pixel-identical to the
>    capture taken before the change.
>
> The clause `docs/94` R1 actually wrote — "a PAL frame shows no top/bottom
> border that an NTSC frame does not" — **is not dischargeable in this
> harness and should be struck.** What it is *about* (a PAL television showing
> 224 lines inside a 288-line field) is real, and it is settled by the four
> checks above plus the hardware note in §10.

---

## 2. §5.2 — What does enabling overscan cost, per rail?

### 2.1 It costs NTSC 40.9% of its VBlank DMA budget

`tests/test_measure_vblank.py`'s probe and protocol, region-parameterised, with
its NTSC sanity bound removed and the ROM path made a parameter so a
SETINI-patched spike can be fed in:

| | overscan OFF | overscan ON |
|---|---|---|
| **NTSC** | **5,952 B** — reproduces `substrate.toml`'s pin exactly | **3,520 B** (−40.9%) |
| **PAL** | ≥ 8,192 B (probe saturates) | ≥ 8,192 B (probe saturates) |

The mechanism is not subtle: `_vblankStartScanline = _state.OverscanMode ? 240
: 225` (`SnesPpu.cpp:559`), so overscan spends 15 of NTSC's 38 VBlank lines and
15 of PAL's 88. On the same arithmetic `tests/test_measure_vblank.py:120` uses (total lines
minus active lines, x 1364 / 8), NTSC's theoretical ceiling drops from **6,479 B
to 3,921 B** and PAL's from ~15,004 B to **~12,447 B** — still over twice NTSC's
non-overscan figure.

**Consequence for the design.** `allocator/substrate.toml`'s
`vblank_usable_bytes = 5952` is a pinned budget the allocator solves against.
Enabling overscan on NTSC would require re-pinning it downward by 41% and
re-checking every rail's VBlank demand against the new pin — and `arm_cost_bytes
= 128` per additional queued transfer means a rail queuing OAM + stream rows +
HUD loses more than the headline. **Overscan must be gated on the region flag.**
That is now two independent arguments for the same gate, and the second one
does not depend on anyone's opinion about §4.1.

### 2.2 Without extending anything, the 15 new lines are wrong

Three rails, overscan spiked on, nothing else changed, NTSC drive:

| rail | rows 0..223 vs the 224-line picture | rows 224..238 |
|---|---|---|
| `brawler` | identical | **solid black** — the BG has no content there |
| `racer` | identical | 224..234 a **frozen repeat** of the last Mode 7 scanline; 235..238 a flat held colour |
| `split_h_2p_demo` | identical | **an exact frozen repeat**, all 15 rows the same two colours |

Two things fall out of that table and they point opposite ways.

**The good half.** *Rows 0..223 are identical in all three cases.* Lengthening
the active area does not perturb the lines that were already there. That is the
property R1′ clause 2 checks, and it holds on every rail measured.

**The bad half.** *A held register is not authored content.* The Mode 7 matrix
is the loud case: when the HDMA table runs out the M7A–M7D registers keep their
last values, so the floor's perspective stops converging and the last scanline's
projection is stamped 15 times. Both Mode 7 rails show exactly that.

### 2.3 The classification that makes R1 affordable: HOLD vs CONTINUE

The key measurement of this pass. `rc_grad`'s COLDATA wash was extended from
224 to 239 entries **with a tail that holds the last value**, the rail rebuilt,
and the render compared to the stock 224-entry build:

| display | stock (224-entry table) vs spike (239-entry, hold tail) |
|---|---|
| 224 lines | **0 pixels differ** |
| 239 lines | **0 pixels differ** |

Both zeros matter, and they are the same fact seen twice:

* On a **224-line** display the extra entries are never fetched. HDMA
  re-initialises every frame and the frame ends before their cumulative line
  index is reached — the property `split_band.asm:84` already records from its
  own audit ("Summing to 224 parks it past the frame"). **An over-length table
  is inert on the shorter display**, which is what lets one table serve both
  regions.
* On a **239-line** display, an *exhausted* table and a *hold-tail* entry
  produce the same picture, because a latched PPU register holds its last value
  either way.

So the per-scanline structures split into two classes, and only one of them is
work:

| class | what the last value means | R1 cost |
|---|---|---|
| **HOLD** — COLDATA, BGnHOFS/VOFS, BGMODE, TM/TS, CGWSEL/CGADSUB, window edges | "keep doing this" is a valid continuation | **none.** Already correct under overscan |
| **CONTINUE** — M7A/M7B/M7C/M7D, and any ramp whose last value is not the right value for the next line | "keep doing this" is visibly wrong | real work: extend the table by continuation |

`docs/93` §4 said "no per-scanline table under-covers" and was right *while
overscan is off*. Turn it on and every 224-entry table under-covers by 15 lines
— but **only the CONTINUE class shows it.**

### 2.4 The trap: extending is a re-authoring, not a length change

The naive extension of `rc_grad` — change `RCG_LINES` 224→239 and
`tools/gen_racer_assets.py`'s `TOTAL_LINES` 224→239, exactly the one-constant
edit the work looks like — **moved 15,581 pixels in rows 56..136 of the NTSC
frame.** Not the new rows: the *old* ones.

The cause is one line: `floor = TOTAL_LINES - SEAM`, and the fog term is
`(floor-1-i)**FOG_FALLOFF / (floor-1)**FOG_FALLOFF`. The curve is parameterised
on the total, so extending the total **rescales the whole band**. Anchoring the
curve on 224 and appending a hold tail restored byte-identity (the 0/0 table in
§2.3).

**The same trap is structural in the Mode 7 pose generator, where it would be
much harder to see.** `tools/gen_pose_tables.py:47-50`:

```python
k0 = sn * (L - 1) / (sf - sn)
K  = sf * k0
scales = [round(K / (k + k0)) for k in range(L)]
assert scales[0] == sf and scales[-1] == sn
```

The hyperbola's two parameters are **solved from L** so that the far scale
lands on line 0 and the near scale on line L−1. Running `--lines 195` instead
of `--lines 180` therefore spreads the *same* near/far scales over 15 more
lines and changes every intermediate scale — a different floor, on NTSC, from a
Makefile argument. The correct change keeps `k0`/`K` solved on the NTSC L and
evaluates `K/(k+k0)` for `k in range(L_pal)`, continuing the curve past the
old near scale.

> **The R1 rule, stated for an implementer:** *anchor on 224 and append; never
> re-solve on 239.* Every generator that takes a line count must be read for
> whether the count is a **length** or a **parameter**. Two of the three read so
> far — `gen_racer_assets.py` and `gen_pose_tables.py` — take it as a parameter.

### 2.5 32-tall sprite parking is arithmetically impossible at 239 lines

OAM Y wraps mod 256. Parking a sprite of height *h* below the display needs
both:

* `y + h <= 256` — or it wraps back onto the top rows;
* `y >= active_lines` — or it is inside the display.

At 224 lines and *h*=32 the window is `224 <= y <= 224`: exactly one value,
which is why `brawler_obj.asm:77` reads `BR_PARK_Y = 224`. At **239** lines the
window is `239 <= y <= 224`: **empty.** There is no valid park Y for a 32-tall
sprite.

Worse, the guard does not fire. `brawler_obj.asm:83` asserts
`BR_PARK_Y >= 224`, which stays true while the sprite becomes visible;
`split_v_obj.asm:905` carries the identical assert over
`SV_PARK_Y32 = 224` (`game/split_v_fight/split_v.inc:136`). Those are the
tree's only two 32-tall parks, and this is a silent-corruption-class defect
that an overscan flip would introduce into both rails with a clean build.

Three escape hatches, all cheap, none free:

1. **clear the size bit before parking** — a 16-tall sprite parks at 240 with
   16 rows of margin. This is already what `split_v_obj.asm:894-902` does for
   the small half of its pair, and it is the least invasive fix;
2. **park on the X axis** — OAM X is 9-bit and 256..511 reads as −256..−1, so
   `X = 512 - h` is off the left edge at any height and any display length. One
   more claim byte per parked slot (the X9 bit) and no Y arithmetic at all;
3. **make the assert region-aware** — `.assert PARK_Y >= ES_ACTIVE_LINES`,
   which turns the silent case into a build failure. **Do this one regardless
   of which of the other two is chosen**; it is three characters and it is the
   difference between a refused build and a debris band nobody sees in review.

The **17** other park sites — twelve `*_PARK_Y` constants under
`engine/features/`, four in `game/*/*.inc`, and `oam_sprites.asm:19`'s
`oam_park_all` — all use 240/`$F0` and are safe at ≤16-tall. They need only the
region-aware assert.

### 2.6 The enumeration: what is a constant, what is generated, what is derived

`224` appears in **27 engine `.asm`/`.inc` files** and **27 `tools/*.py`
files**. Not all are per-scanline structures — `window_iris.asm:104`'s 224 is
COLDATA's plane-select bits and `shmup_obj.asm:195`'s is a sprite X clamp — so
the list below is the read-through, by sizing mechanism.

**Constants (a named `*_LINES` symbol the ASM owns).** Change the symbol; the
tables that derive from it follow.

| symbol | file | value | class |
|---|---|---|---|
| `RCG_LINES` | `rc_grad/rc_grad.asm:46` | 224 | HOLD (COLDATA) |
| `GRAD_LINES` | `rgb_gradient/rgb_gradient.asm:25` | 224 | HOLD (COLDATA) |
| `IRIS_LINES` | `window_iris/window_iris.asm:27` | 224 | HOLD (window edges) — but the table is one entry **per row**, so the WRAM claim grows |
| `SHM_LINES` | `shm_floor/shm_floor.asm:32` | 224 | CONTINUE (Mode 7) |
| `SIT_LINES` | `sit_cam/sit_cam.asm:49` | 224 | CONTINUE |
| `SHG_LINES` | `shg_cam/shg_cam.asm:55` | 224 | CONTINUE |
| `SHP_LINES` | `shp_cam/shp_cam.asm:58` | 224 | CONTINUE |
| `SH2_LINES` | `sh2_cam/sh2_cam.asm:75` | 224 | CONTINUE |
| `SHG_GR_TOTAL` | `shg_grad/shg_grad.asm:53` | 2 × 112 | HOLD |
| `M7F_BAND_BOT` | `m7f_cam/m7f_cam.asm:76` | 224 | CONTINUE |
| `MET_GLOW_LINES × BANDS` | `met_glow/met_glow.asm:119` | 8 × 28 = 224 | HOLD |

**Derived (an expression over 224).** These are the ones a grep for `224`
finds but a grep for `_LINES` does not.

| site | expression | note |
|---|---|---|
| `mode7_persp.asm:17` | `PERSP_LINES = 224 - HUD_LINES` | and `BAND_TAIL = PERSP_LINES - 127`; at 239 the tail is 68, still ≤ 127 |
| `m7_barrel.asm:43` | `MB_LINES = 224 - MB_SEAM` | the `.assert` at :41 bounds `MB_SEAM` against 224 |
| `shg_cam.asm:410`, `shp_cam.asm:256`, `sh2_cam.asm:573` | `VOFS = posy - 224` | the band's own bottom line — moves to 239 |
| `m7_affine.asm:77` | `sbc #112` — "half of 224" | the horizon pivot |
| `room_logic.asm:17` | `RM_HI_Y = 224 - 8 - 16` | a **gameplay** bound, not a raster one: at 239 the room floor moves, which is a design decision, not a port |
| `pfs_logic.asm:28` | `world_h - 224` | same class |
| `brawler_obj.asm:77`, `split_v_obj.asm:905` | park Y | §2.5 |

**Generated (a Python tool emits the bytes).** These carry the §2.4 trap.

| tool | knob | length or parameter? |
|---|---|---|
| `tools/gen_pose_tables.py` | `--lines` (Makefile passes 180 and 184) | **parameter** — re-solves the hyperbola. Must be fixed to continue |
| `tools/gen_racer_assets.py` | `TOTAL_LINES = 224` | **parameter** — measured to move 15,581 px |
| `tools/gen_gradient.py`, `gen_m7f_gradient.py`, `gen_m7f_factors.py` | 224 | unread; assume parameter until read |
| `tools/gen_split_h_persp_assets.py`, `gen_railshooter_assets.py` | 224 | unread; same |

**Declared (the allocator already knows).** 35 claims say `band = "scene"` and
resolve to `(0, visible_lines)`; 8 say `[112, 224]` and 4 say `[0, 112]`. The
12 explicit ones are the only band literals in the tree, and only the eight
`[112, 224]` need editing. §3.

**Claim sizes that grow.** 19 feature claims are exact multiples of 224; two
are verified as per-scanline by reading them — `rc_rom/sky_keys` (5,376 = 8
keyframes × 3 planes × 224 → 5,736, **+360 B**) and `rgb_gradient/grad_tabs`
(672 = 3 × 224 → 717, **+45 B**). The Mode 7 pose blobs are the happy surprise:
`gen_pose_tables.py` pads every pose to a **1,024 B stride** and `L*4 ≤ STRIDE`
holds at L=195 (780 ≤ 1,024), so **the largest per-scanline structure in the
kit costs zero extra ROM to extend.** The `sh2_rom`/`shp_rom` band-local blobs
(28,672 B = 64 poses × 112 lines × 4 B) do grow — a 239-line frame makes the
bottom band 127 lines, which is *exactly* the 7-bit repeat-count ceiling, so
they fit in one entry and cost +13.4% each.

ROM headroom for that: measured occupancy is **≤82.7% on `microzero` and
≤61.7% on `split_h_2p_demo`** (trailing-fill measurement, so an upper bound on
free space and a lower bound on the answer "is there room"). The 512 KB images
are 512 KB because the linker config says so, not because they are full.

---

## 3. §5.3 — Can scanline coverage become a declared claim?

**Yes — and half of it already is.** This was the question most worth asking
and the answer is better than the spec assumes.

### 3.1 What exists today

`HdmaClaim` already carries a **band** (`allocator/schemas.py:588-596`):

```python
class HdmaClaim:
    name: str
    channels: int
    registers: tuple[str, ...]
    band: tuple[int, int]     # [start_line, end_line) — "scene" = whole frame
    phase: str                # active | vblank
```

parsed by `_parse_band` (`schemas.py:894-900`), where `"scene"` resolves
against the substrate:

```python
def _parse_band(v, visible_lines: int, where: str) -> tuple[int, int]:
    if v == "scene":
        return (0, visible_lines)
```

and `visible_lines` is a single substrate constant (`substrate.toml:92`,
`schemas.py:99/163`) whose comment already anticipates this work: `visible_lines
= 224 # 224-line mode (239 in overscan)`.

The band is **load-bearing for composition**: the collision unit is
`(register, band, phase, channel)`, and `allocate.py:812-902` uses band overlap
both to refuse two writers on one scanline (`:829-836`) and to make a channel
**reusable across disjoint bands** (`:866-902`). `:1169-1196` re-checks it after
assignment.

### 3.2 What is missing — and it is exactly the gap the kit's thesis is about

The band is **emitted as a comment** (`allocate.py:1320-1324`):

```python
lines += [f"{s}_CH = {ca.channel}"
          f"    ; {','.join(ca.registers)} band "
          f"{ca.band[0]}-{ca.band[1]} phase {ca.phase}", ...]
```

so the ASM carries a **second, unchecked copy** of the same fact — `RCG_LINES =
224`, `GRAD_LINES = 224`, `SH2_LINES = 224` and eight more (§2.6). That is
precisely the drift the kit's own `_channel_lines` docstring says emitting
exists to prevent ("an encoding narrated at the write site is a second,
uncheckable copy of the claim"). The band is the one field that did not get the
treatment `_BBAD` and `_DMAP` got.

### 3.3 Measured: widening the frame model is free today

Set `visible_lines = 239` in `allocator/substrate.toml` and re-run the
allocator over every game:

* **37 of 37 games still allocate. Zero new refusals.** (A widened `"scene"`
  band can only add overlap, and no band in the tree *starts* at ≥224, so no
  pair becomes newly contended. Now measured rather than argued.)
* The emitted `.inc` files differ **only inside comments** — every symbol value
  is identical.
* **`microzero.sfc` rebuilds to its pinned md5 `e45ddeabac4218cd71709da7b9fcc849`.**

So the frame-model widening is **ROM-neutral**, and the §4.2 pin survives it
untouched. That is a real result: the declaration half of R1 can land before any
ASM changes and before any decision about overscan, with a null diff in every
binary.

### 3.4 The design: three steps, sized

**Step A — emit the band (½ day).** Add to `_channel_lines`, beside `_CH`,
`_BBAD`, `_DMAP`:

```
ES_H_<NAME>_BAND_TOP   = <band[0]>
ES_H_<NAME>_BAND_LINES = <band[1] - band[0]>
```

Then replace the eleven hand-written line-count constants with the emitted
symbol for the claim that owns the table. This is the kit's own established
move and it makes `allocator/no_literals.py` the enforcement: after the switch,
a `224` at a table-sizing site is a literal the gate can see.

*Cost:* ~10 lines in `allocate.py`, 11 one-line ASM edits, one `.assert` per
feature tying the table's length to the emitted band. *NTSC identity:* the
emitted values are unchanged (224 today), so **every ROM is byte-identical** —
provable by rebuilding all 37 rails and diffing.

**Step B — make `visible_lines` the frame model's, not NTSC's (½ day).** Two
sub-options, and the choice is the whole architecture:

* **B1 — one number, sized to the taller region.** `visible_lines = 239`.
  Every `"scene"` band covers 239 lines; every table is built for 239; NTSC
  consumes the first 224 and the rest are inert (§2.3, measured). **One ROM,
  one build, one md5, both regions.**
* **B2 — a `[frame.pal]` table and an allocator `--region` flag.** Two ROMs.
  NTSC's image is literally byte-identical because nothing on its path changes.

**B1 is the recommendation.** B2 buys literal `.sfc` identity — which §4.1 asks
for and which R0 already makes impossible (§9.1) — at the price of doubling
every build, every gate, every screenshot oracle and every md5 pin, and of
handing the jam two artifacts when it wants one. B1 gets the property that
actually matters (the NTSC *picture* does not move) and gets it as a
*measurement*, per rail, per frame, using the instrument in §1.4.

**Step C — the check that makes it a claim rather than a comment (1 day).** A
band is a promise about lines covered; nothing checks that the feature's table
actually covers them. Add, in the shape of `make rom-unbacked`:

* every HDMA claim's owning feature must carry a `.assert` that its table's
  cumulative line count equals `ES_H_<NAME>_BAND_LINES` — the assert lives in
  the ASM, so it is checked by the assembler on every build, and the value
  comes from the declaration, so the two cannot disagree;
* every claim whose band is `"scene"` is a **full-frame** claim and must
  additionally declare its **continuation class**:

```toml
[[claims.hdma]]
name = "rcgr"
band = "scene"
continuation = "hold"      # the register HOLDS its last value legally
# continuation = "table"   # the table must cover every declared line
```

That one keyword is the whole §2.3 finding, made declarable. `hold` says "a
short table is correct here"; `table` says "under-coverage is a defect" and the
`.assert` above becomes mandatory. A new feature must state which it is, and the
allocator refuses a `"scene"`-band HDMA claim that states neither — which is
exactly the shape of the kit's other gates.

### 3.5 What this does and does not buy

**It buys:** the line count stops being 27 files' private opinion and becomes
one emitted number; the under-coverage class becomes a build failure instead of
a picture nobody looks at below row 224; a new feature has to say which class it
is in, in the file a reviewer opens.

**It does not buy:** the *content* of the extra lines. `continuation = "table"`
proves 239 entries exist; it cannot prove they are the right 239. The §2.4
rescale defect passes every check in step C — the table was the declared length
and every entry was authored — and it is the defect that actually moved 15,581
NTSC pixels. **That is caught by R1′ clause 4 (a per-rail NTSC pixel diff), not
by the allocator**, and no plausible extension of the allocator catches it. Say
so in the brief so nobody trusts the wrong gate.

**Honest verdict:** yes, and it is about 2 days, and it is worth doing for step
A + B alone even if R1 never ships — because step A + B is ROM-neutral,
measured, and removes a duplicated constant from eleven files.

---

## 4. §5.4 — Is 6-logic-ticks-per-5-frames viable?

### 4.1 The rail

`split_h_2p_demo` at its shipped `SWM_N = 24`. It is the tightest rail in the
tree by its own measurement (`tools/measure_sh2_swarm.py`: the tick is 76.6% of
a frame at 24 and 102% at 32) and the only one with an **in-situ cadence gate**
with a proven non-vacuity direction — `tests/test_split_h_2p_sprites.py`
asserts the loop beat and the NMI frame count advance +1/+1, and a companion
test pokes the count past the cliff and requires the gate to fail. `make
measure` pins the reference-scene budgets; this rail is where a real
composition sits closest to its ceiling.

The instrument is that rail's own: breakpoints on the tick's callees for the
work, and `loop_periods` — one breakpoint on the tick's entry, the delta
between consecutive hits — for whether it fits. `sm_frame_sync` parks the loop
on the NMI, so **a loop that fits reads exactly one frame and one that does not
reads two.** Both regions, same drive (both pads turning, the busiest state the
projector reaches), same seed.

### 4.2 What PAL actually returns

| N | NTSC tick (mc) | NTSC loop | PAL tick (mc) | PAL loop |
|---:|---:|---|---:|---|
| 24 | 263,142 | 1 frame | 257,632 | 1 frame |
| 27 | 298,118 | 1 frame | 292,756 | 1 frame |
| 28 | 325,460 | 1 frame | 303,596 | 1 frame |
| 29 | **333,760** | **1 frame** | 317,196 | 1 frame |
| 30 | **350,838** | **2 frames** | 330,722 | 1 frame |
| 33 | 378,076 | 2 frames | 367,848 | 1 frame |
| 35 | 393,966 | 2 frames | **391,800** | **1 frame** |
| 36 | 402,250 | 2 frames | **402,894** | **2 frames** |
| 48 | 535,228 | 2 frames | 520,772 | 2 frames |

Frame = 357,368 mc NTSC / 425,568 mc PAL (read from the loop period itself, so
it is the machine's number).

* **NTSC** holds at a 333,760 mc tick and breaks at 350,838.
* **PAL** holds at a 391,800 mc tick and breaks at 402,894.
* **Usable per-frame work grows by +14.8% (upper bounds) to +17.4% (lower
  bounds), midpoint +16.1%.**

The frame grew +19.1%. The *usable work* grew less, because the fixed cost — the
NMI handler, `input_read`, `input2_read`, `sm_tick`, `fade_tick`,
`sm_frame_sync` — does not shrink when the frame gets longer. `docs/93` §7
measured the NMI's worst frame as **16,800 mc in both regions, agreeing to the
master cycle**; that is the same fact from the other end.

**+16.1% measured against +20% required. The near-coincidence does not survive
measurement.** That alone settles it, and it settles it *before* the harder
objection.

### 4.3 The harder objection: the extra tick arrives in a lump

Averages are the wrong instrument here. 6 ticks over 5 frames means **one frame
in five runs the tick twice**, and a tick is atomic — the kit has no resumable
tick and `sm_frame_sync` has no notion of a partial one.

Two of the shipped PAL ticks cost `2 × 257,632 = 515,264 mc` against a 425,568
mc frame: **121% of a frame in work alone**, before the ~23,000–32,000 mc of
non-tick loop cost the table above brackets.

That is arithmetic, so it was measured instead. `N = 48`'s *single* tick costs
**520,772 mc** — the same work as a double tick at 24, within 1.1% — and at
N=48 **the loop takes two frames** (851,132 mc = 1.967 frames). The rail cannot
execute that much work inside one PAL frame, and the observation is the rail's
own cadence oracle, not a sum.

### 4.4 Answer

**No.** Not on the tightest rail, at its shipped count, with the scheme as
described. Both halves fail independently: the average is short (+16.1% vs
+20%) and the peak does not fit (measured). A 6:5 scheme would need the tightest
rail's count cut from 24 to about 11 — halving the thing the rail exists to
showcase — and every other rail re-checked the same way.

**What would work, if R2 were ever wanted**, is the other strategy `docs/93` §10
tier 4 names: keep one tick per frame and **scale the per-frame deltas by 6/5**.
The measured cycle cost of that is near zero (the scale folds into constants and
LUTs at build time). Its cost is §5 — the 185-site re-tuning surface — and its
risk is that most of those sites are integers, not rates.

---

## 5. §5.5 — What assumes one tick equals one frame?

**185 named sites.** The length is the finding. The classification matters more
than the total, because the three classes cost completely different things.

### 5.1 Engine, kit-wide — 27 per-frame routines

Derived from the 31 exported `*_tick` / `*_step` / `*_advance` routines under
`engine/features/`, hand-read and reduced to those actually clocked by the
frame.

| # | site | what it assumes | class |
|---|---|---|---|
| 1 | `fade/fade.asm:29 fade_tick` | one INIDISP level per call; a fade is **15 frames** | integer ramp |
| 2 | `mosaic/mosaic.asm:11 mosaic_tick` | **20 frames out, 15 frames in** | integer ramp |
| 3 | `scene_mgr/scene_mgr.asm sm_nmi_core` | `ES_SM_FRAME` +1 per NMI — the kit's **only clock** | clock |
| 4 | `scene_mgr/scene_mgr.asm:334 sm_frame_sync` | one loop iteration = one frame, **by construction** (`wai` on the NMI) | clock |
| 5 | `vwf/vwf.asm vwf_tick` | reveal rate is "how often the game calls this" = per frame | rate |
| 6 | `dialog/dialog.asm dialog_advance` | page/typewriter advance per call | rate |
| 7 | `window_iris/window_iris.asm wi_tick` | table rebuilt per frame; the caller steps the radius per frame | rate |
| 8 | `mode7_stream/mode7_stream.asm stream_tick` | **clamp 8 tiles/axis/frame**, sized against 48 px/frame | **quota** |
| 9 | `pfs_stream/pfs_stream.asm:168` | **`PFS_CLAMP = 2` lines/axis/frame**, margin of 2 against 1 | **quota** |
| 10 | `m7f_obj/m7f_obj.asm:546 obj_prop_tick` | `M7F_PROP_RATE` frame divider (the propeller) | divider |
| 11 | `m7x_logic/m7x_logic.asm:33` | **`MXL_STEP_FRAMES = MXL_TILE_PX`** — a grid slide is exactly TILE_PX frames at 1 px/frame | **hard integer** |
| 12 | `m7x_town/m7x_town.asm town_step` / `town_try_step` | the same grid discipline | **hard integer** |
| 13 | `m7c_roll/m7c_roll.asm roll_tick` | per-frame velocity integration | rate |
| 14 | `shm_cam/shm_cam.asm shm_zoom_step` | per-frame zoom step with clamps | rate |
| 15 | `m7_barrel/m7_barrel.asm mb_tick` | per-frame applied-step | rate |
| 16 | `shp_cam/shp_cam.asm cam_tick` | per-frame camera integration, both pointers every frame | rate |
| 17 | `sh2_cam/sh2_cam.asm cam_advance` | per-frame, two cameras | rate |
| 18 | `m7f_cam/m7f_cam.asm m7f_apply_step` | per-frame position integration | rate |
| 19 | `m7f_obj/m7f_obj.asm cloud_tick` | per-frame accumulator | rate |
| 20 | `rs_logic/rs_logic.asm rs_advance` | auto-advance px/frame — the camera never stops | rate |
| 21 | `rs_logic/rs_logic.asm rs_path_step` | **the bank ramp**: one quantiser step per frame toward the target | **hard integer** |
| 22 | `rs_logic/rs_logic.asm rs_burst_step` | flash countdown in frames | countdown |
| 23 | `rs_logic/rs_logic.asm rs_tier_step` | grow-only size-tier hysteresis, one step per frame | **hard integer** |
| 24 | `rs_logic/rs_logic.asm rs_actors_step`, `rs_fail_step` | per-frame | rate/countdown |
| 25 | `split_v_obj/split_v_obj.asm sv_blade_step` | **the attack arc is a frame table indexed by a frame countdown** | **hard integer** |
| 26 | `split_v_obj/split_v_obj.asm sv_life_step` | per-frame | rate |
| 27 | scene ticks — `rl_tick`, `pfs_logic_tick`, `mxl_tick`, `mb_tick`, every `game/*/scenes/*::tick` | **one call per frame**, from `main.asm`'s four-line loop | clock |

The three worth naming individually, because they are the ones a 6/5 delta
scale cannot fix:

* **`MXL_STEP_FRAMES = MXL_TILE_PX`** (#11). The grid slide moves exactly 1 px
  per frame for exactly TILE_PX frames to cross one tile. At 6/5 that is 1.2
  px/frame — non-integer, so the slide either overshoots the grid or needs a
  fractional accumulator, and the feature's own header says the constant speed
  is "what keeps the camera's speed a constant the streamer can be reasoned
  about against". Scaling it breaks the streamer's premise, not just the
  animation.
* **The streaming quotas** (#8, #9). Both are per-*frame* allowances sized
  against a declared max px/frame, and both refuse to snap when the clamp bites
  — the anti-pattern their headers exist to prevent. Under a 6:5 scheme the
  double-tick frame moves the camera twice as far: `mode7_stream` would need 12
  tiles/axis against a clamp of 8, and `pfs_stream` 2 lines against a clamp of
  2 with zero margin. Raising the clamps raises the worst-frame staging cost —
  the same budget §4 has already shown does not fit.
* **`sv_blade_step`** (#25). A countdown indexes an animation table directly.
  Scale the countdown and it indexes a different row.

### 5.2 Game state — 135 declared variables across 27 of 37 rails

Machine-derived from `game/*/state.toml` by the rule *"the declaration's own
comment names frames, ticks, a timer, a clock, an animation, a countdown, or
8.8"*, then classified. The full lists are reproducible with the script in §13.

| class | count | what a 6/5 scale does to it |
|---|---|---|
| **A — rate accumulator (8.8)** e.g. `microzero:vel`, `microzero:sub_px`, `racer:speed`, `platformer:vy`, `split_v_fight:jvel`, `boss_saucer:star_far` | **33** | scales cleanly; the sub-pixel accumulator absorbs the fraction. **The cheap class** |
| **B — integer countdown** e.g. `boss:b_timer`, `boss_saucer:lunge_timer`, `boss:p_iframe`, `brawler:attackt`, `platformer:hurt`, `stomper:clearp` | **30** | each becomes N×5/6 with a rounding decision; a 30-frame i-frame window becomes 25 and the *feel* changes |
| **C — animation clock / divider** e.g. `brawler:atick`/`etick`, `shmup:atick`, `split_v_fight:atk`/`afr`/`ast` | **9** | dividers are small integers (2, 3, 4); ×5/6 has no integer answer. **Needs a fractional divider or a re-authored table** |
| **D — free-running frame counter** e.g. `railshooter:dist` (the odometer), `platformer:t_frames`, every `blink`/`frames` | **18** | mostly harmless (parity, blink), but `railshooter:dist` **indexes the baked S-path** |
| **E — other frame-coupled** e.g. `boss_saucer:b_heading`, `m7_dungeon:stepx`, `racer:lean`, `railshooter:burst_f` | **45** | must be read one at a time; several are hard integers |

### 5.3 Build-time, frame-indexed — 5 generators

These bake frame-indexed tables into ROM. A 6:5 tick scheme leaves them
**correct** (a tick indexes a row). A delta-scale scheme requires each to be
**regenerated at 5/6 length with new steps**, and each has a bit-exact Python
mirror that must be re-calibrated with it.

| tool | what it bakes | the coupling |
|---|---|---|
| `tools/gen_move_lut.py` | the movement + collision oracle; `Sim` steps **once per frame** and the ROM is asserted bit-exact against it | `VEL_MAX = 0x3000` = **48.0 px/f**; `ACCEL = 0x0100` = 1.0, i.e. **48 frames to top speed** |
| `tools/gen_boss_tracks.py` | the boss reveal/death matrix tracks | `REVEAL_FRAMES = 60`, `REVEAL_STEP = (REVEAL_SCALE-INIT_SCALE)/60` — a **per-frame** truncated step whose remainder the state exit is designed around |
| `tools/gen_saucer_tracks.py` | the lunge, retreat and scale tracks | `f = 1..60` reveal/death; the lunge is **44 frames**, terminal step +5; `DEATH_SPIN = 3` per-frame angle add |
| `tools/gen_meteor_tracks.py` | the meteor tracks | frame-indexed |
| `tools/gen_pose_tables.py` | 64 headings × L scanlines | the *pose cadence* (which heading is applied) is per-frame; `docs/93`/`measure` record 20.0 Hz flat-out and 15.8 Hz turning |

### 5.4 Substrate, pins and harness — 18 sites

| # | site | assumption |
|---|---|---|
| 1 | `allocator/substrate.toml [frame.ntsc]` | the only frame table; `mc_per_frame`, `vblank_lines`, `visible_lines`, `vblank_usable_bytes`, `cpu_worst_frame_mc` all mean *per NTSC frame* |
| 2 | `allocator/pin_budgets.py:57`, `allocator/schemas.py:142` | read `d["frame"]["ntsc"]` **by name** |
| 3 | `[measured.vblank] arm_cost_bytes = 128` | a per-frame multi-transfer allowance |
| 4 | `[measured.rebuild] cadence_*` | the certificate is literally *240 loop iterations in 240 hardware frames* — a 1:1 assertion |
| 5–16 | the **12 files** carrying the literal `357368` — `pin_budgets.py`, `substrate.toml`, `test_measure_cpu.py`, `test_microzero_stream.py`, `test_mode7_flight.py`, `test_pfs_stream.py`, `test_platformer.py`, `test_room_window.py`, `test_scene_mgr_shadow.py`, `test_schemas.py`, `tools/measure_col_map_cost.py`, `vendor/mesen_runner.py` | percent-of-frame and modulo arithmetic |
| 17 | `tests/test_measure_vblank.py:121` | `assert 4000 <= usable <= 6479` — the 38-line NTSC ceiling. **Would fail under PAL** (≥8,192) |
| 18 | `tests/test_measure_cpu.py:61,93` | `FRAME_MC = 357368` and a `>= 262` torn-slot guard that discards every legitimate PAL latch above line 261 |

`tests/frame_geometry.py` is **not** on this list and that is worth saying:
`docs/93` measured its 256×239 / row-7 geometry across 370 captures in both
regions and it holds in both. §1 adds the reason — the geometry is a fact about
Mesen's buffer, not about the console's region.

### 5.5 The total, and what it means

**27 + 135 + 5 + 18 = 185 named sites**, spread across 27 of 37 rails, 5 asset
generators, the substrate, and 12 harness files.

That number is the real cost of R2 and it was previously unknown. It is not a
number that shrinks with cleverness: 30 integer countdowns and 9 small-integer
animation dividers have no correct ×5/6, only a rounding policy — and a
rounding policy is a game-feel decision taken 39 times.

---

## 6. §5.6 — What does the audio driver do at 50 Hz?

### 6.1 Measured: the music keeps real time; the game does not

`docs/93` §6.5 derived this from the clock model and TAD's `TIMER_0` path and
listed "I did not record and compare WAVs" as an open item (§12.4). It is now
measured from the audio machine's own state.

Sample the S-DSP's eight voice pitch registers (`VxPITCH`, `$x2`/`$x3`) and
`KON` every frame on `racer`, over **10 emulated seconds** in each region:

| region | frames in 10 s | pitch-change frames | per second | per frame | KON changes |
|---|---|---|---|---|---|
| NTSC | 601 | 25 | 2.50 | 0.042 | **10** |
| PAL | 500 | 26 | 2.60 | 0.052 | **10** |

**Per second the note rate matches — KON transitions are 10 and 10. Per frame
it does not.** The music is on the S-SMP's own crystal and is region-blind; the
game is not. (The 25/26 spread is sampling granularity: a 50 Hz sampler and a
60 Hz sampler counting the same continuous event stream.)

### 6.2 What the driver actually does

Read, not assumed. Across all of `game/`, the only TAD entry points used are
`Tad_Init`, `Tad_LoadSong`, `Tad_Process` and `Tad_QueueSoundEffect`. **Nothing
in the tree calls `SET_SONG_TIMER`** (`vendor/tad/tad-audio.inc:197`), so tempo
is whatever the compiled song data sets, on the SPC clock. `Tad_Process` is
called once per frame from each rail's four-line main loop, so at 50 Hz it is
serviced 50 times a second instead of 60: **SFX trigger granularity coarsens
from 16.6 ms to 20 ms**, and nothing else changes. No rail branches on driver
state, so the APU's region-independent progress cannot leak into game logic.

### 6.3 What tracking would cost, in both directions

**Direction 1 — slow the music to match the game (5/6 tempo on PAL).** One
`SET_SONG_TIMER` command at boot with a region-derived value: the S-DSP
`TIMER_0` register takes 64 (fastest) to 255, 0 = 256, bounds-checked, minimum
64. Multiplying the tick clock by 6/5 is a single byte and **~1 hour of work**.
Two objections, and they are why this is not simply the answer:
* it makes the *music* wrong — a PAL player hears the soundtrack 17% flat,
  which is the complaint the era is remembered for;
* the songs' own data can change the timer mid-song (the command's own CAUTION
  note), so a boot-time set is not a guarantee.

**Direction 2 — speed the game to match the music.** That is R2, and §4 says
no.

**Direction 3 — do nothing, and say so.** Today the drift is inaudible because
nothing syncs gameplay to music. It becomes a real bug the moment a rhythm
beat, a cutscene cue or a music-gated transition ships — and when it does, the
fix is not "detect the region", it is **drive the sync from the audio side**
(read the driver's position, step the scene from it). Recording that now is
worth more than fixing something that is not yet broken.

### 6.4 Answer

**R3 has nothing to do for the current kit, and the reason is measured.** The
recommended action is one sentence in the submission text and one paragraph in
`AGENTS.md` warning the next feature author that a music-synced feature must
take its clock from the driver, not the frame counter.

---

## 7. The tiers: options, costs, and the NTSC-identity verdict

Sizes are engineering judgement anchored to what this pass measured. "NTSC
byte-identical" is answered on two axes because §4.1 conflates them and they
diverge (§9.1): **picture** = every rendered frame unchanged; **image** = the
`.sfc` unchanged.

### R0 — the region is known

| option | cost | NTSC picture | NTSC image | how proven |
|---|---|---|---|---|
| **R0-a — region as a declared FEATURE** (`engine/features/region/`, one dp claim for the flag, boot hook reads `$213F` and masks `#$10`) | **1 day** | **identical** | identical on the 36 rails that do not compose it | rebuild all 37, diff every `.sfc`; the composing rail gets a fresh capture diffed against its pre-change capture |
| R0-b — region read unconditionally in `vendor/rom/init.inc` | ½ day | identical | **moves on all 37**, including `microzero` → breaks the §4.2 pin | — |
| **R0-c — header destination via `.ifndef`**, default `$01` | 20 min | identical | identical unless a rail overrides | header dump on all 41 images |
| **R0-d — ROM-size byte derived** from the linker config | 1 hour | identical | **moves on the 20 rails whose byte lies** — and `microzero` is **not** one of them (it already sets `SF_HDR_ROM_SIZE = $09`) | header dump; the `microzero` md5 pin is untouched |

**Recommended: R0-a + R0-c + R0-d.** Together they give a correct header, a
readable region flag, and a `microzero.sfc` still at
`e45ddeabac4218cd71709da7b9fcc849`. R0-b is the obvious implementation and it is
the one that breaks the pin for nothing.

### R1 — the screen is filled

| option | cost | NTSC picture | NTSC image | how proven |
|---|---|---|---|---|
| **R1-A — overscan always on, tables at 239** | 3–5 days | **CHANGES** (239 lines on NTSC too) and costs NTSC **40.9% of its VBlank budget** | changes | — **out of spec, twice** |
| **R1-B — overscan gated on the region flag; one ROM; tables built for 239, inert past 224 on NTSC** | **3–4 days for one rail**, ~2 weeks for all 37 | **identical** — measured (§2.3: 0 px on both display lengths) | changes (bigger tables) | R1′ §1.4, all four clauses, per rail |
| R1-C — two ROMs, `--region` at build time | 2 weeks + a permanent second lane | identical | **identical** | trivially |
| R1-D — leave the display at 224 and state the limitation | 0 | identical | identical | — |

**Recommended: R1-B, scoped to the submission rail only.** R1-C is the only
option that satisfies §4.1 literally, and it buys that by doubling every gate,
oracle and pin forever — a bad trade for a property §4.1 cannot hold anyway
(§9.1). R1-B's picture-identity is the property that matters and it is
*measured*, not argued.

**R1-B's work, in order, per rail:**

1. take the pre-change NTSC capture (the oracle for clause 4);
2. classify each of the rail's HDMA claims **HOLD** or **CONTINUE** (§2.3) and
   declare it (§3.4 step C). HOLD claims are done;
3. for each CONTINUE claim, extend its table **by continuation** — read the
   generator first and establish whether its line count is a length or a
   parameter (§2.4). This is where the pixels get lost;
4. fix the sprite park (§2.5) — the size-bit fix plus the region-aware assert;
5. re-check band literals: the eight `band = [112, 224]` claims become
   `[112, 239]`;
6. re-check claim sizes: `sky_keys` +360 B, `grad_tabs` +45 B, the band-local
   pose blobs +13.4%; the 1,024-B-stride pose blobs cost nothing;
7. discharge R1′ clauses 1–4.

### R2 — the speed is preserved

| option | cost | NTSC picture | NTSC image | verdict |
|---|---|---|---|---|
| R2-A — 6 ticks per 5 frames | — | identical | identical | **measured not to fit** (§4.3) |
| R2-B — scale every per-frame delta by 6/5 | ≥ 2 weeks + a full re-audit | identical if gated on region | changes | **185 sites** (§5), 39 of them with no correct integer answer |
| R2-C — region-specific generated LUTs (two sets, selected at boot) | ≥ 2 weeks + ROM | identical | changes | ROM headroom exists (§2.6) but §5.3's five oracles each need a second bit-exact calibration |
| **R2-D — do not** | 0 | identical | identical | **recommended** |

**Recommended: R2-D.** §4 is the measurement and §5 is the surface. Neither
supports doing this before 2026-10-31, and R2 is the only tier that can break a
rail that works today.

### R3 — audio tracks the game

**Recommended: nothing, plus a written warning.** §6.

---

## 8. The recommended sequence, against 2026-10-31

72 days from 2026-08-20. Sizes are working days.

| # | work | size | ships what | gate |
|---|---|---|---|---|
| 1 | **R0-c + R0-d** — header destination `.ifndef`, ROM-size byte derived | **1 day** | the header stops lying, on all 37 | header dump on all 41 images; `microzero` md5 holds; `make gates` |
| 2 | **§3 step A + B1** — emit `ES_H_*_BAND_TOP`/`_BAND_LINES`, retire the eleven hand-written line-count constants, set `visible_lines = 239` | **1 day** | scanline coverage becomes a declaration | **every `.sfc` byte-identical** (measured: 37/37 allocate, `microzero` md5 holds) |
| 3 | **R0-a** — `region` as a declared feature | **1 day** | `$213F` bit 4 in a readable flag | the composing rail's capture under both regions; 36 images unchanged |
| 4 | **§3 step C** — the `continuation` keyword + the coverage `.assert` | **1 day** | under-coverage becomes a build failure | a plant: shorten a `table`-class table, require the build to refuse |
| 5 | *(gate: is the game itself done?)* | — | — | — |
| 6 | **R1-B on the submission rail** | **3–4 days** | a PAL build that fills the screen | R1′ clauses 1–4 |
| 7 | **the submission text** | ½ day | the stated limitation | — |

**Steps 1–4 are 4 days, are ROM-neutral or one-byte, and are worth doing on
their own merits** — they land the declaration and the header correctness even
if R1 never happens. Step 6 is the only one that needs the game finished first,
and it is the only one with real risk.

**Stop after step 4 if the game is not finished by the end of September.**
Step 6 without step 5 is the classic mistake: polishing the port of a game that
does not exist yet.

---

## 9. Where `docs/94` is wrong

Three places, and the first one blocks R0 as written.

### 9.1 §4.1 is self-contradictory with §3's R0

> "**NTSC output is byte-identical.** Every rail's `.sfc` **and** every rendered
> frame under `SF_REGION=ntsc` must be unchanged by R0 and R1."

R0 requires (a) boot reads `$213F` and stores a flag, (b) the destination byte
becomes derivable, (c) the ROM-size byte tells the truth on all 37 rails. All
three change the `.sfc`. **A constraint that forbids changing the image forbids
the tier it is written to protect.**

The fix is to split the constraint on the axis that actually carries the safety
property:

> **§4.1′.** Under `SF_REGION=ntsc`, **every rail's rendered frame is
> pixel-identical** to its pre-change frame — that is the reversibility
> property, and it is checked per rail with a capture diff. The **image** may
> change only where the change is itself the correction (the header bytes) or
> is provably inert on NTSC (a per-scanline table extended past the active
> area, §2.3). Every image change is enumerated in the landing note with its
> reason.

And §4.2's `microzero` pin is then holdable *by design choice*, not by accident:
region detection is a **declared feature**, `microzero` does not compose it, and
`microzero` already sets `SF_HDR_ROM_SIZE = $09` so the ROM-size correction does
not touch it. Verified: `microzero.sfc` rebuilds to
`e45ddeabac4218cd71709da7b9fcc849` with `visible_lines = 239` in the substrate.

### 9.2 R1's acceptance criterion names something unobservable

"a PAL frame shows no top/bottom border that an NTSC frame does not" cannot be
discharged in this harness and no instrument built here will change that (§1.1).
Replace with R1′ (§1.4).

### 9.3 §5.4's premise ("+19.1% vs +20% — near enough") does not survive

The +19.1% is the frame's growth, not the *usable work's*. Measured on the
tightest rail, usable per-frame work grows **+14.8% to +17.4%** — the fixed NMI
and sync cost does not shrink — and the scheme needs the extra work in a single
frame's lump that measurably does not fit. §4.

### 9.4 Is §2 wrong?

**Two of its three clauses are right; the third should be struck.**

> "A player on PAL hardware sees the game the NTSC player sees, at the speed its
> designer intended, filling the screen."

* *"sees the game the NTSC player sees"* — **right, and nearly already true.**
  19 of 37 rails are pixel-identical across regions and the rest differ by ≤1
  frame of animation phase (`docs/93` §5–6). Keep it.
* *"filling the screen"* — **right in intent, wrong in its acceptance
  criterion,** and much cheaper than the spec assumes now that HOLD-class
  structures are known to need nothing. Keep it, restated as R1′, and scope it
  to the rail that ships.
* *"at the speed its designer intended"* — **strike it.** It is the clause that
  costs 185 sites, that cannot be met by the scheme the spec floats, and that is
  the only one able to break a rail that works today. §0 of `docs/94` argues
  that shipping the era's uncompensated conversion "contradicts the pitch". The
  measurements say something narrower and more useful: the kit's proposition is
  that **the landmines are baked in and the composition is proven** — and R0
  plus the §3 declaration work serves that proposition directly, while R2 serves
  a different one (parity of feel) at a price that would leave the jam
  submission worse, not better.

**Recommended amendment to §2:** *"A player on PAL hardware sees the game the
NTSC player sees, filling the screen. The game runs at 50 Hz and is not
speed-compensated; that is stated in the submission and measured in
`docs/93`."*

---

## 10. What needs real hardware or a second emulator

Named, not asserted. Items 1–3 carry forward from `docs/93` §12 unchanged
because this pass could not touch them; 4–6 are new to this design.

1. **What a PAL television actually shows.** The whole reason R1 exists. Mesen
   crops the visible field, so 224 lines inside a 288-line PAL field is
   invisible here (§1.1) and stays invisible under any instrument built on this
   harness. **Needs a PAL console on a PAL set, or an emulator that models the
   visible field per region.** Everything R1′ checks is a *proxy* for this —
   an honest, mechanical proxy (the PPU really does draw 239 lines) but a proxy.
2. **Whether a real PAL SNES agrees with Mesen's 312-line, 21.28 MHz model.**
   Every number here is Mesen's, cross-read against Mesen's source. No second
   emulator was run and no hardware was touched, so CLAUDE.md rule 7's bar is
   not met for any "the emulator is wrong" claim — and **no such claim is
   made**. Nothing in this pass looked like an emulator bug.
3. **Whether the ≤1-frame boot-phase offset is exactly one frame on silicon.**
4. **Whether overscan's VBlank cost is exactly 40.9% on hardware.** The −40.9%
   figure is a Mesen measurement of a Mesen-modelled VBlank window. The
   *direction* and rough size follow from `225 → 240` and 262 total lines and
   are not in doubt; the exact byte count is the emulator's.
5. **Whether a real PPU's 239-line mode is safe on an NTSC television.** It is
   the reason the overscan bit must be region-gated in any case, and it is not
   an emulator question: some NTSC sets cut the extra lines and some roll.
   Gating on the region flag makes the question moot, which is another argument
   for gating.
6. **Flashcart and menu behaviour on a mismatched destination byte** — whether
   an FXPAK or a PAL console's menu does anything with `$7FD9 = $01`. Not
   answerable from an emulator, and it is the practical reason R0-c exists.
7. **Whether the jam's jury tests PAL at all, and how.** `docs/93` §12.6's
   point stands: it is one message to the organisers and it settles the whole
   tier question. **Ask before spending step 6's four days.**

---

## 11. `tools/active_lines.py`

The one artifact of this pass besides this document. Report-only: it asserts
nothing, is wired into no gate, changes no existing behaviour, and exits 0
unless a child process fails — the same contract `tools/pal_probe.py` holds.

```bash
python3 tools/active_lines.py build/racer.sfc --frames 120,360
python3 tools/active_lines.py --shift ntsc.png pal.png
```

It reports, per region, the **PPU's active line count read off the rendered
frame** (both the extent and the offset witness of §1.2), plus `mc_per_frame` as
the liveness check that the region knob was live at all. It is the instrument
R1′ clauses 1 and 2 are written against, and it exists because the criterion
`docs/94` wrote could not be discharged by any instrument that did.

Self-check on `racer`, both regions: `mc/frame` 357,366 / 425,566, picture rows
7..230, verdict *"consistent with a 224-line active area"*. Against the overscan
spike: rows 0..238, verdict *"OVERSCAN … the active area is 239 lines"*. The
`--shift` witness reports 0 mismatched rows for a true pair and 224 of 224 for a
negative control.

---

## 12. The spikes, and that they were reverted

Two spikes were built. Neither is committed; `git diff --stat origin/main`
carries only this document and `tools/active_lines.py`.

**Spike 1 — the SETINI patch (binary, never in the tree).** `vendor/rom/
ppu_reset.inc:115-123` assembles to `A9 E0 8D 32 21 9C 33 21` (`lda #$E0` / `sta
$2132` / `stz $2133`) at a single, unique offset in every image. Two byte
edits in a **copy of the built `.sfc` under `/tmp`** turn it into `lda #$04` /
`sta $2132` / `sta $2133`: COLDATA with all three plane-select bits clear writes
nothing (`SnesPpu.cpp:2214-2223` — none of the three `if` branches fire), and
SETINI takes `$04` = overscan. The control arm (the COLDATA change alone)
renders byte-identical to the stock image, which is what makes the spike's
second arm attributable to SETINI and nothing else. Used on `microzero`,
`racer`, `brawler`, `split_h_2p_demo`, `meteor_event` and `probe_vblank`.

A third one-line variant of the same site — `lda a:$213F` / `sta f:$7EF000` /
`nop`, exactly eight bytes — is what measured the region flag in §1.3.

**Spike 2 — the 239-line gradient (source, reverted).** Four edits across
`engine/features/rc_grad/rc_grad.asm`, `tools/gen_racer_assets.py` and
`engine/features/rc_rom/feature.toml`, rebuilt with `make rc-assets racer`. The
build passed the allocator, `no_literals`, and every `.assert` on the first try
— which is itself a result about R1's difficulty — and it produced the two
findings of §2.4 (the naive form moves 15,581 NTSC pixels) and §2.3 (the
anchored form moves none). Reverted with `git checkout --`; `build/racer.sfc`
was rebuilt afterwards and is **byte-identical to the pre-spike binary**
(verified with `cmp`).

The substrate was also set to `visible_lines = 239` for the §3.3 measurement
and restored; `microzero.sfc` was rebuilt under it and held its pinned md5.

---

## 13. Reproducing this

Every measurement in this document, in the order it appears.

```bash
# §1 — the instrument, and the region-liveness check
make racer
python3 tools/active_lines.py build/racer.sfc --frames 120,360

# §1.3 — the region flag, in-ROM. Patch a COPY of a built image:
#   offset of  A9 E0 8D 32 21 9C 33 21   ->   AD 3F 21 8F 00 F0 7E EA
#   then read $7E:F000 after 60 frames under SF_REGION=ntsc / pal.

# §2.1 — the VBlank budget under overscan. tests/test_measure_vblank.py's
# probe and protocol with the NTSC sanity bound removed and the ROM path
# parameterised, run once per region against the stock and SETINI-patched
# probe_vblank.sfc.
make build/probe_vblank.sfc

# §2.2/§2.3/§2.4 — the overscan renders and the gradient spike. §12 gives
# the exact byte patch and the four source edits.

# §3.3 — the frame-model widening
sed -i 's/^visible_lines = 224  /visible_lines = 239  /' allocator/substrate.toml
for g in game/*/; do python3 allocator/allocate.py --game $g \
    --features-dir engine/features --out /tmp/alloc/$(basename $g) || echo "REFUSED $g"; done
make microzero && md5sum build/microzero.sfc   # e45ddeabac4218cd71709da7b9fcc849
git checkout -- allocator/substrate.toml

# §4 — the tightest rail, both regions. tools/measure_sh2_swarm.py's own
# marks, measure() and loop_periods(), driven once per region with SWM_N
# poked across [24,27,28,29,30,33,34,35,36,48].
make sh2-assets split_h_2p_demo sh2-labels

# §5.2 — the game-state enumeration
#   parse game/*/state.toml; keep every declaration whose own comment names
#   frames / tick / timer / clock / anim / countdown / 8.8; classify.

# §6 — the audio rate. Sample the S-DSP voice pitch registers ($x2/$x3) and
# KON every frame for 10 emulated seconds per region on build/racer.sfc.
```

Gates after this document and `tools/active_lines.py` landed, all clean and all
run bare:

```
make width-check    width_lint: 0 finding(s) across 224 file(s)
make time-check     no_wallclock: 0 NEW finding(s) across 241 file(s)
make register       census matches the tree (155 dirs); demand lint 18/25 rows
make rom-unbacked   backed arm accepted, unbacked arm refused
make cleanroom      swept 972 text files, 0 zip(s); 3 hit(s) exempted by 2 allowlist entries
```
