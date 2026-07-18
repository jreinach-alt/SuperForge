# docs/reference/hardware/ — hardware reference (fetched, not committed)

**This directory is nearly empty in git on purpose.** The authoritative SNES
hardware reference — fullsnes, the Nocash SNES specs — is **© Martin Korth,
all rights reserved**, so the kit never commits or redistributes it. Instead:

```bash
bash tools/setup.sh     # fetches fullsnes.htm HERE (git-ignored)
```

Setup pulls it from the canonical host (problemkaputt.de), falling back to
the Internet Archive's snapshot of the same URL if that host is unreachable.
After setup, `docs/reference/fullsnes.htm` sits next to this file for local
use. Same fetched-never-committed posture as the Mesen2 emulator core — see
`NOTICE` for the licensing picture.

## Where the kit's own hardware knowledge lives

The curated, kit-verified knowledge is deliberately kept where you'll hit it
in practice, not duplicated here:

| Question shape | Go to |
|---|---|
| "Something misbehaves" (black screen, flicker, tearing, silence) | `docs/troubleshooting.md` — symptom-indexed fixes |
| "My instincts are Unity/Godot-shaped" | `docs/snes_vs_modern_engines.md` — the idiom guardrail |
| Hardware Q&A the kit can answer with confidence tiers | `scenarios/knowledge.md` — the knowledge catalog |
| Per-genre deep dives (Mode 7 math, sprite projection, streaming, splits) | `docs/guides/` |
| Register-level ground truth | the fetched `fullsnes.htm` (above) |

**Confidence discipline** (for agents and humans alike): engine-verified facts
outrank hardware-reference readings, which outrank inference — and "I don't
know yet" beats folklore. When the kit's docs and fullsnes disagree, trust
the emulator: boot a test ROM and measure.

A richer curated fact-bank in this directory is future work; what ships today
is the router above plus the fetch.
