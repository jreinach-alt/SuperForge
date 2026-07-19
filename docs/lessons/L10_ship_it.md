# L10 — Ship it: header, checksum, PAL, flashcart, the jam profile

The last mile — where "runs in my emulator" becomes a release. Builds on
[L00](L00_what_a_snes_program_is.md); the jam rulebook mapping lives in
[`JAM.md`](../../JAM.md) — this lesson is the narrative pass over it.

## The idea

**The internal header.** The 32 bytes at `$FFC0-$FFDF`
(`infrastructure/rom_template/header.inc`) are what every emulator, flashcart
menu, and multicart shows about your ROM: a 21-byte title, map mode (`$30` =
LoROM + FastROM), cartridge type, ROM/SRAM sizes, region byte, checksum pair.
Set your game's title with **two coupled lines** before the header include:
`.define SF_HDR_TITLE "YOUR TITLE"` plus the numeric guard
`SF_HDR_TITLE_SET = 1` (ca65 can't conditionally test a string define, so the
guard symbol carries the opt-in; one line without the other is a hard build
error, never a silent default — `header.inc`'s comment explains). The
kit's default title is a placeholder — and shipping it is the single loudest
"nobody reviewed this" signal you can send: it is the first thing a curious
player sees in their flashcart menu, and the first thing a skeptic screenshots.

**Checksum.** The header ships placeholder checksum bytes (`$FFDC-$FFDF` =
`$FFFF/$0000`); emulators tolerate that, and flashcart/multicart tooling
usually fixes checksums itself. If you want a valid one, any ROM-header
utility writes it post-build (`header.inc` gotcha note; `JAM.md`).

**PAL.** Kit templates tie game logic to the frame interrupt, so on a 50 Hz
console everything frame-locked runs ~17% slower — uniformly, no glitches —
while music tempo holds (the sound CPU keeps its own region-independent
timers). That is how most licensed-era games behaved; either accept it or
scale per-frame velocities by 6/5 on PAL detection. The harness has a region
knob: `SF_REGION=pal` forces 50 Hz timing (`EXPECTATIONS.md`, `JAM.md`).

**Flashcart reality.** "Verified" in this kit means: boots under cycle-accurate
Mesen2 with power-on RAM *randomized* every boot, asserting on rendered
output. That discipline targets the classic works-in-emulator/dies-on-hardware
class — uninitialized reads that a zero-filling emulator hides, PPU writes
outside VBlank, DMA misuse. What it cannot promise: every console revision and
flashcart. The final word is a real console; if you have one, test on it — if
not, say so in your release notes and ask the community
(`EXPECTATIONS.md` → "Emulator vs hardware"). Honesty outperforms bluffing
with this audience, every time.

**The jam profile.** The default header declares 8 KB SRAM (so save-capable
link shapes need no variant) — but the SNES DEV Game Jam forbids SRAM. The kit
ships `header_jam.inc`: include it *instead of* `header.inc` and the cartridge
declares ROM-only. Don't pair it with `sf_save`/`sf_load` or the `*_sram` link
shapes — no-SRAM is the point. Everything else jam-relevant (LoROM, 512 KB
cap, no special chips, asset provenance, the dizworld CC BY credit if your ROM
uses the Mode 7 perspective path) is mapped rule-by-rule in `JAM.md`.

## See it live

```bash
make platformer
python3 - <<'EOF'
h = open("build/platformer.sfc", "rb").read()[0x7FC0:0x7FE0]
print("title    :", repr(h[:21].decode("ascii")))
print("map mode :", hex(h[0x15]), " cart:", hex(h[0x16]),
      " rom:", hex(h[0x17]), " sram:", hex(h[0x18]))
print("checksum : cmpl %02x%02x sum %02x%02x" % (h[0x1D], h[0x1C], h[0x1F], h[0x1E]))
EOF
SF_REGION=pal PYTHONPATH=. python3 - <<'EOF'
import time
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
WR = MemoryType.SnesWorkRam
r = MesenRunner()
r.load_rom("build/platformer.sfc", run_seconds=2.0)
print("PAL boot magic:", r.read_bytes(WR, 0xE000, 4))
f0 = r.read_u16(WR, 0x010C)          # engine frame counter
time.sleep(1.0)
print("frames in ~1s wall:", r.read_u16(WR, 0x010C) - f0, "(PAL ~50; NTSC ~60)")
r.stop()
EOF
```

Observed: the dump prints the 21-byte title field, `map mode: 0x30  cart: 0x2
rom: 0x8  sram: 0x3`, `checksum: cmpl ffff sum 0000` — read your own ROM's
title here before release; if it still says the kit default, stop. The PAL
boot prints `b'SFDB'` and `frames in ~1s wall: 51` — same ROM, genuinely
running at 50 Hz.

## Exercise

Make a jam-legal build and prove the header change:

```bash
cp templates/maze/main.asm /tmp/maze_main.bak
sed -i 's/^\.include "header.inc"/.include "header_jam.inc"/' templates/maze/main.asm
make maze && mv build/maze.sfc build/maze_jam.sfc
cp /tmp/maze_main.bak templates/maze/main.asm && make maze
python3 - <<'EOF'
a = open("build/maze.sfc", "rb").read(); b = open("build/maze_jam.sfc", "rb").read()
print([(hex(i), hex(a[i]), hex(b[i])) for i in range(len(a)) if a[i] != b[i]])
EOF
```

Verified outcome: exactly two bytes differ — `0x7fd6: 0x2 -> 0x0` (cartridge
type: ROM-only) and `0x7fd8: 0x3 -> 0x0` (SRAM size: none). Nothing else in
the image moves. That is the whole no-SRAM profile.

## What breaks if…

- **…you ship the placeholder title.** Nothing technical breaks — that's the
  trap. Your game boots fine and announces on every menu screen that nobody
  looked at the release. In a skeptical scene this costs more credibility than
  a real bug would; a hostile reviewer will lead with the screenshot.
- **…you enter a no-SRAM jam with the default header.** The header *declares*
  8 KB SRAM even if you never save — rule-checkers and multicart tooling read
  the declaration, not your intent. That's a disqualifiable technicality two
  header bytes fix.
- **…you never boot PAL before submitting.** "Works on NTSC and PAL" is a jam
  rule. The kit's pipeline is smoke-verified under both, but *your* tuning
  isn't: a jump timed to a 60 Hz music cue drifts (frames slow ~17%, music
  doesn't). One `SF_REGION=pal` playthrough finds it; skipping it means a PAL
  player finds it for you.
- **…you equate "boots in an emulator" with "works on hardware".** Most
  emulators zero-fill RAM; hardware boots to garbage. The kit randomizes
  power-on RAM in every test precisely to keep that class out — but the final
  word is silicon. Never claim hardware-verified without a flashcart run;
  claim "emulator-verified, hardware reports welcome" instead. It's also true.
- **…a checksum-strict pipeline meets your placeholder.** Rare, but real: some
  tooling validates `$FFDC-$FFDF`. If a flashcart menu flags your ROM, fix the
  checksum with any header utility — thirty seconds — rather than shipping an
  explanation.

End of the course — back to [the index](README.md), and before your first bad
debugging evening, read [`EXPECTATIONS.md`](../../EXPECTATIONS.md).
