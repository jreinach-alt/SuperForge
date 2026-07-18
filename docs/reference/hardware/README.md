# docs/reference/hardware/ — the Knowledge-base router (KB)

> The hardware-facts tier of the Knowledge realm. **Scope: the FULL SNES surface** — larger than what the engine implements (expert troubleshooters bring raw-SPC700, IRQ-raster, enhancement-chip problems). The engine is the clearly-marked *verified subset*.

**This dir is a router, not a fact dump.** It maps a topic → the engine source that exercises it (if any) → where the authoritative facts live, and tiers every fact by **confidence**: engine-verified > hardware-reference > honest-unknown.

**fullsnes is fetched, never committed** — `tools/setup.sh` pulls it into the git-ignored `docs/reference/fullsnes.htm` (same posture as the Mesen core). Enhancement-chip references (Super FX/SA-1) are fetched similarly.

**Assembled in B0/B3 per `docs/snes_homebrew_kb_assembly_plan.md`:** port the current repo's verified CLAUDE.md lessons (PPU encoding, OAM/16×16 layout, DAS re-arm, width-tracking, forced-blank/NMI, the HDMA latch, the per-memory access windows — VRAM vs CGRAM-also-HBlank vs OAM) with their Mesen-source citations, then run the **trap bank** as a QA pass so the KB itself carries no folklore.

**Status:** assembly pending (B0 plan); router structure here.
