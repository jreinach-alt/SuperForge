# Lesson 3 — Change something small

*Matches Try-it prompt 3. The task: one visible change to the library game
nearest your idea — a palette word, a gradient endpoint, a line of HUD text —
with before/after renders and a correct read of what the tests say back. The
edit is trivial; the lesson is what happens after it.*

## The loop

```bash
python3 tools/shot_<game>.py before/     # BEFORE renders, from the current ROM
# ...find every home of the value (below), then edit...
make <game>                              # rebuild — generators re-run off your edit
python3 tools/shot_<game>.py after/      # AFTER renders
python3 -m pytest tests/test_<game>*.py -q
```

## Before editing: find every writer and verifier of the value — by VALUE

A visual constant in this repo can live in **several files at once**: the
asset generator that bakes it, a game include that derives something from it,
and a test driver that states it as the expected picture. Edit one home and
the others now disagree — so before touching anything, grep for the **value**
in every spelling it could take (`$1C8D`, `0x1C8D`, the `(24, 8, 2)` channel
triple), not just for a name.

The worked example — the platformer's dusk sky:

| home | what it holds |
|---|---|
| `tools/gen_platformer_assets.py` | `DUSK_TOP` / `DUSK_BOT` — the ramp's endpoints, baked into the gradient blob |
| `game/platformer/platformer.inc` | `PLF_DUSK` — the ramp's *midpoint*, painted flat by the three menu scenes |
| `tests/plf_drive.py` | `PLF_DUSK` again — the test driver's own copy of that expectation |

Change the endpoints and the menus are showing a different sky than the round;
sync the include and the test driver still expects the old one. Each failing
test names the relationship it checks, so the chase is guided — but walking it
by value up front is one grep instead of two red test runs.

Generators also assert their own tuning constraints (endpoint agreement across
files, colour-math legality, step limits) — **read the generator's comments
before picking a value**; they teach the constraint cheaper than the assert
does.

## What the allocator says: usually nothing — and that is the answer

A content edit inside an already-declared claim moves **no** placement:
`build/<rail>/symbol_map.json` is byte-identical before vs after (diff it —
that is the demonstrable statement "layout unchanged"). Make's caching may not
even re-print "allocation OK" when no toml changed; silence means unchanged,
not skipped. The evidence your change *reached the artifact* is the ROM's
md5/checksum moving.

## Reading the tests after a deliberate look change

Three verdicts, three different meanings:

1. **Generator-as-oracle tests stay green** — they import the generator and
   verify the picture matches *whatever it now declares* (e.g.
   `test_the_dusk_sky_on_screen_is_the_declared_ramp` reads screen pixels
   against the ramp blob, plus a shape check that it still qualifies as a
   dusk). Green here means the NEW look renders faithfully.
2. **Companion-constant tests go red naming the other homes** — e.g.
   `test_the_menu_backdrop_is_the_ramps_own_midpoint`: the menus and the
   round are showing two different skies. Fix by syncing the homes you found
   above.
3. **Fixture-pinned tests go red BY DESIGN.**
   `test_the_dusk_ramp_matches_the_reference_ramp` compares the blob against
   `tests/fixtures/ref_dusk_grad.bin` — a reference captured off an
   independent implementation. The shipped game's look is a **contract**, not
   a preference, and this red is the discipline **working**: it exists so a
   look cannot drift silently. The fix is a *decision*, made with the owner —
   update or retire the fixture **together with** the look change, recording
   why in the commit — never loosening the assertion to sneak past it.

A red after a deliberate look change is not failure; an unexplained green
would be. Classify each red into the three bins above and report it that way.

## Closing the step

- Show before/after renders side by side, from the rebuilt binary.
- Name every file touched — including the companion constants — and say what
  the allocator had to say (usually: "nothing moved; md5 did").
- State whether the change is kept or reverted. The library's look is
  contract-pinned, so the default for a demo edit is revert-and-verify (tree
  clean, checksum back, pinning tests green); keeping it means updating the
  contract deliberately.
- Where a game's colours and art come from in the first place — which
  generator owns which blob — is mapped in
  [`docs/assets_story.md`](../assets_story.md).
