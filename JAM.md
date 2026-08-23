# Jam standing

Where this kit stands against the SNES DEV Game Jam 2026's technical
restrictions, rule by rule, with the in-tree evidence for each.

**This file states only what the tree can show.** Where the tree holds no
evidence for a rule, it says *not verified* rather than claiming compliance.

**What is recorded here, and what is not.**
[`docs/93`](docs/93_pal_region_investigation.md) §1 records that the jam
(submissions 2026-07-31 to 2026-10-31) lists **eight** technical
restrictions, and it names **six** of them — the four file-checkable ones and
the two machine-level ones (§9). **The remaining two are not written down
anywhere in this tree**, so nothing below speaks to them. Read the jam's own
rule list before submitting; do not read this file as the rule list.
`docs/93` §12 item 6 also records that whether the jury tests any of this,
and how, was never established.

## The six recorded rules

| # | rule as recorded | standing | evidence |
|---|---|---|---|
| 1 | **LoROM** | **met** | `vendor/rom/header.inc:20` emits `$FFD5 = $30` (LoROM + FastROM) for every image, and `docs/93` §1 read map mode `$30` back out of all 41 built images. The three linker configs under `vendor/rom/` are all LoROM. |
| 2 | **≤ 512 KB** | **met, at the cap** | Every game links to exactly 524,288 B — `docs/93` §1 records that it is *at* the ceiling, not under it. The ROM-size header byte is no longer hand-written: it is imported from the linker config that settles the size (`vendor/rom/lorom_512k.cfg:85`, `SF_LD_ROM_SIZE = $09`), and `tools/fix_checksum.py` **refuses to patch a header whose declared size is not the file's real length** on every build. Across every image this repo links, 2 declare `$05` and are 32,768 B, 54 declare `$09` and are 524,288 B, and none lies (`docs/97` §2.1, §2.3). |
| 3 | **No special chips** | **met** | `docs/93` §1. This tree models a plain cart: no coprocessor is declared, emulated or linked. |
| 4 | **The SRAM rule** | **depends on the submission** | `docs/93` records this rule under two phrasings and resolves neither: §1 calls it "a known composition question", §9 lists it as "no SRAM". What the tree shows is that three games — `platformer`, `room` and `rpg` — compose `engine/features/save`, and that their headers say so truthfully: cart type `$FFD6 = $02`, SRAM size `$FFD8 = $01` (2 KB), both allocator-derived rather than hand-declared (`vendor/rom/header.inc:21-57`). A submission that composes `save` has to check the rule's actual wording; one that does not compose it declares `$00`/`$00` and the question does not arise. |
| 5 | **Game works on NTSC and PAL** | **met, and past the literal reading** | Two layers. *It runs on both:* all 37 games boot, run and render under PAL with nothing crashing, hanging or corrupting, and no per-scanline table under-covering the taller frame (`docs/93`). *It runs at the same speed on both:* 28 of the 37 — every playable game — compose `region` + `tick_scale` and measure a real-time parity band of **0.994–1.027** against the **0.832** an uncompensated game reads ([`docs/98`](docs/98_region_fleet_landing.md) §1). The mechanism and the header corrections it rides on are [`docs/97`](docs/97_region_r0_landing.md); the requirement it answers is [`docs/94`](docs/94_region_support_spec.md) §2. Of the nine that do not compose it, seven are determinism trials whose frame-indexed sweeps are the thing under test and two are deferred with the measurement that defers them — each states its reason in its own `game.toml` (`docs/98` §1, §4). |
| 6 | **Works on real hardware** | **NOT VERIFIED** | Nothing in this tree has run on an SNES, or on a second emulator. Every number anywhere in these docs is Mesen2's, cross-read against Mesen2's own source. `docs/93` §12, `docs/97` §6 item 5 and `docs/98` §6 each carry that limit forward unchanged rather than asserting past it. The design is hardware-shaped throughout — power-on RAM is random under test, PPU writes are blank-window only, DMA respects bank boundaries — but that is a discipline, not a measurement, and this row will stay *not verified* until somebody runs a cart. |

## Two things a submission still has to decide

- **The destination byte.** `$FFD9` defaults to `$01` (North America) and is
  now overridable per game without editing a vendored file — `.ifndef
  SF_HDR_DEST` in `vendor/rom/header.inc:58`, exercised by
  `tests/test_rom_header.py`. Nothing in the tree overrides it. It declares a
  target market, not a runtime region: a cart composing `region` detects the
  console at boot and adapts, so `$01` stays truthful for a ROM meant for both
  machines. What reads the byte is a flashcart menu or a ROM-verification
  tool, neither of which is emulated here (`docs/97` §2.2).
- **The two unrecorded restrictions.** See the note at the top. They are not
  a gap in this file — they are a gap in what the tree wrote down.

## Re-checking any row

```bash
make bare-check                 # the landing gate: the whole gate block, from a clone of HEAD
python3 tools/rate_oracle.py --list          # the parity registry + every observable
python3 tools/rate_oracle.py scroller brawler --halves    # row 5's measurement, both regions
```
