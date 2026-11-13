# 09 — Open questions (the owner's decisions)

> Each question has a recommendation, so work can start under it. An answer
> changes the named sections. Nothing here blocks M0–M5.

| # | question | options | recommendation | affects |
|---|---|---|---|---|
| **Q1** | **Persistence.** The SNES DEV jam forbids SRAM (`JAM.md` rule 4), and the 2026 jam closed on 2026-10-31. | (a) battery save, with the `save` payload raised from 24 B to fit 2 × 20 B kits + a 96 B stash + run state ≈ 160 B; (b) no persistence, runs are self-contained; (c) a password: about 40 B of kit is too long, so it would carry only gear score + 2 uniques | **(a)**, unless a future jam entry is planned. Then build a `JAM=1` variant with (b), since the allocator derives the header bytes either way | 01 §3, 02 §2, M7 |
| **Q2** | Hero art. | (a) commission; (b) CC0 packs (`vendor/art/dungeon_sprites` covers the hero and one enemy); (c) the owner draws | (b) through M5, then (a) or (c). Pipeline-identical | 07 |
| **Q3** | Difficulty selection. | (a) depth only (threat = floor); (b) depth + 3 modes, as the reference does | (a) at tier M. Depth already is the threat dial | 04 §3 |
| **Q4** | Inventory as a scene vs an in-scene overlay. | A scene needs global floor state (chosen, about 5 KB WRAM); an overlay needs about 50 frames of 4-cell BG3 writes per open | scene | 02 §6 |
| **Q5** | Hero sprite size. | 16×16 (chosen) vs 32×32 (the kit's knight precedent) | 16×16. 32×32 heroes double every per-line cost and the streamed DMA | 02 §3 |
| **Q6** | Name. | "SuperForge Dungeons" is a working title, and the cleanroom check is happy with it | keep, or choose before M10 | — |
| **Q7** | Seed entry (daily runs). | tier C | defer | 03 §2.3 |
