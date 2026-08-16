# 01 — Substrate Reference (the hardware budget the allocator solves against)

> Status: LIVE — the hardware budget and constraints the allocator solves against

Derived from `fullsnes` (nocash), the SNES hardware reference. This is the
machine-readable *budget + constraints* the declarative allocator
(`allocator/`) packs claims into. Line cites are `fullsnes:NNN`.

**The rule:** numbers here that fullsnes states exactly are authoritative;
numbers marked **⟨measure⟩** must be pinned on the cycle-accurate emulator and
never estimated. `make measure` re-measures the pins and fails on drift.

---

## Spatial classes

### VRAM — 64 KB, word-addressed `fullsnes:466-533,887-905`
- **32 K words = 64 KB installed.** VMADD is a word address; **bit 15 is not
  connected → `$8000-$FFFF` mirror `$0000-$7FFF`.** (This is the wrap that made me
  mis-read the VWF base as `$B100` instead of effective `$3100`.)
- **Access only during VBlank or forced blank** `fullsnes:770,810`. Writes go
  through `$2116/17` (addr) + `$2118/19` (data), with VMAIN (`$2115`) increment
  step (1/32/128 words) + optional address translation.
- **BG tilemap base (`BGxSC` $2107-A):** granularity **1 K-word (2 KB) steps**;
  size 32×32 / 64×32 / 32×64 / 64×64 tiles. A 32×32 map = 2 KB.
- **BG CHR base (`BGxxNBA` $210B-C):** granularity **4 K-word steps**.
- **Tile sizes:** 4/16/256-color = **16 / 32 / 64 bytes** per 8×8 tile
  `fullsnes:1100`. OBJ tiles always 16-color (32 B).
- *Allocator constraints:* tilemap regions align to 2 KB; CHR bases align to 8 KB
  (4 K-word); the VMADD wrap means "nominal" bases must be reduced mod `$8000`.

### Mode 7 VRAM — the interleaved special case `fullsnes:898,1113-1125`
- Mode 7 **ignores `BGxSC`/`BGxxNBA`**: BG-map base is always 0, size always
  **128×128 tiles**, i.e. **1024×1024 px**.
- VRAM is split **BG map at EVEN byte addresses, CHR tiles at ODD byte addresses**;
  a Mode 7 tile = 8-bit pixels, **64 odd bytes within a 128-byte region**.
  → map = 128×128 = **16 KB (even)**, CHR = 256 tiles × 64 = **16 KB (odd)**,
  together **32 KB = half of VRAM**, interleaved.
- `M7SEL` ($211A) "Screen Over": **wrap within 128×128** (mode 0/1) — the torus the
  streamer rides. A 4096×4096 world (512×512 tiles ≈ **256 KB of map bytes**) is
  streamed into this 128×128 torus.
- *Allocator constraint:* Mode 7, when a scene declares it, claims a full 32 KB
  interleaved VRAM region; streaming writes go to EVEN addresses via VMAIN step.

### CGRAM — 512 bytes `fullsnes:541-554`
- 256 words (`$2121` addr, `$2122` data, word writes). Sub-palettes per BG depth.

### OAM — 544 bytes `fullsnes:434-461`
- `220h` bytes (128 sprites × 4 + 32-byte high table); `220-3FF` mirror `200-21F`.
- *Note:* the PPU destroys OAMADD during render; reload at VBlank start `fullsnes:444`.
- **PER-SCANLINE, and this is the limit the allocator DOES NOT MODEL:** at most
  **32 sprites** and **34 8×8 slivers** may be rendered on any one scanline; past
  either, the PPU drops sprites and raises `STAT77` (`$213E`) bit 6 (RANGE OVER)
  / bit 7 (TIME OVER) `fullsnes:1383-1385` (+`22935`) — note that `:455-461` is
  OAMADDR/RDOAM, not the per-scanline limit. A sprite contributes `width/8`
  slivers to every line it covers — so a 32×32 costs 4 and a 16×16 costs 2 — and
  the count is over **all 128 slots**, not one feature's window.
  `allocator/allocate.py::place_oam` checks only that the summed `sprites` fit
  the 128-entry table, so a composition that overruns a scanline **allocates
  cleanly and drops sprites at runtime**. Where this budget binds, the arithmetic
  has to be done by hand and written down — it was done that way for
  `railshooter` (measured worst case 22 slivers of 34, corroborated by STAT77
  never firing over 1,200 frames). **And when you do it, count sprite EXTENTS,
  not projected ground points:** a published bound in this project was once
  wrong for exactly that reason, and the error is invisible until the PPU starts
  dropping sprites on one line of one camera pose.

