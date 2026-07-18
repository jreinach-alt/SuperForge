# Clean-room policy — SuperForge SNES kit

> **Scope.** This is the **shipped** clean-room policy: it lives in the public kit
> and is the document every gate-tooling pointer resolves to
> (`tools/cleanroom_check.sh`, `tools/provenance_manifest.toml`,
> `tools/provenance_check.py`, `.claude/hooks/lint_gate.sh`, the Makefile). It is
> written **mechanism-only**: it describes the risk model and the controls WITHOUT
> naming any retail game title — so the doc itself is clean by the very rules it
> states (and passes the name tripwire + provenance gate that scan it). A fuller,
> example-naming companion lives in the parent/legacy tree and never materializes
> into the kit; if the two ever disagree, **this shipped doc is authoritative for
> the clean tree.**

## 1. Why this exists

The kit ships as a clean-room library of original SNES game templates ("rails"),
the 65816 engine, the `sf_*` macros, and the Python tooling behind them. "Clean
room" here means: **everything that ships is either original first-party work,
content we can regenerate from a committed generator, or third-party content we
are licensed to redistribute and have correctly attributed.**

A single hardcoded denylist of retail game/company names is **not** a sufficient
clean-room control. A name in a comment is a provenance *signal*, not an
infringement; a denylist can never be complete (it only catches names someone
thought to add); and the high-risk artifacts — copied/ripped **assets** and
**broken third-party attribution** — are not names at all. This policy replaces
the single weak control with a layered stack matched to the actual risks.

## 2. Risk model

