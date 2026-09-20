#!/usr/bin/env python3
"""Generate the instrument/SFX samples — procedurally, stdlib only.

Provenance: every byte of every wav is synthesised by this script from the
constants below (project decision 2026-07-30: no reference-sourced sample
material; generate instead). Deterministic — the one stochastic source
(Karplus-Strong's initial buffer, the noise burst) uses a fixed-seed
`random.Random`, so re-running reproduces byte-identical wavs.

Outputs (16-bit mono PCM, written to the directory given as argv[1]):

  tri.wav       64-sample single-cycle triangle  -> looped bass instrument
  square25.wav  64-sample single-cycle 25% pulse -> looped lead instrument
  pluck.wav     Karplus-Strong pluck, 0.4 s      -> one-shot melodic accent
  step.wav      filtered noise burst, 0.1 s      -> footstep SFX
  bell.wav      64-sample single-cycle bell      -> pickup / chime SFX
  saw.wav       64-sample band-limited sawtooth  -> laser / engine SFX
  kick.wav      pitch-dropping sine, 0.16 s      -> song kick drum

The last two exist because the SFX set needs TIMBRES the four instruments
above cannot reach: `square_lead` is a 25 % pulse (hollow, buzzy) and `step`
is a heavily low-passed noise burst shaped for a footstep. A bright partial
stack and a full-spectrum saw are what a pickup and a laser actually want.
Both are single-cycle LOOPS -- 64 samples, 4 BRR blocks, ~36 B of audio data
each -- so the whole timbral gain costs less than one tenth of a one-shot.

Design constraints that shaped these:
  * BRR encodes 16 samples per 9 bytes -- single-cycle loops of exactly 64
    samples (4 BRR blocks) keep the whole instrument set tiny.
  * Peak amplitude is capped at 0.72 full-scale: the S-DSP's 4-point
    Gaussian interpolator can overflow on hot samples (the known hardware
    quirk TAD's `ignore_gaussian_overflow` flag exists for); staying under
    ~3/4 FS avoids ever needing that flag.
  * The pulse cycle is mean-centred to remove its DC offset.
"""
import math
import random
import struct
import sys
import wave
from pathlib import Path

RATE = 16000
PEAK = 0.72
AMP = int(32767 * PEAK)


def write_wav(path: Path, samples: list[int]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    print(f"  {path.name}: {len(samples)} samples, {path.stat().st_size} B")


def clamp(x: float) -> int:
    return max(-AMP, min(AMP, int(round(x))))


def triangle_cycle(n: int = 64) -> list[int]:
    # rises -1 -> +1 over the first half, falls back over the second
    out = []
    for i in range(n):
        ph = i / n
        v = 4 * ph - 1 if ph < 0.5 else 3 - 4 * ph
        out.append(clamp(v * AMP))
    return out


def pulse_cycle(duty: float = 0.25, n: int = 64) -> list[int]:
    raw = [1.0 if (i / n) < duty else -1.0 for i in range(n)]
    mean = sum(raw) / n                      # remove the duty-cycle DC offset
    return [clamp((v - mean) * AMP * 0.8) for v in raw]


def bell_cycle(n: int = 64) -> list[int]:
    """A bright, glassy cycle: a fundamental under a thinning partial stack.

    Deterministic by construction -- no RNG, just a fixed harmonic series.
    Normalised by its own peak so the result sits exactly at PEAK full-scale.
    """
    parts = ((1, 1.0), (2, 0.60), (3, 0.35), (5, 0.22), (7, 0.12))
    raw = [sum(a * math.sin(h * 2 * math.pi * i / n) for h, a in parts)
           for i in range(n)]
    peak = max(abs(v) for v in raw)
    return [clamp(v / peak * AMP) for v in raw]


def saw_cycle(n: int = 64, harmonics: int = 16) -> list[int]:
    """A BAND-LIMITED sawtooth -- the buzz a laser/engine wants.

    Summing 1/h to `harmonics` rather than drawing the naive ramp keeps every
    partial below the 64-sample cycle's Nyquist (harmonic 32), so the loop
    carries no content that would alias when the S-DSP resamples it.
    """
    raw = [sum(math.sin(h * 2 * math.pi * i / n) / h
               for h in range(1, harmonics + 1)) for i in range(n)]
    peak = max(abs(v) for v in raw)
    return [clamp(v / peak * AMP * 0.9) for v in raw]


def karplus_strong(freq: float = 220.0, seconds: float = 0.4,
                   damp: float = 0.996) -> list[int]:
    rng = random.Random(0x51EB)
    period = int(RATE / freq)
    buf = [rng.uniform(-1.0, 1.0) for _ in range(period)]
    out: list[float] = []
    for _ in range(int(RATE * seconds)):
        v = buf.pop(0)
        avg = damp * 0.5 * (v + buf[0])
        buf.append(avg)
        out.append(v)
    # short linear fade-out so the one-shot ends at zero, no click
    fade = int(0.01 * RATE)
    for i in range(fade):
        out[-fade + i] *= 1.0 - (i + 1) / fade
    return [clamp(v * AMP) for v in out]


def noise_step(seconds: float = 0.1) -> list[int]:
    rng = random.Random(0xF007)
    n = int(RATE * seconds)
    out, lp = [], 0.0
    for i in range(n):
        # one-pole lowpass over white noise, exponential decay envelope
        lp += 0.25 * (rng.uniform(-1.0, 1.0) - lp)
        env = math.exp(-9.0 * i / n)
        out.append(clamp(lp * env * AMP * 1.4))
    return out


def drum_kick(seconds: float = 0.16) -> list[int]:
    """Pitch-dropping sine with a click transient -- a one-shot kick drum.

    A single-cycle loop cannot be a kick: the sound IS the pitch envelope, a
    fast drop from ~160 Hz to ~45 Hz. It exists so the song can have a bottom
    end WITHOUT the S-DSP noise generator -- there is only one, and the driver
    zeroes a music channel's volume whenever a sound effect wants noise
    (audio-driver.asm, `nonShadow_music` under `SfxNoise`), so a noise-based
    kick would drop out under every explosion.

    Normalised rather than clamped: the click and the body sum past full scale,
    and clipping a kick is audible as a rasp.
    """
    rng = random.Random(0x4B1C)
    n = int(RATE * seconds)
    click = int(0.004 * RATE)
    out, phase = [], 0.0
    for i in range(n):
        t = i / n
        phase += 2.0 * math.pi * (45.0 + 115.0 * math.exp(-14.0 * t)) / RATE
        v = math.sin(phase) * math.exp(-5.5 * t)
        if i < click:
            v += rng.uniform(-0.55, 0.55) * (1.0 - i / click)
        out.append(v)
    peak = max(abs(v) for v in out)
    return [clamp(v / peak * AMP) for v in out]


def main() -> int:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/audio/samples")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"gen_audio_samples -> {outdir}")
    write_wav(outdir / "tri.wav", triangle_cycle())
    write_wav(outdir / "square25.wav", pulse_cycle())
    write_wav(outdir / "pluck.wav", karplus_strong())
    write_wav(outdir / "step.wav", noise_step())
    write_wav(outdir / "bell.wav", bell_cycle())
    write_wav(outdir / "saw.wav", saw_cycle())
    write_wav(outdir / "kick.wav", drum_kick())
    return 0


if __name__ == "__main__":
    sys.exit(main())
