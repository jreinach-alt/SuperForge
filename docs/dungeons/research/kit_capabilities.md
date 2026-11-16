# Research — what the kit already proves for this game

> A read-only survey of the tree, 2026-11-13, at `aee087f`. No ROM was built
> for this survey.
>
> **Primary vs secondary.** Citations are `file:line` in the tree, unless they
> are marked (doc), which means a doc's claim was relied on. The following
> were spot-checked against the tree when this file was written:
> - `input2`
> - the 24 B `save` payload cap (`engine/features/save/feature.toml:9`)
> - `sm_request`'s same-scene no-op (`engine/features/scene_mgr/scene_mgr.asm:176`)
> - `window_iris`'s measured 20.84% (`engine/features/window_iris/feature.toml:77`)
> - the `tiles16` vocabulary (`docs/100` §, `allocator/schemas.py:906`)
>
> Everything else is the survey's reading. Per CLAUDE.md, **if you are about
> to rely on a row, open the tool.**

## 1. Budget pins (measured, `allocator/substrate.toml`)

| quantity | value | where |
|---|---|---|
| NTSC frame | 357,368 master clocks (mc). A reference worst 60 fps frame is 305,348 mc, of which 16,800 mc is NMI | `substrate.toml:91,110,145-150` |
| VBlank DMA | **5,952 B/frame**. Each extra transfer costs 128 B. OAM is 544 B | `substrate.toml:95,132-139` |
| OAM | 128 entries. **32 sprites and 34 slivers per scanline: NOT modelled by the allocator** | `docs/01:48-66` (doc) |
| VRAM / WRAM / DP / CGRAM | 64 KB / 128 KB / 256 B ("the scarcest class") / 256 words | `substrate.toml:10-39` |
| ROM | LoROM, 524,288 B, 16 × 32 KB windows. Window 0 is code. A DMA source cannot cross a bank | `substrate.toml:112-124` |
| `col_map` query | 951.9 mc each | `docs/capability_envelope.md:137` (doc) |
| `window_iris` lantern | 74,458 mc/frame = **20.84%** | `window_iris/feature.toml:77` |
| TAD audio tick | 438 mc/frame | (doc) `hardware_for_your_idea.md` |

## 2. Subsystem status for a 2P top-down crawler

| need | status | evidence and consequence |
|---|---|---|
| Two pads | **Proven** | `engine/features/input2` (DP `inp2_cur/prev/press`, from `$421A`). `room` is already a 2-hero shared-screen rail: `tests/test_c2_slice_c.py::test_pad2_drives_the_twin`. `Machine.advance(pad1=, pad2=)` drives both. |
| Shared camera | **Near** | The `split_v_fight` midpoint plus the `camera_follow` world clamp. Leash and warp are new game logic (DP only). |
| Split screen | **Refused by design here** | `split_v_bg` owns BG1–3 and every window register, and is horizontal-only. No Mode 1 two-axis split is proven. |
| Whole floor resident in VRAM | **Near** | The 64×64 tilemap `shape` is proven (`pfs_bg/feature.toml:72`). `tiles16` is in the video vocabulary, but **no rail declares it yet** (`docs/100` "NO RAIL DECLARES tiles16 TODAY", an art-budget reason that does not apply to a metatile game). 64×64 entries × 16 px = 1024×1024 px = one whole generated floor, 8 KB, uploaded once at enter. |
| 2-axis streaming from WRAM | **Avoided** | `pfs_stream` streams from two 32 KB ROM blobs. A generated level would need both in WRAM (64 KB). The `tiles16` route above makes streaming unnecessary. |
| Runtime cell edits (doors, chests) | **Proven pattern** | `breaker_bg`'s `brk_q`, 4 arbitrary BG1 cells per frame (`breaker_bg/feature.toml:99-114`). |
| Collision | **Near** | `col_map` binds to ROM blobs and is unproven against WRAM. The proven runtime-mutable shape is `breaker_bg`'s WRAM grid (`brk_cells`). Here the generated metatile map IS the collision grid. |
| PRNG | **New feature, with precedent** | `m7c_roll` runs two seeded 16-bit Galois LFSRs in DP (`m7c_roll.asm:33-41,244-270`), but no reusable `rng` feature exists. Entropy comes from `scene_mgr`'s `sm_frame` sampled at a button press. |
| Entity pools | **Near** | `pool` (4 B DP, the consumer owns the arrays). Precedents: `shmup_obj`'s pinned OAM ranges, and `.struct` records as in `sh2_swarm` / `rs_obj`. |
| Enemy behaviours | **Near** | Patrol (`patrol`), knockback with grace (`m7_dungeon`), chase-and-hit (`brawler`). The largest live crowd is the 24-sprite swarm (`split_h_2p_demo`). |
| Projectiles | **Proven** | `shmup` bullets; `m7_oshoot` on `pool`. |
| Hero sprites, P1/P2 tint | **Proven** | `split_v_obj`: one 32×32 knight drawn twice with an OBJ palette swap. |
| Metasprites / Y-sort | **New** | Zero hits for "metasprite". Every cast is resident CHR uploaded at enter. |
| HUD | **Proven** | OBJ pips (`room_logic` `hud_pips`), BG3 text via `bg_text`. Note that a running scene gets 4 text cells per frame. |
| Scenes and transitions | **Proven, with a trap** | `scene_mgr` + `fade`/`mosaic`. **`sm_request` to the scene already running is a no-op**, so "next floor" must go through another scene (06 §5). |
| Save | **Proven, too small** | 2 slots × 24 B payload with CRC (`save/feature.toml:9`). The payload cap is "a choice, not a law". (The jam's no-SRAM rule does not apply: this is not a jam game.) |
| Audio | **Proven** | `audio` + `tad_rom`. Existing cues include hit, pickup, footstep, explosion and chime. **Never run on hardware** (`JAM.md` row 6c). |
| Hit-flash | **Near** | An OAM palette-attribute swap (zero DMA), or a CGRAM VBlank write (the `smt_opt` shape). |
| Lantern / darkness | **Proven but costly** | `window_iris`: one window, tied to `room_rom`, 20.84% of the frame. Two lanterns would be new work. That is scope tier C only. |
| Region | **Proven** | `region` + `tick_scale`. Integer cooldowns are "class B": not scaled, and that must be disclosed (`shmup/game.toml:21-25`). |

## 3. Traps the docs already paid for

- `enter_scr` must be in `globals`, or the build fails late on `ES_ESCR`.
- A BG feature that owns CGRAM word 0 refuses `backdrop`.
- One OBSEL owner per scene, so another rail's `*_obj` cannot be composed in.
- Any register a transfer drives needs an off-state owner in every scene
  (the `blend_off` pattern).
- Do not copy `rpg_logic`'s shared `t0` scratch shape.
- Power-on RAM is random under test. Never zero-init "to be safe".