| Risk | Severity | Why | Primary control |
|---|---|---|---|
| **Copied / ripped code or assets** (a retail game's tilemap, CHR, palette, music, or code dumped into the tree) | **HIGH** | Direct copyright infringement; the thing a clean-room library must never do. | Provenance gate (§4.1) — every blob must be regenerable or attributed; opaque blobs FAIL. |
| **Broken third-party attribution** (vendored CC BY / zlib / CC0 / etc. content with no `NOTICE` entry, or a dangling attribution-doc pointer) | **HIGH** | License *violation* even when redistribution is permitted — the permission is conditioned on attribution we failed to give. | Attribution check (§4.2) — every file declaring a third-party license must have a live `NOTICE` chain. |
| **Retail game-name identifiers / branding in the clean tree** (a rail, symbol, palette, or template named after a trademarked title; marketing copy implying affiliation/endorsement) | **MEDIUM** | Trademark / passing-off risk; also a strong *signal* that copied content may be near. | Name tripwire (§4.3) + publish-time semantic review (§4.4). |
| **Retail game-name *references* as mechanism/genre language** (a comment naming a retail title as shorthand for a technique; "Super Nintendo" as the platform) | **LOW (hygiene / provenance signal)** | Not infringement and not branding — descriptive fair reference. Worth minimizing for cleanliness and to keep the tripwire's signal-to-noise high. | Name tripwire flags it; reviewed exemptions in `tools/cleanroom_allow.txt`. |

The ordering is the whole point: the cheap name list spends its effort on the
LOW/MEDIUM rows, so the **HIGH** rows are owned by the complete controls (§4.1,
§4.2) and the semantic review (§4.4).

## 3. Rules for the clean tree

### FORBIDDEN in the clean (shipping) tree

- **Copied or derived code/assets** from any retail product — tilemaps, CHR,
  palettes, sample/BRR rips, sequenced music ripped from a game, or code lifted
  from a disassembly. Includes "I traced it" / "I re-typed it from the
  disassembly" — that is a derivative work, not clean-room.
- **Unattributed third-party content.** Vendoring is allowed (§ALLOWED) but only
  with a correct `NOTICE` entry and an intact pointer to any attribution doc.
- **Derivation language** that asserts a copied lineage: "ripped from", "ported
  from <a retail title>", "decompiled", "extracted from the ROM", "based on
  <a retail title>'s actual data", etc.
- **Retail game-name identifiers / branding**: file names, symbol names, template
  names, palette/asset names, or user-facing copy that use a trademarked title or
  imply affiliation/endorsement.

### ALLOWED in the clean tree

- **Mechanism-only descriptions.** Describe *how the hardware/technique works*,
  not *whose game it came from*: "a rotating Mode 7 floor with a per-frame moving
  pivot", "HOFS-per-scanline HDMA for a curved-road effect", "overhead
  run-and-gun". Prefer generic genre language over a title; if a title is
  genuinely the clearest shorthand it is a LOW-risk hygiene reference that the
  tripwire flags for a conscious reviewed exemption (§4.3).
- **Properly attributed third-party content.** Vendored components with their
  `NOTICE` entry and license intact (e.g. the Terrific Audio Driver ca65 API, the
  vendored Mode 7 Z-reciprocal LUT, the CC0 art packs).
- **The platform name** ("Super Nintendo" / "SNES") as a factual descriptor.

### ALLOWED only in non-shipping / legacy docs (NOT the clean tree)

- **Game-name research and comparison.** Notes that name retail titles to record
  *which technique a game used* belong in the parent/legacy tree, never in the
  shipping kit. The split tooling (`tools/scrub_split.py` / `tools/dryrun_split.sh`)
  carries the scrub vocabulary by design and is **removed** from the materialized
  tree — it never ships.

## 4. The control stack

Four layers, cheapest first. They are complementary, not redundant: the cheap
floor catches the obvious, the complete controls catch what a denylist cannot,
and the human/LLM review catches semantic cases a regex never will.

### 4.1 Provenance gate — the COMPLETE high-risk control

`tools/provenance_check.py` (`make provenance-check`), run on the **materialized**
tree. It enumerates **every** committed binary/asset blob and every large
`.byte`/`.word` data table, then requires each to match exactly one entry in
`tools/provenance_manifest.toml`, classified as:

- **`generator`** — reproducible from a committed generator. With a `regenerate`
  command, the gate re-runs it in a throwaway sandbox copy and **byte-diffs** the
  output against the committed bytes (the strong proof: the asset provably came
  from first-party code, not a rip). Converter-fed assets that read external art
  zips are coverage-only: the in-tree generator must exist and the asset carries
  its `; Generated by …` / `; cmd: …` header, with the source zip registered as
  third-party (the chain is still complete).
- **`third-party`** — vendored; verified to have a matching `NOTICE` entry.
- **`attested`** — a small allowlist of known-non-regenerable-but-attributed
  content (e.g. a hand-authored ROM-header template, a hand-authored sprite, or a
  vendored blob built by an external toolchain), each with a provenance `note`.
- **`artifact`** — a committed verification render/screenshot (proof of a build,
  not a shipping game asset).

**Any enumerated blob with no manifest entry FAILS.** This is the rip-detector,
and unlike a name list it is **complete by construction**: the guarantee is "only
assets we generate or properly attribute ship", which a denylist can never make.

### 4.2 Third-party attribution check

Folded into the provenance gate: every blob registered `third-party` names a
`notice_token` that must appear in `NOTICE`, and any attribution doc `NOTICE`
points to (e.g. `docs/THIRDPARTY.md`, a packaged `LICENSES.md`) must actually ship
in the materialized tree. A file that declares a third-party license (an SPDX tag,
a `CC BY` / `CC0` / `vendored` marker, a vendored-author token) with **no live
`NOTICE` chain** is a **HIGH-risk** finding — a license violation — and FAILS. The
gate **verifies** the chain; it does not author `NOTICE` / `THIRDPARTY` (that
content is owned elsewhere).

### 4.3 Name tripwire — the cheap FLOOR (NON-EXHAUSTIVE)

`tools/cleanroom_check.sh` (`make cleanroom-check`). A fast denylist scan of
committed text **and text members inside committed zips** for retail game /
company / eliminated-lineage names. It is explicitly **not** a completeness
guarantee — its own header and success message say so. Its value:

- It is nearly free, so it runs on every edit (the hook, §"Enforcement wiring")
  and in CI.
- A hit is a **provenance signal** ("a retail name is near — look for copied
  content"), which complements §4.1.
- The zip-internal scan closes the audit gap where names hide in a zip's
  `metadata.json` / README that the plain text grep walks past.

Legitimate mechanism/platform references a human has reviewed are exempted via
`tools/cleanroom_allow.txt` (`relpath<TAB>fixed-substring`, or `zip<TAB>member`
for an in-zip member). Adding an entry is a **conscious review act**; a growing
allowlist is a signal to *clean the tree*, not to keep exempting.

### 4.4 Publish-time semantic review — REQUIRED pre-public-release pass

A regex tripwire cannot catch a paraphrased derivation claim, a title referenced
without its exact denylisted spelling, or copied *structure* described in original
words. A semantic review at the publish step closes that gap. Unlike the
mechanical gates, it is **not** a code-time CI check — it is a deliberate human /
LLM-assisted review specified in §5, and it is **mandatory before any public
release**.

### Enforcement wiring

- `make check` runs `cleanroom-check` + `provenance-check` (alongside
  width/zp/test) — the mechanical gates actually RUN, closing the "gate existed
  but never fired" gap.
- `.claude/hooks/lint_gate.sh` invokes both at edit time for any change touching
  assets, data tables, the manifest, `NOTICE` / `THIRDPARTY`, or docs — SAFE-NO-OP
  if the `make` targets are absent (e.g. the bare staging overlay before
  materialization). The hook runs `provenance-check --no-regen` for speed; the
  full byte-diff regeneration runs in `make check` / CI.
- The publish-time semantic review (§5) runs at the **split/publish** step, over
  the materialized tree, before the tree is pushed public.

## 5. Publish-time semantic clean-room review (the fourth control, specified)

> **Status: REQUIRED before any public release.** This is a process, not a code
> comment. It is the third leg of the control stack alongside the two mechanical
> gates; the kit is not cleared for public release until it has been run on the
> materialized tree and its HIGH findings are resolved.

**When it runs.** At the **publish / split step** — after `tools/dryrun_split.sh`
materializes the clean tree and the mechanical gates (§4.1–§4.3) are green, and
**before** that materialized tree is pushed to any public remote. It reviews the
materialized tree (what actually ships), not the staging overlay or the parent
tree. It is re-run for every public release, not once.

**What it checks** — the semantic cases a regex and a byte-diff structurally
cannot catch:

- **Retail game-name references the wordlist misses** — paraphrases, misspellings,
  foreign-language titles, or a title referenced obliquely by description rather
  than by its denylisted spelling.
- **Derivation language asserting a copied lineage even when worded originally** —
  e.g. claims that the data matches a real cartridge's tables, or that something
  was reverse-engineered/extracted from a ROM, phrased so no exact denylist token
  appears.
- **Branding / affiliation implications** in user-facing copy (README, template
  descriptions) that suggest endorsement by a rights-holder.
- **Copied-looking code or assets that pass the mechanical gate** — an asset whose
  declared provenance is clean on paper but whose bytes/structure *read* like a rip
  (e.g. an "authored" image suspiciously resembling a known sprite sheet), or code
  whose structure mirrors a disassembly while being formally registered. The
  provenance manifest is the ground truth for "what claims to be what"; the
  reviewer cross-checks the claim against the artifact.

**How it runs.** A reviewer (human, optionally LLM-assisted) walks the
materialized tree using this document's FORBIDDEN / ALLOWED rules (§3) as the
rubric, with the provenance manifest as the ground-truth provenance map. It
produces a findings list of `(file, snippet, risk class, rationale)`:

- **Any HIGH finding blocks the release** until resolved (the file is fixed, the
  asset is removed, or the provenance is corrected and re-verified).
- **MEDIUM / LOW findings** are triaged: rename/remove branding, or record a
  conscious mechanism-reference exemption (and, for a recurring regex-catchable
  case, extend `tools/cleanroom_allow.txt` or the tripwire denylist so the cheap
  floor catches it next time).

If automated as a `make publish-review` / CI step, an LLM endpoint in the publish
pipeline (model, cost, reproducibility of a non-deterministic reviewer in a
blocking gate) is an owner/infra decision; the **manual review is the baseline
obligation** and does not depend on that automation.

**It is a backstop, not a substitute.** The provenance gate (§4.1) remains the
mechanical guarantee that only generated-or-attributed assets ship; the semantic
review catches the residue a regex and a byte-diff cannot. Passing the mechanical
gates is necessary but **not sufficient** for public release.

**Final legal sign-off.** This review is an engineering hygiene control; it is
**not legal advice and does not replace it.** Final clearance for public release —
including the authoritative wording of the rubric's risk classes and what a HIGH
finding legally obligates — rests with the maintainer's own legal counsel.

## 6. When a gate fires — what to do

- **`provenance-check` UNREGISTERED blob.** Do not allowlist reflexively. Find the
  generator and add a `regenerate` entry (best), or register/attribute it. If it
  is genuinely a rip, delete it.
- **`provenance-check` REGEN-MISMATCH.** The committed asset is stale or
  hand-edited vs its generator. Regenerate it (`PYTHONPATH=. python3 <gen>`) and
  commit the fresh bytes, or fix the generator.
- **`provenance-check` THIRD-PARTY-UNATTRIBUTED.** The `NOTICE` chain is broken.
  Add the missing `NOTICE` entry / restore the attribution doc.
- **`cleanroom-check` name hit.** Read the line. Branding / identifier / derivation
  → rename or remove. Mechanism / platform reference a human has cleared → add a
  reviewed `tools/cleanroom_allow.txt` entry. Retail name *inside a zip* → confirm
  no copied asset is present; if it is a documented fixture, exempt the specific
  zip member.
- **Publish-time semantic review HIGH finding.** Do not publish. Fix the file /
  remove the asset / correct the provenance and re-run the mechanical gates, then
  re-review, before the tree goes public.
