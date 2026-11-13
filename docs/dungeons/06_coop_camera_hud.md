# 06 — Co-op, camera, HUD and flow

> DRAFT SPEC. The precedents and alternatives are weighed in research §E. The
> kit's split screen is refused here because it costs every BG layer
> (`research/kit_capabilities.md` §2).

## 1. Players

- P1 is pad 1 (`input`), P2 is pad 2 (`input2`). Both are proven in `room`.
- **Drop-in.** P2 presses Start at any time to join.
  - On a floor, P2 appears next to P1 with full HP and their saved kit.
  - P2 can leave from the pause menu. Leaving reverts the floor's enemy HP
    scaling for packs that have not spawned yet.
- **One-player play** uses the same code with hero 2 parked. The OAM slots
  are parked in place, as `brawler_obj` does it.

## 2. The camera: centroid plus leash

- **Target.** The midpoint of the live heroes, or the one hero when solo,
  offset 8 px upward so that more of the room ahead is visible.
- **Smoothing.** The camera moves 1/4 of the way to the target each frame.
  That is a shift, not a divide.
- **Clamp.** The camera is clamped to the floor's bounds, 0..(1024−256) in X
  and 0..(1024−224) in Y.
- **Leash, as a spread limit.** The leash does not test against the lagging
  camera. It tests the heroes' separation: |x1 − x2| ≤ 224 and
  |y1 − y2| ≤ 176. That is the screen size minus a 16 px inset on each side,
  less the 16 px HUD band in Y, and it is the condition under which the smoothed camera can always frame
  both.
  - A move that would break the limit is cancelled on that axis, for the
    hero who is moving.
  - If both heroes pull apart, both stop. That is the cue to regroup.
  - A **downed** hero still anchors the leash, so the partner cannot abandon
    them.
- **No warp needed.** Both heroes are always on screen on a resident floor,
  so research §E's warp-to-partner rule never triggers. A descend puts both
  heroes on the start marker. Together these solve the 1993 precedent's
  "stuck at a scroll edge" problem by construction (research §D).
- **Doors and the leash.** Room cells are 256×256 px, slightly larger than the
  screen, so the leash rarely binds inside a room. It does bind across a long
  corridor, which is intended: the pair crosses together.

## 3. HUD (BG3, top 2 rows, plus OBJ pips)

```
P1 ▮▮▮▮▮▮▮▯▯▯  ⟐12  B▪ L▫ R▪ X▪          P2 ▮▮▮▮▯▯▯▯▯▯  ⟐31  B▪ L▪ R▫ X▪
```

- **HP bar.** 10 cells of BG3 tiles with 8 fill levels each. Only changed
  cells are queued, 4 per frame (`bg_text`'s run queue).
- **Ammo count.** 2 digits.
- **Cooldown pips** for B (when the swing is in recovery), L, R and X.
  These are OBJ pips (the `room` `hud_pips` shape): 8 entries, no text
  traffic. That keeps the BG3 queue free for HP.
- **Lives.** Shown on the pause screen and the descend card only.
- **Damage taken** flashes the HP bar's palette for 4 f, using a BG3
  sub-palette swap.

## 4. Loot fairness

- **Gear** is instanced per player and tinted in the owner's OBJ palette:
  P1 cool blue, P2 amber. Only the owner can pick it up (04 §5).
- **Consumables** are shared.
- **Chests** hold one item per player.

Nobody fights over a drop, which is the genre reference's answer and the right
one for a couch (research §A).

## 5. Down, revive, lives

- **Down.** At 0 HP a hero is **downed**:
  - It lies in place and cannot act.
  - A 30-second timer starts (1,800 f, tick-scaled), shown as a ring of OBJ
    pips.
  - Enemies ignore downed heroes.
- **Revive.** The partner stands within 16 px and **holds A** for 90 frames
  (RALLY shortens this). The downed hero comes back at 50% HP with 60
  i-frames.
- **Timer expiry.** The party loses one **life**, and the hero respawns at
  the room's door with full HP.
- **Lives.** 3 per expedition, shared, shown on the descend card.
- **Both heroes down at once, or 0 lives left:** go to `results`. The
  expedition ends.
  - Equipped gear and the stash are kept.
  - The backpack contents of the run are lost.
  - That is the stakes.
- **Solo play.** A solo hero who goes down spends a life immediately and
  respawns at the door. There is no revive and no wait.

## 6. OAM rotation (new feature `obj_rotate`, small)

- Each frame, the OAM build starts its dynamic block (enemies, shots, drops,
  FX) at an index that advances by 7 (mod the block size).
- Heroes and the HUD pips stay pinned at the front, so they are never the
  ones that drop.
- **Test:** with rotation on, in a planted over-line scene (12 enemies on one
  row), every enemy is drawn in at least 1 of every 3 consecutive frames.
  Read OAM and STAT77 per frame.

## 7. Scene flow and the edges (`game.toml`)

| scene | composes (sketch) | notes |
|---|---|---|
| `title` | `bg_text`, `dgn_title_bg`, music | captures `run_seed` on Start |
| `camp` | `dgn_bg` (camp map), `dgn_obj`, `bg_text`, `dialog` | equip, salvage, spend sparks, pick the depth, save |
| `descend` | `bg_text`, `backdrop` | the card: "FLOOR n · SEED 1A2B · LIVES 3". The fade hides the generation |
| `floor` | `dgn_bg` (BG1 + the BG2 boss), `dgn_obj`, `obj_stream`, `obj_rotate`, `bg_text`, `dgn_logic`, `rng`, `input2` | the game |
| `inventory` | `bg_text`, `dgn_obj` (item icons) | full text rebuild under forced blank |
| `results` | `bg_text` | the run summary; goes to camp |

Edges are `fade`. `floor → inventory → floor` sets `resume` (02 §6).
