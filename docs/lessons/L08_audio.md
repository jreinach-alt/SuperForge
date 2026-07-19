# L08 — Audio: the second computer in the box

Why most homebrew ships silent, and how not to.
Builds on [L00 (what a SNES program is)](L00_what_a_snes_program_is.md) and
[L01 (the frame)](L01_the_frame.md).

## The idea

The SNES sound system is a **whole second computer**: an SPC700 CPU with its
own 64 KB of ARAM, its own clock (its own resonator, ~0.25% off the CPU's —
sync on the handshake protocol, never on counted CPU cycles:
`scenarios/knowledge.md`), and a DSP with 8 voices. Your 65816 cannot touch
ARAM or the DSP at all — it talks through four 8-bit I/O ports, full stop. At
power-on the SPC700 runs a tiny boot ROM (the IPL) waiting for you to upload a
*program*. No program, no sound. Ever.

And samples aren't WAVs: the DSP plays **BRR** — 9-byte blocks encoding 16
samples as 4-bit residues plus a header byte (shift, filter, loop/end flags) —
so every sound must be converted, and the echo buffer eats ARAM you thought
you had (hardware-reference; the driver abstracts this —
`scenarios/knowledge.md` AX2/TD2).

That is why homebrew ships silent: sound needs a second program, a second
toolchain, and a music format — none of it shared with the graphics work, all
of it easy to defer forever. The kit's honest status today: **two rails play
sound** (the platformer: music + SFX; the rpg: music); the rest are silent by
design while wiring lands (`EXPECTATIONS.md` → "Audio ships where it is
wired, not everywhere"). The subsystem itself is verified the only way audio
can be — on *recorded output*: the gate records a WAV and asserts on its
energy, because a status flag can read "playing" while the speakers stay dead.

The kit's front door is `lib/macros/sf_audio.inc` over the vendored
**Terrific Audio Driver** (TAD — see `NOTICE`; ship your own music by
rebuilding the song blob with `tad-compiler`). The wiring pattern, copyable from
`templates/platformer/main.asm`:

1. **Build shape**: an audio ROM links a `lorom_tad*.cfg` plus two extra
   objects — the template's `; LDCFG:` sentinel handles it (`sf_audio.inc`
   header has the full list).
2. **`sf_audio_init` once at boot**, *before* NMI enable, while the SPC700 is
   still in IPL state — and never again on a soft restart.
3. **`sf_audio_tick` every frame, every scene.** Song loads are asynchronous
   and commands queue; the tick is the pump. No tick, no sound.
4. **`sf_music #Song::x` / `sf_sfx #SFX::y`** — IDs from the compiled set's
   enums (`assets/audio/tad_audio_enums.inc`).

## See it live

```bash
make platformer
PYTHONPATH=. python3 - <<'EOF'
import math, struct, wave
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
WR = MemoryType.SnesWorkRam
r = MesenRunner(enable_audio=True)
r.load_rom("build/platformer.sfc", run_seconds=2.0)  # title song loads async
print("TAD status:", hex(r.read_u16(WR, 0x016A) & 0xFF))  # $01 = playing
r.start_audio_recording("/tmp/title.wav")
r.run_frames(150)
r.stop_audio_recording()
w = wave.open("/tmp/title.wav"); n = w.getnframes()
s = struct.unpack(f"<{n * w.getnchannels()}h", w.readframes(n)); w.close()
print("music RMS:", round(math.sqrt(sum(v * v for v in s) / len(s)), 1))
r.stop()
EOF
make audioroms && python -m pytest tests/test_audio.py -q  # the WAV-energy gate
```

Observed: `TAD status: 0x1`, `music RMS: 1581.5` — real energy in a real
recording, not a flag. (Open `/tmp/title.wav` and listen.) The gate run ends
`1 passed` — it drives play → pause (energy collapses) → resume → SFX-over-
paused-song, all asserted on WAV RMS.

## Exercise

Change the gameplay song. In `templates/platformer/main.asm`, `scene_game`
ends with `sf_music #Song::ode_to_joy` — swap it to `#Song::chords_transpose`
(the set's enums are in `assets/audio/tad_audio_enums.inc`), rebuild, rerun
the snippet but press START first (`r.debug_break(); r.frame_step(2,
start=True); r.debug_resume(); r.run_frames(120)` before recording). Verified
outcome: status still `$01`, RMS still four digits (measured 1361.2), and the
tune in the WAV is audibly the other song.

## What breaks if…

- **…you call `sf_audio_init` late, twice, or on a soft restart.** The
  handshake assumes IPL state; a live driver isn't in it. Best case silence,
  worst case a boot hang waiting on a port that will never answer. Scene
  transitions switch *songs* (`sf_music`), never re-init — the platformer's
  SOFT-RESTART CONTRACT comment is the pattern.
- **…you drop `sf_audio_tick` (or gate it on game state).** Song loads stall
  mid-transfer and SFX sit queued forever. The status mirror at `$016A` shows
  `$02` (loading) indefinitely — that read is your first probe when "music
  never starts".
- **…you queue an SFX right before a long stall.** Delivery rides the tick: a
  coin sound queued just before a scene init's ~1800-call level load plays
  *after* the load. Tick once right after queueing when timing matters
  (`sf_sfx` header note — this bit a real template).
- **…you link the default `lorom.cfg` out of habit.** The TAD banks and BSS
  don't exist there; the build fails at link (or, with a hand-rolled cfg,
  boots silent). Copy the flagship's `; LDCFG:` sentinel line.
- **…you trust `TAD_STATUS` as proof of audibility.** After `sf_music_stop`
  the *silent song* plays — status settles at `$01` with a flat WAV
  (`sf_audio.inc` caveat). Status answers "is the driver alive", the recording
  answers "does it make sound". Assert on the recording.

Next: [L09 — budgets & limits](L09_budgets_limits.md).