### WRAM — 128 KB ($7E-$7F), DP the scarce fast slice `fullsnes:413-419`
- **WRAM runs at 2.6 MHz (slow).** Faster tricks exist (seq `[$2180]`, the
  `$43x0-B` DMA regs as 8×12 scratch bytes) but the model treats WRAM as one slow
  128 KB pool.
- **DP (direct page):** 256 bytes, the fast/short-addressing page — its own
  scarce sub-allocation, shared engine+user, global/scene-scoped.
- **No WRAM↔WRAM DMA** `fullsnes:408`.

### SRAM — battery-backed cart RAM, the program-wide persistent class

Every statement below was verified against Mesen2 source at the cited
file:line.

- **Header encoding:** `$FFD8` holds an exponent — SRAM bytes = `1024 << N`,
  `$00` = none (`BaseCartridge.cpp:258-259`; Mesen caps the raw nibble at 8).
  The battery flag lives in `$FFD6` cart type (`$02` = ROM+RAM+battery). Mesen
  persists on the size byte alone; **bsnes and real hardware read the chipset
  byte**, so both must be set — the allocator derives BOTH from packed demand.
  No claims → `$00`/`$00`, byte-identical headers.
- **Mapping + mirroring:** with SRAM present, LoROM maps it at banks
  `$70-$7D` and `$F0-$FF`; the canonical window every mapper variant agrees on
  is **bank `$70`, offsets `$0000-$7FFF`** — hence the `[sram]` cap of one
  window (32 KiB). Handlers are 4 KiB chunks over the physical size, so a
  small SRAM **mirrors** across the window.
- **Speed:** bank `$70` is in the always-slow region — **8 mc/access,
  MEMSEL-independent**. Never quote /6 for a save copy.
- **Battery lifecycle (emulation):** the `.srm` is written at unload /
  power-off, **never on write**; loaded at `LoadRom` whenever size > 0. An
  in-process `load_rom` of the same path is a faithful power cycle.
- **Power-on: virgin SRAM is RANDOM garbage**, exactly like WRAM — and unlike
  WRAM it must **NOT** be blanket-initialised (that erases saves). The only
  honest read of raw SRAM is through an integrity gate (magic + version +
  CRC, verify-before-copy — the `save` feature's job, not the allocator's).
- *Allocator constraints:* `[[claims.sram]]` is a `BytesClaim` (bytes,
  optional `at` pin, **no** `dma_source`), placed **program-wide** — one free
  list over the union of all features' claims across globals + every scene,
  deduped by feature name, emitted once in the globals inc with
  `_BANK`/`_LONG`/`_SIZE` companions at bank `$70`. `[init] zero` structurally
  cannot name an sram claim. Layout stability across builds is the save
  FORMAT's job (version/CRC makes a moved layout detected-invalid, never
  silently mis-read); a game wanting manual stability pins with `at`.

---

## Temporal + bandwidth classes (where split-mode & streaming live)

