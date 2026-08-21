# 97 — R0 landed: the region is known, the header stops lying, the timebase is a feature

> Status: LANDING NOTE. It discharges [`docs/94`](94_region_support_spec.md)
> §3's **R0** and promotes [`docs/96`](96_region_timebase_tooling.md) §4's
> prototype into a composed feature. It is also the enumeration `docs/94`
> §4.1 requires: **every ROM whose bytes moved is listed in §5 with its
> reason.**
>
> R1 (the taller active area) is NOT in this work and neither is the 185-site
> retune. `docs/95` §7's R2-D recommendation stands.

## 0. The three things that landed

**One.** *Region detection is a declared, opt-in feature.*
`engine/features/region` reads `$213F` bit 4 once at boot and publishes
`ES_RGN_PAL` — 0 on NTSC, 1 on PAL — for game code to read with one `lda`. A
rail that does not compose it is **byte-identical to what it was**, which is
how `microzero` keeps `e45ddeabac4218cd71709da7b9fcc849` while R0 lands.

**Two.** *The header stops lying, in both fields.* `$FFD7` (ROM size) is now
**imported from the linker config** — the only file that knows how big the
image will be — instead of defaulting to 32 KB, which 20 of 37 rails inherited
while linking 524,288 B. `$FFD9` (destination) is `.ifndef`-guarded with its
old default. And `tools/fix_checksum.py` — the one build step that already
reads the finished image — now **refuses to patch a header whose declared size
is not the file's real length**, so the class cannot come back silently.

**Three.** *The timebase is a composable feature, and it generalises.*
`engine/features/tick_scale` supplies the accumulator `docs/96` §4 measured at
0.99919 behind `-D SF_TICK=3`. The flag is gone; `scroller` and `brawler`
compose it. Measured on the promoted form, both regions, `tools/rate_oracle.py`:

| rail | class | observable | before | after |
|---|---|---|---:|---:|
| `scroller` | scrolling | `cam_x` (world px/s) | 0.83208 | **0.99919** |
| `brawler` | sprite animation | `knight_tile` (OAM tile byte) | 0.82831 | **0.99969** |
| `brawler` | sprite animation | `px` (world px/s) | 0.83208 | **0.99909** |

## 1. `engine/features/region` — the shape, and how a game reads it

```asm
    lda z:ES_RGN_PAL        ; 0 = NTSC, 1 = PAL
    beq @ntsc
```

One `dp` claim (`rgn_pal`, 2 B) and one routine, `region_init`, called once
from `MAIN`'s boot block beside `input_init` and `fade_init`. The flag is
game-lifetime, not scene-scoped: a console does not change region between
scenes.

**Why bit 4 and not a compare.** `$213F` is STAT78. Bits 0–3 are the PPU
version (3 on both machines) and bit 7 is the odd/even frame flag, which
changes under the ROM's feet — so the test is a MASK. `docs/95` §1.3 measured
the byte in-ROM: `$03` under `SF_REGION=ntsc`, `$13` under `pal`.

**Why it does not disturb the three existing `$213F` reads.** Those sites
(`sit_cam.asm:409,430`, `shg_cam.asm:475,496`, `m7f_cam.asm:230`) read it to
reset the OPHCT/OPVCT flip-flops, and each issues its OWN `lda a:$213F`
immediately before the `$213C`/`$213D` pair it cares about — so the toggle
state each reads from is the one it has just established, not one a boot-time
read left behind.

**No `[[claims.reg]]`.** The reg-ownership pass in `allocator/no_literals.py`
is a WRITER-side gate (`sta`/`stx`/`sty`/`stz` plus the RMW family) and this
feature never writes a PPU port. Read in the implementing file, not inferred;
the three sites above have carried no reg claim for as long as they have
existed.

**Why opt-in rather than `init.inc`.** `docs/95` §7's R0-b reads the same bit
unconditionally in `vendor/rom/init.inc`. That moves the image on **all 37**
rails including `microzero`, breaking `docs/94` §4.2's md5 pin for nothing. A
declared feature makes the reversibility property structural instead of
careful.

## 2. The two header corrections

### 2.1 `$FFD7` — the ROM-size byte, derived

The old default: `SF_HDR_ROM_SIZE = $05` in `vendor/rom/header.inc`, inherited
by every rail that did not override it. Seventeen rails overrode it with `$09`
in their own `main.asm` — the same fact written down eighteen times and checked
nowhere.

`header.inc` cannot know the answer: the size is settled by the linker config's
MEMORY areas, after ca65 has finished. So the config declares it, beside the
areas that create it:

```
SYMBOLS {
    SF_LD_ROM_SIZE: type = export, value = $09;   # 2^9 KB = 512 KB
}
```

