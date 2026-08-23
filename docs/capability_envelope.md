# The capability envelope — what this engine proves today

> Status: LIVE, derived from the tree. Every row below names the shipped game
> (and where useful the test) that **proves** it — there are no aspirational
> rows. To re-verify any line: open `game/<name>/game.toml` (each header is a
> ruling ledger: what the rail is, what it composes, what it refused and why),
> then run its tests (`tests/test_<name>*.py` boot the ROM on the emulator and
> read rendered output). The generated supply census lives in
> [`docs/09_feature_register.md`](09_feature_register.md) §3 and `make register`
> gates it against the tree. **Where any document and the tree disagree, the
> tree wins** — this document was written under that rule and is read under it.

The point of this file: triage "my idea" without archaeology.

- **Proven** — a shipped game already does it. Part 1 finds the game; Part 2
  finds it by capability.
- **Near** — existing features, new composition. Per-rail work, not engine
  work. Part 3 shows what "exactly that" looks like in the library.
- **New** — a fresh feature with declared claims. Part 3 names the checklist
  and the two gates a new composition must pass.
- **Doesn't fit** — the substrate refuses. Part 3 lists the refusals the
  allocator makes for you and the limits it deliberately does not model.

All 37 games build to 524,288-byte ROMs and are gated in the `Makefile`'s
`gates:` block (`make rail-registered` fails if one goes missing).

---

## Part 1 — the library: 37 games, one line each

### Complete games (8)

| game | what it is → what it uniquely proves |
|---|---|
| `microzero` | Title → race → results and the edges between them; the smallest complete game. Globals survive scene edges; the race scene composes eleven features at once (perspective floor, streaming, HUD band, proportional text, collision, car). |
| `platformer` | The flagship: four-scene arc (title → play → over/win → title) with a battery-SRAM continue. Restart-as-transition; two-layer stepped-band HDMA parallax (`platformer_bg`). |
| `shmup` | Vertical shooter, two scenes. Proves the restart ruling from the other side: BG1 untouched by play, but a banner cannot be unprinted on a running frame — a running scene reaches VRAM only through `bg_text`'s one-cell VBlank queue. |
| `breaker` | Paddle-and-ball, two scenes. A wall of 180 cells can only be rebuilt in `play::enter` under forced blank — restart is spelled as what it physically is, a scene transition (`sm_request` refuses self-transitions). |
| `rpg` | Mode 7 perspective overworld walked on a tile grid, mosaic wipe into a Mode 1 town, opaque BG3 dialog with paged text, battery save, music surviving the swap. Debuts `dialog`; everything else composed. |
| `room` | Playable windowing: a carried lantern built from WH0/WH1 per scanline (`window_iris`), three scenes, one song persisting with per-room echo, a visit count that survives power-off, an OBJ pip HUD. |
| `racer` | Kart on the perspective floor: accel/coast, off-road drag with the map as collision ground truth, day-night COLDATA cycle, pause, race music. The channel-pressure rail: 7 of 8 HDMA channels, vblank/active phase sharing. |
| `brawler` | Two animated 32×32 fighters with an HP/FOE/WINS text HUD. The one allocator `partial` in the set: the second OBJ name table (resolution in `engine/features/brawler_obj/feature.toml`). |

### The Mode 7 line (9)