### DMA / HDMA channels — 8, modeled by `(register, band, frame-phase)` `fullsnes:562,588-603`
- **8 channels total, shared between GP-DMA and HDMA.** `MDMAEN` ($420B) starts
  GP-DMA; `HDMAEN` ($420C) arms HDMA. **A channel armed for HDMA must not be used
  for GP-DMA *in the same scanline*** `fullsnes:600`. Order ch0→ch7; **HDMA > DMA
  priority**; **HDMA runs even in forced blank** `fullsnes:588-590`.
- **Time-phase sharing is real and load-bearing.** GP-DMA runs in VBlank; HDMA runs
  during active display — they are **time-disjoint**, so *one channel can serve
  both in a frame.* The vendored reference scene
  (`vendor/probe_ref/src/probe_scene_ref.asm`) uses **CH0 for VBlank OAM GP-DMA
  and active-display COLDATA-R HDMA**. A "CH0/CH1 reserved for VBlank DMA"
  convention — the usual hand-written arrangement — is a **crude convention, not
  a hardware limit**: this allocator, by modeling the frame-phase, reclaims those
  channels for active-display HDMA.
- **The reference scene's live map — a full racing HDMA set on 7 channels:**
  CH0/1/2 = RGB COLDATA gradient · CH3 = BGMODE (mode split) · CH4 = TM ·
  CH5 = M7A/B · CH6 = M7C/D (perspective), with streaming + OAM as VBlank
  GP-DMA. (`racer`'s all-8 saturation is a *different* scene; it also shows the
  ad-hoc "OR in the gradient channel without a conflict check" hazard the
  allocator exists to kill.)
- *Allocator resource:* 8 channels; the collision unit is `(register, band,
  frame-phase, channel)`, **reusable across disjoint bands** (NON-REPEAT tables)
  **and disjoint phases** (VBlank GP-DMA vs active HDMA).

### GP-DMA cost — **8 master cycles / byte, fixed** `fullsnes:747`
- Cartridge/WRAM bytes transfer at a fixed 8 MC/byte. This is *the* bandwidth
  constant for the VBlank budget below.
- **Cannot cross a bank boundary:** A1B (bank, `$43x4`) is constant; only the low
  16 bits step `fullsnes:643`. → a single transfer stays within one 64 KB bank.
- Transfer-unit modes (`DMAPx` $43x0 bits 2-0) `fullsnes:618-630`:
  `0`=1 B (WRAM $2180) · `1`=2 B (VRAM $2118/19) · `2`=2 B same reg (OAM/CGRAM) ·
  `3`=4 B `xx,xx,xx+1,xx+1` (BGnxOFS, M7x) · `4`=4 B `xx..xx+3` (BGnSC, window).

### HDMA per-scanline `fullsnes:628,672-707`
- **One unit (≤4 bytes) per channel per scanline.** Table = `[line-count/repeat
  byte] + data` (direct) or `+ 16-bit ptr` (indirect); count byte `01-80h` = 1
  unit then pause, `81-FFh` = repeat. Arm HDMA in VBlank so the hardware reloads
  it at VBlank end; mid-frame arming needs manual register reload `fullsnes:712-741`.
- *Split-mode's model:* a split is a set of `(register, scanline-band, channel)`
  claims — e.g. an HDMA on BGMODE ($2105) toggling Mode 1↔Mode 7 at the band
  boundary, plus HDMA on M7A-D for the perspective floor. The allocator assigns
  channels and verifies no band-overlapping channel collision.

### VBlank bandwidth — the frame cycle budget
- NTSC: **262 scanlines/frame, ~1364 master cycles/line** (21.477 MHz ÷ 60 ÷ 262).
  Visible 224 (or 239) lines → **VBlank ≈ 38 lines ≈ 51.8 k MC** (224-line mode).
- At 8 MC/byte, that's a theoretical **~6.4 KB/VBlank**; realistic usable after
  register overhead + not overrunning active display is less, and the exact
  figure is **measured: 5,952 bytes** (`allocator/substrate.toml`,
  `vblank_usable_bytes` — `make measure` fails the build if it drifts). This
  is the number streaming + OAM + tilemap DMA are summed against. OAM DMA
  alone = 544 B; a Mode 7 row/col update = 128 map bytes, so 2 rows + 2 cols
  ≈ 512 B.