and `header.inc` imports it. `<` is required rather than decorative:
`.byte <import>` emits a byte-sized fixup ld65 resolves, while a bare
`.byte import` is an assembly-time **Range error** (ca65 cannot prove an
unresolved external fits in a byte).

**The seventeen hand declarations are gone, and their removal moved zero
bytes** — which is the proof that the derivation reproduces what they said.

Before / after, read out of the built images:

| image | before | after | real size |
|---|---|---|---|
| `microzero.sfc` (declared `$09` by hand) | `$09` | `$09` | 524,288 B |
| `racer.sfc` (declared `$09` by hand) | `$09` | `$09` | 524,288 B |
| `split_v_fight.sfc` (inherited the default) | **`$05`** | **`$09`** | 524,288 B |
| `boss_saucer.sfc` (inherited the default) | **`$05`** | **`$09`** | 524,288 B |
| `scroller.sfc` (inherited the default) | **`$05`** | **`$09`** | 524,288 B |
| `toy.sfc` | `$05` | `$05` | 32,768 B |
| `probe_vblank.sfc` | `$05` | `$05` | 32,768 B |

Across every image this repo links: **2 declare `$05` and are 32,768 B; 54
declare `$09` and are 524,288 B; none lies.**

### 2.2 `$FFD9` — the destination byte, overridable

`.byte $01` became `.ifndef SF_HDR_DEST` / default `$01` / `.byte
SF_HDR_DEST`. Nothing in the tree overrides it and **no image's byte moved**.

It is a declaration of the TARGET MARKET, not a runtime region — a cart
composing `region` detects the console at boot and adapts, so `$01` stays
correct for a ROM meant to run on both machines. What reads this byte is a
flashcart menu or a ROM-verification tool, neither of which is emulated here
(`docs/95` §10 item 6), which is exactly why the override needed to exist and
why the default should not change on a guess.

### 2.3 The gate that keeps it true

`tools/fix_checksum.py::_check_rom_size` refuses any image whose `$FFD7` does
not equal `log2(len / 1024)`. It lives there rather than in a new `make`
target for one reason: **it is the only build step that already reads the
finished image**, so it is the only place that can see both the declaration and
the truth — and a tool that patched a checksum over a lying header would be
certifying the lie. Every rail's recipe already runs it (42 call sites in the
Makefile plus the variant build scripts).

Proven against a real violation, not believed:

```
$ python3 tools/fix_checksum.py liar.sfc      # microzero with $7FD7 poked to $05
liar.sfc: header $7FD7 declares ROM size $05 = 32768 B, but the image is
524288 B. The declaration lies. ...
exit=1
```

`tests/test_rom_header.py` carries that plant plus the non-vacuity control (a
truthful image must still be accepted, and idempotently — `microzero`'s md5 pin
depends on it).

**Stated limit.** `probe_cpu.sfc` / `probe_cpu_step.sfc` are linked against
`vendor/probe_ref/lorom_512k.cfg` with the quarry's own vendored
`vendor/probe_ref/inc/header.inc` (which declares `.byte $08`), and their
Makefile recipes patch `$7FD7` to `$09` post-link. Those two recipes do not run
`fix_checksum.py`, so the gate does not cover them; the patch already makes
them truthful, and `tests/test_rom_header.py` does not read them.

## 3. `engine/features/tick_scale` — the timebase, composed

### 3.1 What it is

One tick per frame; the per-frame delta scaled by the measured frame ratio in
8.8; the fraction carried between frames. `TS_STEP <accumulator>, <base>`
publishes this frame's WHOLE units:

```asm
    TS_STEP z:US_TS_ACC, TS_CAM_BASE     ; A = whole units this frame
    sta z:US_TS_STEP                     ; every downstream add reads this
```

On NTSC the base is a whole number of units, the scale is 1, and the carried
fraction stays 0 for ever — so every consumer publishes **today's constant, to
the unit, on every frame**. That is why the NTSC picture cannot move, and
`tests/test_region.py` asserts it as a set equality over a 180-frame window
rather than as an average.

The ratio is stored as a GAIN — the step **plus** 0.2018039 of it — rather than
as 1.2018039×. Arithmetically identical, and it raises the largest base ca65
can scale at build time from ~7.0 to ~166 units/frame inside 32-bit expression
arithmetic. `TS_BASE_MAX` asserts the bound instead of leaving it to be
discovered by a silently wrapped constant.

### 3.2 What it claims: nothing, and that is the design

`docs/96` §7 sketched the shipping form as "a feature with its own dp claim".
It has none, deliberately. The only two things such a claim could hold are:

* **the region flag** — `region` owns it, and a second copy is exactly the
  duplicated-constant defect this kit exists to refuse;
