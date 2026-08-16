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


def main() -> int:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/audio/samples")
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"gen_audio_samples -> {outdir}")
    write_wav(outdir / "tri.wav", triangle_cycle())
    write_wav(outdir / "square25.wav", pulse_cycle())
    write_wav(outdir / "pluck.wav", karplus_strong())
    write_wav(outdir / "step.wav", noise_step())
    return 0


if __name__ == "__main__":
    sys.exit(main())
