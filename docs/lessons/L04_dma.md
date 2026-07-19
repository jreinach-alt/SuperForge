# L04 — DMA, and why you can't touch VRAM mid-frame

## The idea

VRAM, CGRAM, and OAM are not in your address space. The CPU reaches them only
through PPU **ports** (`$2118/19` for VRAM, `$2122` for CGRAM, `$2104` for
OAM) — and during the visible frame the PPU itself is reading those memories
sixty times a second to build the picture. Writes from the CPU while the
display is active are ignored or land corrupted (hardware-reference; the
address latches advance even when the data doesn't stick, so the damage is
rarely a clean no-op). The safe windows are VBlank (L01) and **forced
blank** — screen switched off, PPU idle, which is why boot-time loading
happens there.

VBlank is short, and pushing bytes through a port with CPU loads/stores is
slow. The hardware's answer is **DMA**: eight channels of dedicated copy
machinery that stream bytes from CPU-visible memory into a PPU port at one
byte every eight master clocks, ~2.7 MB/s — far faster than any CPU loop
(hardware-reference). The kit's engine builds its whole rendering contract on
that: during the frame, nothing writes the PPU. Sprites resolve into a
shadow OAM in WRAM; bulk uploads enqueue into a DMA queue (`$0200`, up to 32
entries); then the NMI handler drains the queue and DMAs the shadow OAM
across, all inside VBlank, under a byte budget the engine enforces
(engine-verified: `VBLANK_DMA_BUDGET = 5500` bytes conservative default,
`engine/engine_state.inc`). Your code draws into RAM; VBlank publishes it.

## See it live

Two probes on ROMs you already built (L00, L01). First: boot-time DMA.
hello_world's tile bytes live in ROM at `sprite_tile:`; `sf_load_obj_tile`
DMA'd them into VRAM under forced blank. Read them back out of VRAM (the L02
probe): the 32 bytes match the source rows exactly. The screen never saw the
upload happen — it was off.

Second: the per-frame pipeline, made visible. Game state (WRAM) updates
during the frame; hardware OAM only changes when the *next* VBlank's DMA
publishes it. Step frames and watch the two run one frame apart:

```bash
python3 - <<'EOF'
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom("build/move_sprite.sfc", run_seconds=2.0)

def wram_x():
    lo, hi = r.read_bytes(MemoryType.SnesWorkRam, 0x32, 2)  # PLAYER_X
    return lo | (hi << 8)
def oam_x():
    return r.read_bytes(MemoryType.SnesSpriteRam, 0, 1)[0]

r.debug_break()
print(f"parked : WRAM X={wram_x()}  OAM X={oam_x()}")
r.frame_step(1, right=True)
print(f"step 1 : WRAM X={wram_x()}  OAM X={oam_x()}")
r.frame_step(1, right=True)
print(f"step 2 : WRAM X={wram_x()}  OAM X={oam_x()}")
r.frame_step(1)
print(f"step 3 : WRAM X={wram_x()}  OAM X={oam_x()}")
r.stop()
EOF
```

Observed:

    parked : WRAM X=120  OAM X=120
    step 1 : WRAM X=122  OAM X=120
    step 2 : WRAM X=124  OAM X=122
    step 3 : WRAM X=124  OAM X=124

The hardware copy trails the game state by exactly one frame, every frame:
that lag *is* the shadow-then-DMA pipeline, measured. (It is also why tests
that assert OAM allow one settle frame after changing input.)

## Exercise

Prove the VRAM layout rule from L02 (OBJ tile N at VRAM word N*16). In
`examples/hello_world/main.asm` change the upload and the draw from tile 1 to
tile 2 (`sf_load_obj_tile 2, sprite_tile` / `spr #2, ...`), rebuild, and
re-read VRAM at byte 32 and byte 64. Verified outcome: byte 32 now reads
zeros, the `FF 00` pattern sits at byte 64, and OAM record 0 shows tile 2 —
same square on screen, new address in memory. Revert when done.

## What breaks if…

**…you write VRAM mid-frame anyway.** The write is silently dropped or
misplaced: tiles half-upload, tilemap cells go stale, and — the cruel part —
some emulators are more forgiving than hardware, so it can "work" on your
machine and shred on a console. The kit's stance: tests run cycle-accurate,
and every engine upload path goes through the VBlank queue or forced blank.
Symptom index: [`../troubleshooting.md`](../troubleshooting.md) ("Tilemap I
built is empty / partially wiped", "Sprite shows the WRONG GRAPHIC").

**…a transfer crosses a 64 KB bank boundary.** DMA source addressing wraps
within the bank instead of carrying into the next one, so the tail of the
transfer reads the wrong bytes (hardware-reference). The kit's asset layout
and link shapes are arranged so shipped transfers never straddle a bank; keep
that habit when you add data.

**…VBlank runs out.** A DMA that doesn't finish before the display restarts
sprays writes into the visible frame — flicker or a torn band at the top of
the screen. This is why the engine meters the queue against
`VBLANK_DMA_BUDGET` instead of hoping: over-budget work waits for the next
frame. Streaming whole worlds through that same small window is its own
discipline — the streaming rails' guides (`docs/guides/`) show the measured
version, and L09 has the budget arithmetic.

Next: [L05 — Backgrounds, scrolling, cameras](L05_backgrounds_scrolling.md):
what all this machinery is usually moving.