| game | what it is → what it uniquely proves |
|---|---|
| `m7_dungeon` | Rotating static-affine dungeon floor; the cast projected through the matrix transpose (`m7_project`, fixed pivot); tank controls, world-space `col_map`, wall-turn patrol, knockback, win card. |
| `m7_oshoot` | Run-and-gun on the spinning floor; the pivot re-pins to the player every frame (the moving-pivot stress `m7_dungeon` doesn't have); gameplay entirely in world space; `pool`'s second consumer; the scale-1.0 LUT used exactly as built. |
| `mode7_explore` | 512×512-tile overworld streamed through the 128×128 VRAM window as you walk; camera clamped off the toroidal seam; mosaic into a Mode 1 town interior and back — the mode swap spelled as a second scene so the allocator proves the two register owners never coexist. |
| `mode7_flight` | Free flight with input-controlled altitude driving the perspective scale. The 12.7 MB exact pose table becomes ~28 KB of baked factors joined per frame by the hardware multiplier (`m7f_cam`); day/night clock; zero dropped ticks over 240 worst-case frames (`tests/test_mode7_flight.py`). |
| `mode7_chamber` | Four cooperating per-scanline HDMA effects over one plane: barrel bow (`m7_barrel`, baked ROM matrix columns), perspective recession, a Mode 1 band at scanline 32, and a brightness vignette. |
| `railshooter` | On-rails forward shooter; `pool` debut; depth from a decoupled 1/z pinhole (explicitly *not* the matrix inverse) with pre-drawn size tiers and a depth-ordered OAM emit that never sorts. |
| `boss` | "The boss IS the screen": the Mode 7 BG layer scaled and rotated as one rigid image under a frame-indexed matrix track (`m7_track` debut) — reveal 5.0→1.5, free rotation at 1.5, death recede — with sprites and HP pips composited over it. |
| `boss_saucer` | The first reuse of `m7_track`, unchanged: the saucer grows in out of the star field and lunges at the camera — a 71 px disc to a 141 px one, the small end of what the wrap ceiling and the magnification floor leave — and fires a beam LANCED from its own emitter down onto your column; TAD audio composed into the fight. |
| `meteor_event` | Mid-level Mode 1 ⇄ Mode 7 cutscene: play freezes, BG platforms are captured into a declared 40-slot OAM claim, the meteor grows about a pinned pivot with a tumble, then the level is restored. |

### The split-screen line (8)

| game | what it is → what it uniquely proves |
|---|---|
| `split_v_demo` | The vertical window dual-view primitive: two cameras clipped to screen halves by PPU window 1, plus a seam bar. |
| `split_v_fight` | The seamless distance-driven split: two cameras onto one stage diverging with the fighters' distance, one VRAM copy, pixel-identical halves at zero separation; BG3 *is* the divider; second pad (`input2`). |
| `split_h_demo` | The cockpit raster split: BG3 instrument panel above, perspective floor below, HDMA rewriting BGMODE **and** TM at one seam — held under a live per-VBlank matrix rebuild. |
| `split_h_matrix_demo` | Two constant camera matrices swapped at the seam by HDMA: one world rendered at 8-px and 32-px checker periods in the same frame, for ~nil CPU. |
| `split_h_persp_demo` | Two full per-scanline perspective trapezoids stacked at a single-scanline seam, each a ROM-resident band-local pose streamed through indirect HDMA — four VBlank stores per frame. |
| `split_h_persp3_demo` | The same rail at three bands: the band count lives in a WRAM table's entry list, not the declaration — the pair of rails is the evidence. |
| `split_h_2p_demo` | Two pads, two independent Mode 7 cameras, one world, one frame; ROM pose streaming; sprites placed via `m7_persp_project`. |
| `split_h_irq_grad_demo` | Spends what the seam IRQ freed: two panning cameras, band 2's origin by IRQ, and a freed channel driving a per-scanline COLDATA gradient over the whole frame. |

### Mechanics studies (10)

| game | what it is → what it uniquely proves |
|---|---|
| `sprite_game` | The OBJ-only catch game — no BG feature at all, a genuine `oam_sprites` isolation; `catch_dot` (`game/sprite_game/scenes/play.asm`) is the worked example of game-side AABB. |
| `hud_game` | The text-surface rail: one scene (edges are optional in the manifest schema), a movable sprite over a live SCORE line; the `backdrop`-not-BG-feature ruling. |
| `scroller` | The BG pipeline alone: a checkerboard scrolled four ways under a centred sprite. |
| `camera_follow` | The camera/world-space split: follow camera with world-edge clamp, sprite drawn at world − camera; carries the "allocator proves collision-freedom, not sufficiency" ruling. |
| `maze` | `col_map` against a hand-built walled map; the canonical per-axis move-check (diagonals slide along walls); the two-gate lesson — allocator OK, then the binding `.error` is the design review. |
| `jumper` | Jump physics end to end: take-off, ascent, head bump, apex, descent, landing snap, rest; display tilemap and collision world derive from one ROM blob, so what you stand on and what you see agree by construction. |
| `stomper` | Enemy resolution on jumper physics: land from above culls the enemy and bounces the player; side contact knocks back; a FOES counter and a CLEAR card. |
| `patrol` | The composition reference: sprites, BG terrain, text HUD, tile collision, jump physics and patrol beats all in one frame. |
| `scroll_run` | The page-seam world: a 512-px level across two BG pages with a platform straddling the seam, camera follow + clamp; its composition was probed before any ASM existed. |
| `platformer_stream` | Two-axis normal-BG streaming: a level four screens wide *and* tall through a 64×64-word four-page ring (`pfs_stream`) with no pop-in. |

### Engine trials (2)

| game | what it is → what it uniquely proves |
|---|---|
| `seam_irq_trial` | The scanline-IRQ debut: a seam V-IRQ delivers band 2's Mode 7 origin byte-identically to the classic HDMA control — proving a `wai` frame loop survives a second wake source and the seam HBlank fits four origin bytes, *inside* the engine spine every game uses. |
| `split_v_seamtrial` | The seamless split in isolation: zero new engine features — `split_v_bg` composed under a different director (a triangle-wave `spread` instead of fighter distance). |

---

## Part 2 — the capability map

Capability → proving game(s) → feature(s). Features live under
`engine/features/<name>/`; the full claims-per-feature table is docs/09 §3.

| capability | proven by | feature(s) |
|---|---|---|
| **Scene flow** — multi-scene arcs, edges, enter/exit under forced blank | `microzero` (3), `platformer` (4), `shmup`/`breaker`/`rpg` (2 each), `room` (3) | `scene_mgr` (INIDISP commit, frame sync, phase machine), `fade` |
| **Persistent globals across edges** | `microzero` (results read the race), `rpg` (overworld camera survives the town), `platformer` (continue) | `[global]` blocks in `state.toml`; global-lifetime claims |
| **Single-scene games** — no edges, honestly declared | `hud_game`, `scroller`, `camera_follow`, `jumper`, `stomper`, `patrol`, `maze`, `sprite_game`, `scroll_run`, `platformer_stream`, most demos | `[[edge]]` is optional (`allocator/schemas.py`) |
| **Restart = scene transition** (a running scene cannot rewrite its map) | `breaker`, `shmup`, `platformer` | `scene_mgr` (`sm_request` refuses self-transitions) |
| **Mode 7 static-affine floor** (uniform matrix, scale 1.0) | `m7_oshoot` (the LUT exactly as built), `m7_dungeon`, `mode7_explore` | `m7_affine` (256-heading LUT) |
| **Mode 7 per-scanline perspective** (ROM-baked pose, indirect HDMA) | `microzero`, `racer`, `railshooter`, `rpg`, `split_h_demo` | `mode7_persp` + `pose_rom` |
| **Mode 7 world streaming** (4096×4096 world through the 128×128 window) | `microzero`, `racer` (at kart speed), `mode7_explore` (on foot, toroidal clamp) | `mode7_stream` (+ a floor feature's seed upload) |
| **Normal-BG streaming, two axes** | `platformer_stream` | `pfs_stream` — a sibling mechanism, not a `mode7_stream` parameterisation (its header says why). Verified in the tree (`tests/test_pfs_stream.py`, `tests/test_platformer_stream.py`); docs/09 §1's STREAM row still says "normal-BG streaming unproven here" — the tree wins. |
| **Altitude driving perspective scale** | `mode7_flight` | `m7f_cam` (separable hybrid: baked factors × hardware multiply) |
| **Scale-ramping affine tracks** (zoom/rotate composed, frame-indexed) | `boss` (debut), `boss_saucer`, `meteor_event` — each rail bakes its own track blobs | `m7_track` (player; format + contract in its `feature.toml`) |
| **Per-scanline matrix columns** (barrel/bow) | `mode7_chamber` | `m7_barrel` (baked ROM column sets, indirect by construction) |
| **Mode 7 ⇄ Mode 1 swaps** | `mode7_explore` (town), `rpg` (town), `meteor_event` (mid-level, with BG-to-sprite capture) | spelled as scene edges — one register owner per scene, proven by `check_reg_ownership` |
| **How the plane reads on screen** — the camera-style fact, stated plainly: FLAT OVERHEAD (a rotating map seen from above) is the static-affine set; TILTED INTO THE DISTANCE (a road-view horizon) is the per-scanline perspective set; FREE FLIGHT over it adds altitude | flat overhead: `m7_dungeon`, `m7_oshoot`, `mode7_explore` · tilted: `microzero`, `racer`, `railshooter`, `rpg`, `split_h_demo` · flight: `mode7_flight` | the same fact the two rows above state by mechanism (`m7_affine` vs `mode7_persp` + `pose_rom`; `m7f_cam`) |
| **Projection onto the floor** | `m7_dungeon` (fixed pivot), `m7_oshoot` (re-pinned pivot), `split_h_2p_demo` (perspective bands), `railshooter` (decoupled 1/z pinhole) | `m7_project`, `m7_persp_project`, rail-side pinhole |
| **Vertical split (PPU windows)** | `split_v_fight`, `split_v_demo`, `split_v_seamtrial` | `split_v_bg` (window 1 clip, seam bar) |
| **Horizontal raster band split** (BGMODE + TM at a seam) | `split_h_demo` (cockpit); as a Mode 1 band over the Mode 7 plane: `microzero`, `racer`, `railshooter` (HUD band, with `sky_band` — docs/09 §6.A), `rpg`, `mode7_chamber` | `split_band` (+ `sky_band`) |
| **Two cameras, one frame** | `split_h_matrix_demo` (two matrices), `split_h_persp_demo` (two trapezoids), `split_h_persp3_demo` (three bands), `split_h_2p_demo` (two pads) | `shm_cam`, `shp_cam`, `sh2_cam` |
| **Scanline IRQ mid-frame CPU** | `seam_irq_trial` (proof), `split_h_irq_grad_demo` (applied) | `irq` + `sit_cam` / `shg_cam` |
| **Windowing as a game object** (lantern) | `room` — incl. the disarm-on-exit path | `window_iris` (WH0/WH1 per scanline) |
| **Sprite pipeline** — 544-B shadow, boot park, one VBlank DMA | every game with OBJ; isolated by `sprite_game` | `oam_sprites` |
| **Sprite pools** (spawn/despawn lifecycles) | `railshooter` (debut), `m7_oshoot`, `boss`, `boss_saucer` | `pool` |
| **Sprite priority** — OAM index order *is* priority; pinned slot ledgers | `railshooter` (`engine/features/rs_obj/feature.toml`'s front-to-back ledger), `room` (pips over heroes) | per-rail `*_obj` claims |
| **Second OBJ name table** | `brawler` — the set's one allocator `partial` | `brawler_obj` |
| **Fixed-cell text + live HUD cells** | every HUD game; live counters via the one-cell VBlank queue (`text_queue_cell` / `text_vblank_commit`) | `bg_text` + `text_dp` + `font_rom` |
| **Proportional (VWF) text** | `microzero` | `vwf` + `vwf_rom` |
| **Paged dialog panel** | `rpg` (open/page/close/reopen proven on screenshot pixels, `tests/test_rpg.py`) | `dialog` |
| **HUD regimes** | `hud_game` (BG3 text), `room` (OBJ pips), `boss` (sprite HP pips — BG3 does not exist in Mode 7), HUD band over Mode 7 (`microzero` etc.) | `bg_text`, per-rail `*_obj`, `split_band`+`sky_band` |
| **Tile-map collision** (world-space probe) | 12 games compose `col_map` — `maze` (hand-built map), `jumper` (map agrees with display by construction), `racer` (off-road ground truth), `mode7_explore`, `rpg`, `stomper`, `patrol`, … | `col_map` — measured 951.9 mc/query (`tools/measure_col_map_cost.py`); world bound by the includer |
| **Box collision (AABB)** | game-side inline, by ruling: `sprite_game`'s `catch_dot` is the worked example; `boss`/`boss_saucer` took the same ruling | (no engine feature — deliberate) |
| **Physics precedents** | `jumper` (full jump cycle), `stomper` (stomp), `breaker` (ball), `racer` (accel/coast/drag), `microzero` (car physics, `tests/test_microzero_physics.py`), `scroll_run` (page-seam runs) | per-rail game logic |
| **Audio** — music, SFX under music, persistence, echo | 8 games compose `audio`; `room` proves one song across three scenes + per-room echo (S-DSP asserted, `tests/test_slice_b_audio.py`); `racer` (pause + race music); `boss_saucer` (composed into a fight) | `audio` + `tad_rom` (vendored driver; `spc` claims) |
| **Battery saves** | `rpg` (CRC-gated payload; test power-cycles and checks SRAM bytes *and* restored screen), `room` (visit count survives power-off), `platformer` (continue) | `save` (2×32 B slots, CRC-16, reject semantics — geometry "a choice, not a law") |
| **Transitions** | fades everywhere (`scene_mgr` phases); mosaic wipes: `mode7_explore`, `rpg`; freeze/capture/restore: `meteor_event` | `fade`, `mosaic`, scene edges |
| **Day/night + gradients** | `racer` (COLDATA day-night cycle), `mode7_flight` (free-running clock + horizon fog), `mode7_chamber` (vignette), `split_h_irq_grad_demo` (per-scanline COLDATA); `rgb_gradient` composed by 6 games | `rgb_gradient`, `rc_grad`, `shg_grad`, `met_glow` |
| **Camera regimes** | `scroller` (free scroll), `camera_follow` (follow + world clamp), `scroll_run` (clamp + page seam), `platformer`/`platformer_stream` (side-view), `racer` (steerable kart), `mode7_flight` (flight), `m7_oshoot` (rotate-to-face), the split line (two at once) | per-rail; the split `*_cam` features |
| **Region parity** — the same ROM at the same REAL-TIME speed on NTSC and PAL, opt-in per rail | 28 of the 37 compose it — every playable rail — at a measured band of **0.994–1.027** against the **0.832** an uncompensated rail reads (`docs/98` §1). The other 9 decline in their own `game.toml`: 7 determinism trials whose frame-indexed sweeps are the thing under test, and 2 deferred with the measurement that defers them. NTSC is pixel-identical against every pre-change image | `region` (reads the console's region line once at boot, publishes `ES_RGN_PAL`) + `tick_scale` (the `TS_STEP` macro; no claims of its own, `depends = ["region"]`). Part 3 item 7 is what a consumer still has to decide |

---

## Part 3 — composing, and reading the edges

### Near vs new — how to tell

**Near** means: the mechanism already ships, and your rail supplies data and a
director. The library's own examples of *exactly that*:

- `split_v_seamtrial` — **zero new engine features**: `split_v_bg` composed
  under a different director (a frame counter instead of fighter distance).
  Everything below the (mid, spread) pair is untouched.
- `boss_saucer` — the first reuse of `m7_track`: the player, blob format and
  test shape are the boss rail's, unchanged; what is new is five track blobs
  and a cast. Its header states the norm: *"a composing rail that needed to
  change one would be an escalation, not an edit."*
- `m7_oshoot` — "NO NEW ENGINE FEATURE": renders at the exact scale the
  `m7_affine` LUT tabulates, consumes `pool` as shipped.

Expect near-work to include your rail's own `*_bg` / `*_obj` / `*_rom`
features — that is **per-rail work, not engine work**. The keystone BG pattern
(a tilemap built from declared geometry, written under the enter-time forced
blank) has a long chain of instances to crib from — `jumper`'s header lists
the seven before it (room/breaker/shmup/platformer/pfs/scroller/cf), and
`stomper_bg` / `brawler_bg` follow it. Per-rail `*_bg` exists
because the display features are welded to their art blobs by name —
`room_bg.asm` resolves six `room_rom` symbols, so composing it renders the
*room*'s art, not yours (`camera_follow` and `maze` both carry this ruling).

**New** means a fresh `feature.toml` with claims. The checklist is docs/09
§4.6; the twelve claim classes are in `allocator/schemas.py`. Probe the
composition *before* writing ASM — `scroll_run`'s manifest was its first
commit, so an infeasible list would have stopped the build before any code.

**Two gates, and you must read both.** The allocator proves the claims
compose; it holds no opinion on whether the composition can produce your rail.
`maze` is the worked case: `room_bg` + `col_map` allocate OK, then `col_map`'s
six `.error`-guarded binding symbols stop the *assembly* because the room blob
has nothing they can point at. "The undefined-symbol error is the design
review." Run `allocate.py` AND ask what the bound symbols would render.

**Doesn't fit** shows up two ways. (1) The allocator refuses: two mechanisms
for one register set (`mode7_persp`'s HDMA claims own M7A–D, so it cannot sit
beside `m7_affine`'s CPU writes in one scene), two owners of BGMODE/TM in one
scene (why mode swaps are scene edges). These refusals are the product working.
(2) The substrate refuses and the allocator deliberately does *not* model it —
docs/01: at most 32 sprites / 34 slivers per scanline (hand-count crowded
rows; `railshooter`'s ledger shows the discipline), and BG3 does not exist in
Mode 7 (HUDs there are sprites or a `split_band` Mode 1 band).

### Composition prerequisites you cannot see from a distance

Each verified against the implementing file; open them before composing.

**1. `enter_scr` must be armed in `globals` — and the failure arrives late.**
Eight features' enter-time upload routines run through the shared 8-byte DP
scratch `ES_ESCR` (`room_bg`, `breaker_bg`, `shmup_bg`, `shmup_obj`,
`mode7_floor`, `split_v_bg`, `platformer_bg`, `platformer_obj` all reference
it), but none of them lists `enter_scr` in `depends` — its claims sit on the
**companion** because the shared code is top-level
(`engine/features/enter_scr/feature.toml` explains; docs/09 §4.1 names the
pattern). So the allocator will not drag it in: if your `game.toml` composes
one of those features without `enter_scr` in `globals`, allocation succeeds
and ca65 fails later with an undefined `ES_ESCR` — the symbol reaches
`engine_state_globals.inc` only when the feature is in the composition
(`allocator/allocate.py`, `emit`). The fix is one word in `globals`; the
detection is grepping the feature's `.asm` for `ES_ESCR` before you compose
it. (`bg_text`'s companion `text_dp` does *not* have this trap — `bg_text`
declares the dependency, so it is dragged in.)

**2. `rpg_logic`'s `t0` is a documented transient share — treat it as such.**
`engine/features/rpg_logic/feature.toml` declares `+14 t0 (2 B) shared
TRANSIENT scratch, consumed inside one call`; `rpg_logic.asm` adds the rule:
`rpg_town` and `rpg_obj` both use it, "never across a `jsr` that could reach
the other". `game/rpg/scenes/town.asm` (~line 400) shows the discipline in
action: a destination is carried on the *stack* across the `rpgt_blocks` call
because that routine uses the very same byte pair as its own index scratch —
an earlier form parked it in `RPG_T0` and read back garbage. If you extend the
rpg rail (or copy its shape), audit every value you hold across a call against
the callee's scratch use.

**3. `save`'s CRC LUT is bound by a label the *game* provides.**
`engine/features/save/save.asm` reads the table as `lda f:crc16_lut_bin, x` —
a blob label the feature references by name but does not define. Every
composing game's `main.asm` supplies it: a `crc16_lut_bin:` label +
`.incbin "crc16_lut.bin"` + two `.assert`s pinning `^crc16_lut_bin` and
`.loword(crc16_lut_bin)` to the emitted `ES_R_CRC16_LUT_ROM_BANK/_ADDR`
(`game/rpg/main.asm`, `game/room/main.asm`, `game/platformer/main.asm` are the
three worked instances — the asserts refuse the build if the `.segment` drifts
from the allocation). This label-plus-assert arrangement is the standard shape
for *every* `rom` claim (AGENTS.md "ROM claims"), and `make rom-unbacked`
gates that each claim's `.incbin` actually fills it. Also note the stated
non-init: SRAM cannot appear in `[init] zero` (an init-zeroed save is not a
save) — gate on `sv_load`/`sv_exists`'s `$FFFF`/`$FFFE` codes, never on raw
SRAM bytes.

**4. The `role` vocabulary — what a dir under `engine/features/` even is.**
Every `feature.toml` declares a `role`, and the build refuses an unknown one
(AGENTS.md's list): `feature` (supplies a demanded capability) · `blob` (ROM
data, no behaviour) · `companion` (holds claims for shared top-level code) ·
`consumer` (game-side user of an engine feature) · `game_logic` (game code
living there only because that is where the allocator looks) · `fixture`.
The census counts today: 73 feature, 44 blob, 3 companion (`enter_scr`,
`text_dp`, `text_chr`), 25 consumer, 10 game_logic. Read a `game_logic` dir
(`rpg_logic`, `race_logic`, `m7x_logic`, …) as a worked example of *your*
side of the line, not as engine surface. A new dir also owes a
`supplies / serves` line in docs/09 §3.1 — `make register` refuses one
without the other.

**5. The allocator does not police symbol REACH — the contracts do.** The
build refuses an undeclared *claim* and a raw *literal*, but a feature's ASM
that names ANOTHER feature's emitted symbol assembles fine once both are
composed — nothing checks that the use was agreed. That is what the binding
conventions exist for: includer-bound symbols behind named `.error` guards,
contract blocks at the top of the `.asm`, and the emulator test as the only
proof. Before consuming a symbol you did not declare, find its owner's
contract block; if there isn't one, you are proposing a new contract, not
using an existing one.

**6. Where a feature's contracts and clobbers actually live.** Three places,
in order: (a) the **`feature.toml` header** — ownership and binding contracts
(`m7_track`'s "THE CONTRACT — who binds, who indexes, who advances";
`mode7_stream`'s and `col_map`'s binding contracts continue at the top of
their `.asm`: includer-bound symbols, each missing one a named `.error`, plus
the multi-chunk `.assert` obligation the feature file cannot state for you);
(b) **per-routine comment blocks** in the `.asm` — register clobbers
(`room_bg.asm`: "`ES_ESCR+0` = source bank. Clobbers A, X, Y."); (c)
**`; WIDTH-RISK:` markers** on exported routines — the entry/exit width
contract (`col_map.asm`: "entered A16/I16, EXITS A8/I16"). These markers are
load-bearing, not decoration: the width lint cannot see cross-file callers
(CLAUDE.md rule 6), so the marker is the only statement of the contract your
call site must satisfy — and the emulator test is the only check.

**7. `tick_scale` scales a RATE — and what a number *means* decides whether it
is one.** Composing `region` + `tick_scale` does not make a rail
region-correct; it hands you `TS_STEP`, and you still classify every number you
feed it — by DIMENSION, not by where it sits (`docs/98` §2). A **velocity**
(px per frame) takes the ratio once. An **acceleration** (px per frame²) takes
it twice, and since `TS_STEP` applies exactly one, the second goes into the
BASE on the PAL arm — `game/jumper/scenes/sky.asm` is the one place that
arithmetic is spelled, and it re-asserts the rail's own no-tunnel bound on the
*scaled* constants rather than assuming a tuned number survives a scale. A
**playhead** into a baked per-frame table scales the cursor and leaves the
table byte-identical (`brawler`'s animation divider is untouched; what is
scaled is how fast the clock advances — `docs/97` §3.3). An **integer countdown
or duration** stays an integer and its consequence is disclosed rather than
rounded away — a PAL swing window is 20% wider. An **event per button press**
is not a rate at all, and is never scaled. What a consumer declares is two
`u16@dp` per scaled rate — the carried fraction and this frame's published
whole-unit step — in its own `state.toml` (`game/jumper/state.toml` is the
worked two-rate case, one pair for the run and one for gravity); `tick_scale`
claims nothing itself, and its `depends = ["region"]` makes the allocator
auto-include the flag, so listing only `tick_scale` in `globals` builds the
same bytes as listing both.

### Reading order for a new composition

1. Part 1 → pick the nearest game; read its `game.toml` header end to end —
   the "NOT COMPOSED, each for a reason" ledgers are case law you inherit.
2. Part 2 → for each capability you need, open the proving feature's
   `feature.toml`, then its `.asm`'s contract block and `; WIDTH-RISK:` lines.
3. Write your `game.toml`/`state.toml` first and build — let the allocator
   answer feasibility before any ASM exists (`scroll_run`'s method).
4. docs/09 §4 (architecture map + checklist) when something is genuinely new.
