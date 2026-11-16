# 13 — Character pipeline: animated figures from Blender

> DRAFT SPEC, 2026-11-16. **The gap:** SUPERFORGE GT's pipeline renders
> *rigid* models: cars on a turntable. Dungeons needs *figures that move*:
> a skinned body, an armature, actions keyed over time, three facing
> directions, and a weapon on its own layer. This file closes the gap as far
> as can be done **without Blender**, so the first Blender session spends its
> time rendering rather than deciding.

## 1. What is already done (pre-work, in the tree)

| artifact | what it settles | pinned by |
|---|---|---|
| `tools/dungeons/art/actions.toml` | camera (35° ortho, 16 px/unit, ×8 supersample), the sf-gt light rig, the **bone list**, proportions, and every action's frame count, game-frame holds and key poses. It is data, so the Blender script and the game read the same numbers | `test_actions_agree_with_the_combat_spec` (it checks the roll is 8 f and the swing's wind-up/active is 4/4 f, as 05 specifies) |
| `tools/dungeons/art/roles.toml` | the hero's **palette role table**: which material id becomes which palette index, ramp thresholds, vote weights | the loader refuses reserved, duplicate or mis-sized entries |
| `tools/dungeons/art/pixelate_actor.py` | the **render → sprite stage**, ported from sf-gt and generalised to role tables. It does cover, material vote, ramp step, despeckle, outline/shadow, and fit-or-refuse, and provides two metrics: `foot_row` (anchor) and `shimmer` (boiling) | `tests/test_dungeons_pixelate.py`: 8 tests on **synthetic data frames**, with no Blender needed |

Because a data frame is only three channels (sun, material id, sky), the
whole downstream half of the pipeline is testable today, and it is tested.
**What remains is the upstream half: the `bpy` script that writes those
frames** (§3).

## 2. Why script-built and keyed, not sculpted or captured

- **The provenance rule.** sf-gt's art bible: *"Nothing is downloaded: every
  asset is authored here, procedurally or by hand, and the script that made it
  is committed beside it."* A figure built and posed by a committed script
  satisfies it. A mesh from a generative 3D service does not (§6).
- **Determinism.** The same script, data and Blender version give the same
  pixels, so a retimed walk is a one-line TOML diff with a reviewable pixel
  diff.
- **The target is 16×16.** The detail a sculpt or motion capture buys is
  below one pixel. What reads at this size is **silhouette and exaggerated key
  poses**, and those are exactly what `actions.toml` holds.

## 3. The `bpy` script to write (track A1): `art/dungeons/render_actor.py`

The structure follows sf-gt's `render_car.py`
(`setup_scene` / `setup_compositor` / `set_camera` / `render_to`), with these
additions:

1. **`build_wanderer(kit)`.** A low-poly body from primitives:
   - a capsule torso
   - a sphere head with a hood shell
   - limb cylinders
   - a cone cloak
   - a satchel box and a lantern

   Each gets a material whose **pass index** is its `roles.toml` material id
   (2 = cloak, … 8 = detail). Ground shadow: a flat disc with material 1, in
   the shadow-catcher setup sf-gt used.
2. **`build_armature(rig)`.** Bones are named exactly as `actions.toml`'s
   `rig.bones`. Use automatic weights, plus a **cloak chain** (`cloak.1`,
   `cloak.2`) weighted to the cloak's lower rings. Parent the weapon mesh to
   `weapon`, on render layer 2.
3. **`key_action(name)`.** For each frame *i* of the action, set every
   `keys` channel to value *i* and insert a keyframe at timeline frame *i*.
   Rendering samples those frames directly, so no interpolation is involved.
   **Secondary motion:** `cloak.*` channels take the value from frame *i − 1*
   (wrapping), which is the "lag by one sample" note in the TOML.
4. **`set_direction(d)`.** Yaw the root (not the camera) to
   `camera.yaw_deg[d]`, so the light stays fixed relative to the screen.