- CPU/frame: FastROM 3.58 MHz vs SlowROM 2.68 MHz → ~28-37 k cycles usable
  (`CLAUDE.md`). Perspective is **PPU-offloaded** (precomputed per-scanline pose LUT
  streamed through HDMA), so its steady-state CPU is ~nil: this repo's
  `split_h_2p_demo` runs **two** M7 perspective cameras + a 24-sprite inverse-LUT
  swarm at **60 fps for ~40 register stores/frame**
  (`test_split_h_2p_demo.py::test_cadence_true_60fps_in_situ`), vs a live-solve
  rail's measured **30 Hz**. **⟨measure⟩** the *combined*
  streaming+perspective+sprite path under a fast camera to confirm the pose-change
  amortization holds — the residual budget question, not the feature's steady-state cost.

### ROM banks
- LoROM/HiROM banked; **a DMA source cannot span a bank** (see above). The 256 KB
  4096² Mode 7 world map must be **bank-tiled** so any streamed row/col DMA stays in
  one bank. *Allocator sibling:* the ROM/asset layout tool checks this.

---

## The reference racing budget, recomputed with exact numbers

The whole combination is **already demonstrated, hand-built at 4096×4096** by
the vendored reference scene (`vendor/probe_ref/src/probe_scene_ref.asm`). The
table below is that scene's actual draw, not an estimate.

| Resource | Exact budget | Draw (reference scene) | Verdict |
|---|---|---|---|
| HDMA channels | **8** (`(register, band, phase)`) | gradient CH0/1/2 + BGMODE CH3 + TM CH4 + M7A/B CH5 + M7C/D CH6 = **7**; stream+OAM via VBlank GP-DMA (CH0 time-shares) | ✅ fits — this is its live map |
| VBlank DMA | **5,952 B** (measured pin — `allocator/substrate.toml`) | OAM 544 + stream ~512 (2 rows+2 cols ×128) + HUD ~300 ≈ **1.4 KB** | ✅ headroom to a fast camera |
| VRAM | 64 KB | Mode 7 **32 KB** + HUD BG/chr/font ~8–12 KB ≈ **~44 KB** | ✅ ~20 KB spare |
| CPU/frame | 28–37 k ⟨measure⟩ | **PPU-offloaded** persp (precomputed HDMA table) ≈ **0–1%** steady + stream + sprites | ✅ LUT+HDMA feature, not a CPU tax |

The verdict is **feasible and demonstrated.** Perspective is applied per-scanline by
the PPU's HDMA engine from a **precomputed, LUT-driven coefficient table** (sine LUT
+ linear `ZR_INC` slope), rebuilt only on a camera-pose change (the reference
scene's `pv_rebuild` runs *if angle changed*) — ~0–1%/frame steady, so streaming +
sprites + HUD have the rest of the frame. The RGB COLDATA gradient is a
**must-have and it fits** (CH0/1/2). The ⟨measure⟩ items are a **confirmation** of
the steady-state cost + the pose-change amortization on the real target — not a
go/no-go on an unproven combination. **The naive per-frame *software* perspective
rebuild (measured at 69–138%/frame) is the path to avoid, not the cost of the
feature.**

---

## What must be MEASURED (not estimated)

1. **Usable VBlank DMA bytes/frame** on the cycle-accurate target (the streaming
   bandwidth ceiling).
2. **CPU cycles/frame** for the racing worst case (fast camera: max row/col
   updates + perspective HDMA setup + sprite update).
3. The exact **Mode 7 streaming update cost** (cycles per row/col treadmill step).

Everything else here is fullsnes-exact and can be encoded directly into the
allocator's substrate model.