* **a shared accumulator** — which `docs/96` §7 itself rules out ("each
  consumer declaring its own accumulator instead of sharing one"), because two
  consumers on different base rates cannot share a carried fraction.

What is left is arithmetic, so what the feature supplies is arithmetic plus the
`depends = ["region"]` that makes composing the macro without the flag it reads
a **refusal** rather than a silent scale of 1.

A CONSUMER declares two `u16@dp` per rate: the accumulator and the published
step. `scroller` declares one pair (its whole motion is one rate). `brawler`
declares three.

### 3.3 The two rails, and why the second one is `brawler`

`scroller` is where the prototype lived and it stays a consumer for the reason
it was chosen: smallest rail in the tree, motion is one word, and the oracle
reads it with a first-half/second-half spread of ZERO, so a 0.1% change is
unmissable.

`brawler` was picked for its MOTION CLASS, not its size. The oracle registry
covers scrolling, Mode 7, sprite animation and physics; `brawler` is **sprite
animation**, and it is the class where the mechanism has something to prove —
because two of `docs/95` §5.2's classes meet in one rail:

* an integer walk step (`BR_WALK_SPEED` = 2 px/frame, `BR_ENEMY_SPEED` = 1),
  the same shape `scroller` has;
* an **animation divider** — `br_anim_meta`'s per-table frame rate, a small
  integer that `docs/95` §5.2 classifies as having *"no correct ×5/6, only a
  rounding policy"*. Nine of those exist across the tree and they are part of
  why that document recommends against a retune.

The accumulator answers the divider **without touching it**: the divider stays
the integer its table authored and what is scaled is the amount the CLOCK
advances by — 1 unit per NTSC frame, 1.2018 per PAL frame. One companion
change makes that exact: the clock now **carries its overshoot** (`sbc` the
divider) instead of zeroing, because a 2-unit PAL frame can cross the divider
by one and dropping that one is a bias the accumulator upstream cannot see. On
NTSC the clock arrives at the divider exactly, so `tick − rate = 0` and the
behaviour is unchanged.

And the observable is rendered output: `knight_tile` is the OAM tile byte the
PPU draws from, not the counter behind it.

**The two rails that were NOT chosen, and why.** `racer` (Mode 7) has a
streaming quota sized against a declared max px/frame (`docs/95` §5.1 #8: 8
tiles/axis/frame against 48 px/frame); compensating its speed pushes the
demand past a clamp whose own header forbids snapping, which is R2 work, not
foundation work. `platformer` (physics) is a ballistic arc — preserving it in
real time needs velocity × r AND gravity × r², a two-constant retune of a
`gen_move_lut.py`-mirrored oracle, and `docs/95` §5.3 names that mirror as
needing its own re-calibration.

### 3.4 What was scaled on those rails, and what was NOT

Scaled: `scroller`'s camera step; `brawler`'s player walk, enemy walk and
animation clock. **Three rates, and nothing else.**

Not scaled, and deliberately: every integer countdown on `brawler`
(`BR_ATTACK_LEN` 16, `BR_INV_T` 45, `BR_STUN_T` 20, `BR_RESPAWN_T` 90), and
the free-running frame heartbeats (`US_BLINK`, `US_FRAMES`). Those are
`docs/95` §5.2's class B, they are 30 of the 185, and each needs a rounding
policy that is a game-feel decision. **This sprint is not that retune.**

That scope is not a claim, it is an assertion:
`tests/test_region.py::test_the_unscaled_heartbeat_in_the_same_run_still_reads_five_sixths`
reads `US_BLINK` from the SAME probe run that reads the walk cycle at parity
and requires it to still be 0.832. It is the non-vacuity control — without it,
"the rates match" is satisfied by an instrument that cannot see a difference —
and it is an honest statement of what is left.

## 4. The evidence

### 4.1 Parity, per composing rail, both regions

`python3 tools/rate_oracle.py scroller brawler --halves`, warm + window as the
registry declares, both regions, on the shipped images.

```
scroller  [scrolling]  scroller.sfc  md5 1cc6f10974bcc9c06a60ec434ad0ce02
  frame period   ntsc   357,366 mc  (60.0988 fps)   pal   425,566 mc  (50.0072 fps)
  observable     unit                 NTSC/s        PAL/s     ratio
  cam_x          world px            120.198      120.101   0.99919  PARITY
                 halves 1st/2nd      120.198      120.198   120.017   120.184

brawler  [sprite animation]  brawler.sfc  md5 af404239133ea8e0c6edc3f3a0572d54
  observable     unit                 NTSC/s        PAL/s     ratio
  knight_tile    tile changes         10.005       10.001   0.99969  PARITY
                 halves 1st/2nd        9.993       10.016    10.001    10.001
  px             world px            120.198      120.089   0.99909  PARITY
                 halves 1st/2nd      120.198      120.198   120.017   120.160
```

**The NTSC column did not move** — 120.198, 10.005, 120.198 are the same
numbers `docs/96` §2.5 published for the uncompensated rails. That is the
reversibility property visible in the measurement, before any pixel is looked
at.

### 4.2 The NTSC picture did not move, per rail

`tools/tb_picture_diff.py` — same drive, absolute PPU frames 120/300/600, the
PRE-CHANGE image as the reference and the rebuilt image as the variant, both
regions. All 37 rails: **NTSC IDENTICAL**. The PAL arm is the non-vacuity
control and it differs on exactly the two rails that compose the timebase.

The tool gained a `--pad` flag in this work (it was hardwired to `scroller`'s
held-RIGHT drive) and now prints each image's md5 beside its name, because a
pre-change reference and its rebuilt variant share a basename and the name
alone cannot tell them apart.

### 4.3 Gates

Run bare, each on the tip of this work:

```
make width-check    width_lint: 0 finding(s) across 226 file(s)
make time-check     no_wallclock: 0 NEW finding(s) across 248 file(s); 0 grandfathered
make toy-bad        allocator refused as designed (VRAM overlap)
make rom-unbacked   backed arm accepted, unbacked arm refused
make register       census matches the tree (157 dirs); demand lint 18/25 rows
make rail-registered  every rail named at every site
make cleanroom      swept 990 text files, 0 zip(s); 3 hit(s) exempted by 2 entries
make tick-check     tick_lint: 0 NEW finding(s) across 705 file(s); 356 held
make measure        substrate pins agree with fresh measurements
```

`make tick-check`'s baseline went **356 → 356 with no site added and none
removed** — only line numbers moved. This work added no new frame coupling to
the tracked population.

## 5. Every ROM whose bytes changed — the enumeration `docs/94` §4.1 requires

**31 images. Two reasons, and no third.**

**(a) The ROM-size correction — 29 images, header bytes only.** In every one of
them the ONLY bytes that differ are `$7FD7` (`$05` → `$09`) and the
complement/checksum pair at `$7FD c`–`$7FDF` that `fix_checksum.py` recomputes
over it. Byte-diffed, not assumed. Nineteen are rails; ten are the variant and
control images the rails' test modules build:

`boss` · `boss_saucer` · `camera_follow` · `jumper` · `m7_dungeon` ·
`m7_oshoot` · `maze` · `meteor_event` · `mode7_explore` · `mode7_flight` ·
`scroll_run` · `split_h_2p_demo` · `split_h_demo` · `split_h_matrix_demo` ·
`split_h_persp3_demo` · `split_h_persp_demo` · `split_v_demo` ·
`split_v_fight` · `split_v_seamtrial` — and the variants `sh2_autocam`,
`sh2_badorder`, `sh2_same_cam`, `sh2_same_heading`, `sh2_sp_culloff`,
`sh2_sp_forward`, `sh2_sp_tieroff`, `shd_autodemo`, `shp_autodemo`,
`svd_nowin`.

*This is the correction, not a regression.* Each of these declared 32 KB while
being 524,288 B.

**(b) The composition — 2 images.** `scroller.sfc`
(`f34ae672bc8b98e034172ba1e28acbbf` → `1cc6f10974bcc9c06a60ec434ad0ce02`) and
`brawler.sfc` (`1b72f8d129fd7a3b667a9c4d9c8c7586` →
`af404239133ea8e0c6edc3f3a0572d54`) compose `region` + `tick_scale`. Both
carry the header correction as well.

**Unchanged, byte for byte:** the other 16 rails, `toy`, `probe_vblank`,
`probe_cpu`, `probe_cpu_step`. In particular:

* **`microzero.sfc` holds `e45ddeabac4218cd71709da7b9fcc849`** — `docs/94`
  §4.2's pin. It does not compose either feature and it already declared `$09`
  by hand, so removing that hand declaration moved nothing;
* the 17 rails that hand-declared `$09` are byte-identical after their
  declarations were deleted, which is the proof that the linker-config
  derivation reproduces exactly what they said.

## 6. What this does NOT do

1. **R1 is untouched.** The active area is still 224 lines in both regions and
   the overscan bit is still never set. `docs/95` §2 costs that work and
   `docs/95` §1.4 restates its acceptance criterion; nothing here approaches it.
2. **The 185 sites are not retuned.** Two rails' three rates are expressed
   against a declared tick. `make tick-check` still holds 356.
3. **`SF_HDR_DEST` changes nothing today.** No image's `$FFD9` moved. What
   landed is the ability to override it without editing a vendored file.
4. **`region` is composed by two rails.** The other 35 do not read the flag and
   are byte-identical.
5. **Nothing here was checked on hardware or on a second emulator.** Every
   number is Mesen2's, cross-read against Mesen2's source. `docs/95` §10's list
   carries forward unchanged — in particular item 6, whether a flashcart or a
   PAL console's menu does anything with `$7FD9 = $01`, which is the practical
   reason the destination override exists and which an emulator cannot answer.