5. **`render_frame(action, dir, i, layer)`.** Write
   `build/dgn_art_work/<model>_<action>_<dir>_<i>_<layer>.png` as the raw data
   frame. Use sf-gt's compositor recipe: view transform **Raw**, 8-bit,
   `dither_intensity = 0`, and the material index packed into G
   (`sf-gt:docs/fgt/dx_paper_cuts_cars.md`, "material-index pass … is
   exact").
6. **`project_anchor()`.** Project the `root` bone's head to the sprite pixel
   and write it to `build/dgn_art_work/anchors.json`. The pixelate stage
   compares this against `foot_row`.

**The smoke test first.** One frame: the wanderer, `walk` frame 0, `right`,
body layer, then through `pixelate_actor.pixelate` into a PNG. Look at it
before writing anything else.

## 4. Acceptance metrics (asserted by `sheets.py`, reported per run)

The numeric thresholds below are **first-pass guesses**, not measurements.
Recalibrate them on the first real renders and record the measured values
here, per CLAUDE.md rule 1.

| metric | rule | why |
|---|---|---|
| **fit** | every frame fits the 16×16 box; `pixelate` refuses otherwise | sf-gt's refuse-never-crop |
| **anchor drift** | `foot_row` is the same row for every grounded frame of an action in a direction. A drift of ≥ 1 px fails | otherwise the hero "slides" against the foot-box collision (05 §1) |
| **anchor agreement** | `foot_row` equals the projected `root` row ± 1 | the anchor is measured from the renders and published as data (sf-gt lesson) |
| **shimmer** | idle frames 0↔1 differ by 6–30 px | 0 = no motion; > 30 = the shading "boils" rather than moving |
| **walk legibility** | contact vs passing frames differ by ≥ 12 px in the leg rows | the stride must read at 1 px limbs |
| **role coverage** | every role in `roles.toml` appears in at least one frame of the model | an unused role is a palette slot wasted, or a material bound wrongly |
| **readability (judged)** | the lineup sheet: both heroes on each biome floor, captured **from the ROM** | 11 §6 |

## 5. The first Blender session's checklist (a fresh agent, cold)

1. **Install Blender 4.2 LTS** at `~/toolchains/blender` (sf-gt's path), and
   check `blender -b --factory-startup --version`. This container's
   permission policy blocked the download on 2026-11-16, so the session that
   runs this needs the owner's approval, or an environment whose setup script
   installs Blender. An environment setup script is the better fix: it runs
   once per fresh container.
2. Read sf-gt's `render_car.py` `setup_scene` / `setup_compositor` and its
   `dx_paper_cuts_cars.md` "Tooling" section (11 §1.1 summarises it).
3. Write `render_actor.py` steps 1 and 5 only. Run the smoke test (§3).
4. Add the armature (step 2) and `key_action` (step 3). Render `walk` × 3
   directions, then run pixelate and `sheets.py`.
5. Iterate on `actions.toml` values, not on code, until the §4 metrics pass
   and the lineup reads.
6. Hand the frames to the converter (11 §5 stage 6), so M3's streamed-slot
   test has real art.

## 6. Elyum and AI generation: what it can and cannot do here

**What it is** (as of 2026-11-16). Elyum is a credit-priced studio that fronts
dozens of third-party generative models. Its MCP server
(`https://elyum.ai/mcp`, OAuth or an `ek_mcp_…` bearer token, scopes
`read` / `generate` / `spend`) exposes **image, video, audio and avatar**
generation: `elyum_make_image`, `elyum_make_video`, `elyum_make_audio`,
`elyum_make_avatar`, plus `elyum_wait`, `elyum_keep` and `elyum_kill`.
**Its documented tools do not generate 3D meshes, rigs or animation.**
`elyum_models` lists the live catalogue, so check it once connected, but
nothing in its docs says 3D.

**Where it genuinely helps (reference, never shipped):**

| use | tool | feeds |
|---|---|---|
| **Concept and turnaround sheets** for the wanderer, each enemy and the Hollow Crown: front, side and back on a neutral background, so the `bpy` builder has proportions to match | `elyum_make_image` | `build_wanderer` (§3 step 1); 10 §5 designs |
| **Motion reference:** a short clip of a cloaked figure walking, rolling or swinging, to judge key poses before they are typed into `actions.toml` | `elyum_make_video` | `actions.toml` key values |
| **Palette mood boards** per biome | `elyum_make_image` | 10 §2–3, `roles.toml` / BG ramps |
| **Music mood sketches** of the three colours, to agree on direction before MML is written | `elyum_make_audio` | 12 §1. Never sampled, never shipped |

**Rules if it is connected:**

- **Nothing generated ships, and nothing generated is committed under
  `vendor/` or `art/`.** References live outside the repo, or under
  `docs/dungeons/refs/` marked **"reference — not an asset"**. That keeps the
  provenance rule intact: shipped art comes from committed scripts. (A
  generated image's licence and its training provenance are both outside what
  this tree can verify, which is a second reason for the rule.)
- **Originality applies to prompts too.** Never prompt with the film's or the
  scores' names (10, 12). Describe the mood instead. A reference that comes
  back recognisably like the film's creatures is discarded, not traced.
- **Token hygiene.** Use the OAuth flow, or an MCP token with scopes `read` +
  `generate` and **a daily cap**. Grant `spend` (keeping a render is the only
  charging action) only if the agent is meant to keep renders unattended.
  Never paste a token into the repo or the chat. In a Claude Code session,
  `claude mcp add` stores it in the user's config, outside the tree.

**Generative 3D with auto-rigging** (Tripo-, Meshy- or Hunyuan-class
services, which Elyum's docs do not offer) was considered and **not
recommended**:

- It breaks the committed-script provenance rule.
- Its outputs are not reproducible.
- Its auto-rigs need cleanup a 16 px target never repays.
- The material-id data pass, which the whole pixelate stage depends on, has to
  be re-authored on a generated mesh anyway.

If the owner wants it as **reference geometry** to trace proportions from,
the same "reference, not an asset" rule applies.
