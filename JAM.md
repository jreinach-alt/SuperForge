# Jam standing

Where this kit stands against the SNES DEV Game Jam 2026's technical
restrictions, rule by rule, with the in-tree evidence for each.

**This file states only what the tree can show.** Where the tree holds no
evidence for a rule, it says *not verified* rather than claiming compliance.

**What is recorded here.**
[`docs/93`](docs/93_pal_region_investigation.md) §1 records the jam
(submissions 2026-07-31 to 2026-10-31) and, in its 2026-08-23 addendum, all
**eight** technical restrictions quoted from the jam's own page
(<https://itch.io/jam/snes-dev-game-jam-2026>) — the four file-checkable
ones, the two machine-level ones (§9), and the two authorship ones the
original measurement pass had nothing to hold a measurement against. Read
the jam's page before submitting anyway; the page, not this file, is the
rule list. `docs/93` §12 item 6 also records that whether the jury tests
any of this, and how, was never established.

## The eight rules

| # | rule as recorded | standing | evidence |
|---|---|---|---|
| 1 | **LoROM** | **met** | `vendor/rom/header.inc:20` emits `$FFD5 = $30` (LoROM + FastROM) for every image, and `docs/93` §1 read map mode `$30` back out of all 41 built images. The three linker configs under `vendor/rom/` are all LoROM. |
| 2 | **≤ 512 KB** | **met, at the cap** | Every game links to exactly 524,288 B — `docs/93` §1 records that it is *at* the ceiling, not under it. The ROM-size header byte is no longer hand-written: it is imported from the linker config that settles the size (`vendor/rom/lorom_512k.cfg:85`, `SF_LD_ROM_SIZE = $09`), and `tools/fix_checksum.py` **refuses to patch a header whose declared size is not the file's real length** on every build. Across every image this repo links, 2 declare `$05` and are 32,768 B, 54 declare `$09` and are 524,288 B, and none lies (`docs/97` §2.1, §2.3). |
| 3 | **No special chips** | **met** | `docs/93` §1. This tree models a plain cart: no coprocessor is declared, emulated or linked. |
| 4 | **No SRAM** — the wording is flat: "Game uses no SRAM" (`docs/93` §1 addendum, page read 2026-08-23) | **met by any submission that does not compose `save`** | Three library games — `platformer`, `room` and `rpg` — compose `engine/features/save` and are therefore **not valid jam entries as-is**; they are library demonstrations. An entry forked from one drops `save` from its `game.toml`, and the headers then truthfully declare cart type `$FFD6 = $00`, SRAM size `$FFD8 = $00` — both allocator-derived rather than hand-declared (`vendor/rom/header.inc:21-57`), so a header cannot claim SRAM the composition lacks. The other 34 games compose no `save` and already declare `$00`/`$00`. |
| 5 | **Game works on NTSC and PAL** | **met, and past the literal reading** | Two layers. *It runs on both:* the 37 games in the `docs/93` sweep boot, run and render under PAL with nothing crashing, hanging or corrupting, and no per-scanline table under-covering the taller frame. *It runs at the same speed on both:* **32 of the 39** compose `region` + `tick_scale` — every playable game, plus the two screen-effect rails — and the 30 of them inside the measured set hold a real-time parity band of **0.994–1.027** against the **0.832** an uncompensated game reads ([`docs/98`](docs/98_region_fleet_landing.md) §1). The two rails added since that sweep (`lakeside`, `heathaze`) compose the mechanism but are **not yet measured**, and this file says so rather than folding them into a band they were not in. The mechanism and the header corrections it rides on are [`docs/97`](docs/97_region_r0_landing.md); the requirement it answers is [`docs/94`](docs/94_region_support_spec.md) §2. The seven that do not compose it are all determinism trials whose frame-indexed sweeps are the thing under test — each states its reason in its own `game.toml` (`docs/98` §1, §4). |
| 6 | **Works on real hardware** | **NOT VERIFIED** | Nothing in this tree has run on an SNES, or on a second emulator. Every number anywhere in these docs is Mesen2's, cross-read against Mesen2's own source. `docs/93` §12, `docs/97` §6 item 5 and `docs/98` §6 each carry that limit forward unchanged rather than asserting past it. The design is hardware-shaped throughout — power-on RAM is random under test, PPU writes are blank-window only, DMA respects bank boundaries — but that is a discipline, not a measurement, and this row will stay *not verified* until somebody runs a cart. |
| 7 | **Done by yourself — no hacks, ripped music or graphics; free assets allowed** | **met for what the kit supplies; the rest is the entrant's** | Nothing in this tree is a hack or a rip: [`docs/92`](docs/92_provenance_audit.md) establishes what is not ours and how that was checked, and NOTICE plus the per-pack READMEs under `vendor/art/` carry each free asset's licence and author — exactly the "free assets" the rule allows, attribution ready to copy. What an entrant adds on top is theirs to keep clean. The rule does not say whether AI-assisted authorship counts as "done by yourself"; this kit is built for exactly that workflow, so ask the organisers rather than assume. |
| 8 | **Team projects allowed — state every member and their contribution** | **a submission-time obligation** | Nothing for the tree to prove; the crediting happens on the submission form. NOTICE and `docs/92` make the kit-side attribution copy-pasteable. |

## One thing a submission still has to decide

- **The destination byte.** `$FFD9` defaults to `$01` (North America) and is
  now overridable per game without editing a vendored file — `.ifndef
  SF_HDR_DEST` in `vendor/rom/header.inc:58`, exercised by
  `tests/test_rom_header.py`. Nothing in the tree overrides it. It declares a
  target market, not a runtime region: a cart composing `region` detects the
  console at boot and adapts, so `$01` stays truthful for a ROM meant for both
  machines. What reads the byte is a flashcart menu or a ROM-verification
  tool, neither of which is emulated here (`docs/97` §2.2).

## Re-checking any row

```bash
make bare-check                 # the landing gate: the whole gate block, from a clone of HEAD
python3 tools/rate_oracle.py --list          # the parity registry + every observable
python3 tools/rate_oracle.py scroller brawler --halves    # row 5's measurement, both regions
```
