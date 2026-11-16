# 09 — Open questions (the owner's decisions)

> Each question has a recommendation, so work can start under it. An answer
> changes the named sections. Nothing open here blocks M0–M5.

## Open

| # | question | options | recommendation | affects |
|---|---|---|---|---|
| **Q8** | **Where is Fable's existing Blender → SuperForge intake?** It is not in `SuperForge` or `SuperForge-Private`, and attaching the owner's other repos to this session was refused. | point to the repo/branch, or rebuild it from 11 | point to it. 11 §6 says how to reconcile its choices with the game's projection | 11, 08 A1/A2 |
| **Q9** | **Sample policy for the orchestra.** The house rule (2026-07-30) is that every sample is synthesised. | (a) keep it: a synth-orchestra, which suits the 80s hybrid sound; (b) allow CC0-licensed orchestral samples with per-pack provenance, as `vendor/art/` already does for art | **(a)** first. Audition the synthesised brass and choir (12 §6 step 1) before deciding | 12 §3 |
| **Q3** | Difficulty selection. | (a) depth only (threat = floor); (b) depth + 3 modes, as the genre reference does | (a) at tier M. Depth already is the threat dial | 04 §3 |
| **Q4** | Inventory as a scene vs an in-scene overlay. | A scene needs global floor state (chosen, about 5 KB WRAM); an overlay needs about 50 frames of 4-cell BG3 writes per open | scene | 02 §6 |
| **Q5** | Hero sprite size. | 16×16 (chosen) vs 32×32 (the kit's knight precedent) | 16×16. 32×32 heroes double every per-line cost and the streamed DMA. Blender renders downscale cleanly to either, so this stays cheap to revisit | 02 §3 |
| **Q6** | Names. | "SuperForge Dungeons", "Lumenvale", "the Unwriting", "the Underleaf", biome and enemy names are all **working names**. Check for clashes with existing titles before release | keep while building; clear before M10 | 10 |
| **Q7** | Seed entry (daily runs). | tier C | defer | 03 §2.3 |
| **Q10** | The Unwriting as advancing pressure (10 §4). | tier S as specced, or drop it | keep it at tier S. It is the theme made into a mechanic, and it costs one cell queue plus one driver command | 10 §4, 12 §2 |

## Decided

| # | decision | date |
|---|---|---|
| Q1 | **Battery save.** Not a jam game, so the no-SRAM rule does not apply. The `save` payload is raised to 144 B (02 §2.1) | 2026-11-16 |
| Q2 | **Art is modelled in Blender and prerendered** (11). The CC0 placeholders serve until the renders land | 2026-11-16 |
| — | **Visual theme:** borrows mood from a 1984 storybook-void fantasy film, as evocation, not reproduction (10) | 2026-11-16 |
| — | **Music:** 80s orchestral, influenced by two early-80s fantasy scores (barbarian epic; goblin maze), as technique, not quotation (12) | 2026-11-16 |
