# sf_split_h C-horiz PERSPECTIVE series (PR #223) — INDEPENDENT REVIEW

- **Tree under review:** PR #223 head `8466408` (`claude/persp-final-audit`) → base
  `origin/claude/split-mode-spec` (`8781d17`). Diff: 22 files, +4171/−22.
- **Role:** independent post-audit review, fresh session, no involvement in the build or
  the prior audit series. Everything re-verified on the emulator (kit rule #1); every
  claim below is measured, with four of the measurements cross-confirmed by independent
  probes using different methods.
- **Method:** fresh materialization → full builds (both rails + all `-D` variants) →
  56/56 test suite re-run → gates → six-dimension adversarial review (hardware/latch
  discipline, cycle budget, double-buffer/temporal, framebuffer forensics, test-assertion
  quality, docs/cleanroom/process) → adversarial re-verification of every major finding
  by a fresh independent probe. Owner-side renders were re-taken and inspected directly.

## AGGREGATE VERDICT: **the capability is real and hardware-sound — but DO NOT MERGE AS-IS.**

The renders are correct, the engine primitives are correct, the budget instrument is
sound, the live-B park is right (and stronger than claimed), and the audit trail is
honest in form. But the PR's headline optimization claim — *"camera A rotates at a true
60 fps CPU-side"* — is **false for the shipped artifact** (four independent measurements:
the demo game loop closes once per TWO frames → 30 Hz motion), one shipped gate the audit
series never ran **fails** (provenance), and two of the shipped test done-conditions are
**vacuous/confounded** (P2, P5) — falsifying the final audit's "none of the passing
positive assertions are vacuous." All of it is fixable at test/doc level in a small
follow-up commit series; a real 60 fps fix also exists and is measured-feasible.

Reproduced clean from fresh materialization: 27/27 perspective+cycles+persp3, 29/29
split-family regression, `width-check` (188 files), `zp-check` (0 findings),
`cleanroom_check.sh` (also clean WITH this report present — re-run verified).

---

## 1. MAJOR findings

### M1 — The shipped rail's game loop runs at 30 Hz; the "true 60 fps" headline is false in situ

**Claim under test:** `templates/split_h_persp_demo/main.asm:122-133`, guide
`docs/guides/split_h.md` ("interp4 … **FITS → true 60 fps**"), commit `c9f9a94`
("live rotation now fits 60fps (measured)"), final audit DoD-1.

**Measured (four independent confirmations, different methods):**

1. Frame-stepped WRAM trace of the maintainer-built default ROM: the `E010` heartbeat
   advances in strict `+2, 0, +2, 0` steps; `pv_buffer` ($01C6) flips every **2nd**
   frame (one `pv_rebuild` per 2 frames); `M7_PV_ANGLE` advances 8 units per 2 frames —
   **30 Hz pose motion**, proven in WRAM independent of any screenshot.
2. Scanline-resolution map: body released ~scanline 229 → solve ends ~scanline 212 →
   band-2 splice **straddles the NMI** and completes ~scanline 24-32 of the *next*
   frame → total body ≈ 323 scanlines ≈ **123%** of one frame. The frame handshake
   (`lib/macros/sf_frame.inc` DONE/DMA_READY) quantizes ANY overrun to a whole extra
   frame — so 123% → 2 frames.
3. Instrumented decomposition (free-running cycles method, independently rebuilt):
   interp4 solve alone = 307,832 mc = **86.1%** (reproduces the pinned 86.6%) — but
   that number is **HDMA-off**. With the rail's CH5|CH6 per-scanline REPEAT HDMA the
   solve is **92.6%** (steal ≈ +23-25k mc/frame ≈ 7%), and the per-frame
   `mode7_band_splice` costs **~85k mc ≈ 23.9%** (the guide calls it "a WRAM memcpy,
   cheap" — it is 896 bytes through a `[dp],y` loop with a per-line width toggle).
   Total per-frame work = **110% (HDMA off) / 120% (HDMA on)** — corroborating the
   scanline map exactly.
4. Controls that prove the mechanism: a no-work engine loop and the `-DNO_SEAM` build
   (solve, no splice) both run **true 60 fps** (heartbeat +1/frame, buffer flips every
   frame); every splice-carrying variant (default, freeze, still, `-DA_INTERP=1`,
   seam moved to 176 or 200) is 2-frame. The solve + frame spine ride at ~99% — any
   per-frame splice tips it. No knob fixes it: the engine clamps interp at 4
   (`A_INTERP=8` silently falls back to interp1, measured 492k mc).

**Fairness / scope:** the DISPLAY genuinely holds 60 fps (HDMA re-streams the committed
buffer; the PR's own E010-is-liveness-only analysis is correct — and is precisely the
blind spot that let this ship: the suite has no in-situ loop-rate gate). The solve-alone
measurement and the interp4-fits-the-solve conclusion are honest. Even the old "interp1 →
~43 fps motion" narrative was impossible — quantization means interp1 was also 30 Hz, so
the interp4 change did not alter the shipped motion rate at all. What is false is the
shipped-artifact claim.

**Two undocumented hazards ship with the overrun:**

- **Splice-tail beam race, ungated.** The mid-body NMI commits the freshly-flipped
  buffer (A1T5/A1T6, `engine/nmi_handler.asm` commits every NMI) while the band-2 splice
  is still running; the tail completes ~scanline 24-32 of ACTIVE display and stays
  invisible only because HDMA doesn't read band-2 rows until scanline 112 — an ~80-scanline
  margin nothing measures or asserts. ~30% growth in the tail would tear band-2 on
  hardware.
- **Stale band-1 origin every other frame.** The CH2/CH3 origin tables are re-stamped
  *after* the straddled frame's line-0 HDMA fetch, so that frame renders the NEW camera-A
  matrix against the STALE band-1 centre/scroll — a measured geometric incoherence at
  30 Hz (throttled pixel deltas ~3-4M on alternate frames; exactly 0 in the frozen
  control).

**Remediation:**

- *Minimum (docs-honest):* correct the main.asm header, the guide's "FITS → true 60 fps"
  and "splice … cheap" lines, and the commit-narrative claims to: "the SOLVE fits
  (92.6% HDMA-on); the integrated demo loop closes in 2 frames → 30 Hz motion; the
  display holds 60 fps." Add an **in-situ cadence gate**: frame-step and assert
  `pv_buffer` flips (or heartbeat parity advances) every frame — a WRAM assertion,
  immune to the harness artifact in M4. It fails at HEAD, documenting the known gap,
  or ships `xfail` with the follow-up filed.
- *Real fix (measured-feasible, engine work + its own audit cycle):* stop solving rows
  the splice overwrites — rebuild camera A over `[PV_L0..SEAM)` only. Measured: a
  112-line band-1 rebuild ≈ 184k mc (51.5%) + splice 85k (23.9%) + restamp ≈ **~75-81%
  → fits with margin**. Requires the CH5/CH6 index-table shape to keep covering 224 rows
  while `pv_rebuild` fills only band-1. Add a splice-tail margin gate (assert completion
  before the beam reaches SEAM) either way.

### M2 — `make provenance-check` FAILS on the materialized kit; the audit series never ran it

Both PR-added binary assets are unregistered:
`templates/split_h_persp_demo/assets/checker_map.bin` and
`templates/split_h_persp3_demo/assets/checker_map.bin` (plus 3 pre-existing unregistered
blobs from the base branch: `split_h_demo/assets/floor.png`, `floor_map.bin`,
`split_h_matrix_demo/assets/checker_map.bin`) → `provenance: FAIL — 5 unregistered
blob(s)`. The shipped policy (`docs/cleanroom_policy.md` §4.1/Enforcement) says this
gates. The final audit's "all three gates clean" (§5) ran only width/zp/cleanroom.
No rip risk — both assets regenerate **byte-identical** from the committed `gen_map.py`
(verified; md5 `3862ea7c…` / `07a91259…`) — so the fix is a trivial `kind=generator` +
`regenerate` manifest entry each (and ideally the 3 base-branch ones in the same pass).

### M3 — Two shipped done-condition tests are vacuous/confounded (final audit's non-vacuity claim falsified)

**P2 (`test_p2_clean_single_scanline_seam`) is fully vacuous.** Harness screenshots are
256×239 with a **+7-row offset** (PPU line L → screenshot y = L+7; rows 0-6 padding).
P2's window (y 100-113) never contains the real seam (y 118→119 = PPU 112); its 216-px
"seam peak" at y=104 is a checker row-edge inside camera A's band. Verified directly:
P2's exact metric returns the **identical passing verdict on the no-splice control
builds**. Worse, the true seam's G+B signature jump (108) is below P2's >120 threshold,
so even a corrected window would fail as written. Seam coverage survives elsewhere (C2
red-step at exactly PPU 112; P1 period regime; P3 data test pins the M7A jump at buffer
idx 112) — so the render is right and the capability stands; the test certifies nothing.
Fix: correct the window for the offset, retune the threshold, and pair it with a
noseam-control assertion (which would have caught this immediately).

**P5 (`test_p5_latch_violation_corrupts`) is confounded.** It compares a ROTATING
latch-violation ROM (max jitter over 6 frames) against ONE settled frame of the FROZEN
still build. Rotation alone beats the 2× threshold: the untampered default build passes
the exact P5 procedure **3/3** as the "corrupted" side (rotating jitter sweeps 2.4-14.2
with angle; the frozen baseline is 0.56). Commit `38f6f72` hardened the wrong variance
source (its "clean reference is deterministic" premise was already false once live
rotation shipped). The latch mechanism itself IS real and load-bearing — an isolation
probe that write-twices the SAME values the NMI writes (no value change, pure
latch-interleave) tears the floor 0.56 → 11.8 — so the guard is genuinely proven, just
not by P5 as shipped. Fix: build the latch variant as `FREEZE+HOLD_B+LATCH_VIOLATION`
and compare against `still` on the same metric (measured: 5.52 vs 0.56, a clean 10×).

### M4 — Harness artifact: `frame_stepping()` frame-skips the video output

MesenRunner's frame-stepping path sets the emulator's MaximumSpeed flag, which skips
video frames: consecutive screenshots pair up **even on a true-60 fps ROM** (verified
with a throttled control). WRAM reads are unaffected. This taints per-frame *pixel*
assertions built on step-captures (the P3/C3 stability tests still stand — their
positive/negative controls flip on the same metric, and the FIXED_BUFFER_SPLICE
alternation is far coarser than the skip — but the instrument itself is misleading and
already contaminated one probe in this review before being caught). File as an
infrastructure follow-up: either throttle during step-capture or document the flag.

### M5 — Band-1 origin re-stamp is unsynchronized with the CH2/CH3 table fetch (latent)

The per-frame re-stamp of the band-1 origin slots (`center_update`,
`templates/split_h_persp_demo/main.asm`) lands at scanlines **16-32 of active display**
(locked phase, measured over a full rotation) — i.e. ~16+ lines *after* the line-0 HDMA
fetch of those very slots, safe today only by phase accident (a ~1-2k-cycle change in
body cost walks the multi-store sequence onto the fetch, where HDMA — which halts the
CPU mid-sequence — reads a torn entry: X-new/Y-old, or CH2-centre-new/CH3-scroll-old,
breaking the centre/scroll cancellation for one frame). No VBlank guard, no table
double-buffer, and no test can see it (C3 uses the frozen build, where the re-stamp
writes identical bytes). The "guard by construction" language covers register writes,
not this WRAM-table race. Fix: document the phase constraint, or double-buffer the
origin tables, or re-stamp under the same VBlank window as the NMI commit. (M1's real
fix frees enough budget to do this trivially.)

---

## 2. MINOR findings (roll into the same follow-up)

1. **Stale guide subsection** ("Demo & tests → The C-horiz PERSPECTIVE rail"): still says
   `NMI_HDMA_ENABLE == $60` / "no extra HDMA channel" and omits C1-C3/`-DSAME_CENTER`/
   `-DSKY_HORIZON`; contradicts the shipped `$6C` (asserted by the structural test and
   stated correctly 3× earlier in the same guide).
2. **Stale template comments** (`split_h_persp_demo/main.asm`): "CH2 is the ONLY channel
   the renderer never touches (pv_rebuild owns CH3-CH7)" contradicts the code that binds
   CH3 lines later (ground truth: pv_rebuild writes CH3/4/7 *shadows*; the NMI ownership
   gate `M7_OWNED_MASK=$60` keeps them off hardware); "OBJ stays on in both bands" and
   "TM holds $11" contradict the shipped `$00/$01` tables (guide is right; comments stale).
3. **Latent CH3 trap:** `engine_mode7_hud` pins CH3 into `M7_OWNED_MASK` without checking
   the allocator — combining the origin splice with the Mode-7 HUD overlay would have the
   NMI clobber CH3 with the BGMODE stub. Needs a caveat in the guide (or an allocator
   check in the HUD bootstrap).
4. **Vendor math-coprocessor trade name** in two shipping kit files (guide + demo header,
   same sentence). Mechanism-phrased, but it's a chip trade name with no tripwire
   coverage and no reviewed exemption — rephrase ("the vendor's math coprocessor") or add
   a conscious `cleanroom_allow` entry before publish.
5. **C2 docstring confabulates physics:** the "red boundary lands a few rows INTO band-2
   (world-X wrap)" explanation is actually the +7 screenshot offset — the step is exactly
   AT the seam. The misdiagnosis is what hid M3/P2. Also `SKY_ROWS[0]=4` samples a
   padding row (margin erosion only).
6. **Stability tests lack controls where they'd be cheap:** C3's metric flips at 775 on
   the already-built `stillfixed` frames but no control test asserts it; persp3-C3 has no
   frame-advance guard (would pass vacuously if frame_step no-oped). P3's pairing is
   exemplary — same metric, same rows, control >40 vs pass ≤4.
7. **Seam-location blind spots:** persp3-C2 passes with the first seam displaced 10 rows
   and with a 2-row interleave smear; no test pins the visible seam row (P3-data pins the
   buffer index; C2 pins the red step but searches 92 rows). Worth one `peak_y ==` assert.
8. **Structural test overclaims in prose:** `test_structural_channels_and_60fps`'s
   docstring/failure message state a CPU-budget claim ("frame did not close at 60fps")
   that its E010 liveness metric cannot make — and which is false at HEAD (M1) while the
   test passes. Reword to "display/NMI liveness" (the persp3 twin is harmless — that loop
   genuinely idles).
9. **Guide's WRAM claim is conditional:** "$7E:C000+ is free" holds in this rail only via
   the Mode-7/standard-HDMA mutual-exclusivity clause (`engine_state.inc`); a rail adding
   a standard HDMA effect would collide with pose tables at $C000-$D3FF. Add the caveat.
   (The `$C810-$C814` allocator-scratch note in engine_state.inc is itself stale — the
   scratch moved to $01D8.)
10. **Budget-table framing:** the pinned solve numbers are HDMA-off (correct for what the
    instrument isolates — but the guide never says so, and the real headroom at interp4
    is ~7%, not 13.4%). One sentence fixes it. The 6-digit pins carry ±0.4-0.8% tick
    quantization; thresholds are wide, so assertions are robust.

---

## 3. Verified SOUND (independently confirmed — no findings)

- **Engine splice/capture primitives** (`mode7_band_splice`/`mode7_band_capture`/
  `splice_copy_band`): offset math `(seam−L0)*4` incl. the stale-high-byte mask; Z-flag
  survival through `rep #$20` (REP/SEP touch only the immediate-mask P bits); scratch
  (`pv_temp+2/4`, `math_a/b`) dead across the window, NMI-safe (DP=$0100 handler);
  boot-capture provably under forced blank, reading the post-flip buffer camera B was
  just built into. Out-of-contract seam values would wrap (documented range in the macro
  headers only — noted, not gating; demo usage valid).
- **ValueLatch discipline + channel ownership:** every CPU write-twice to
  $211B-$2120/$210D/$210E traces to forced-blank boot or the NMI VBlank commit; CH2/CH3
  acquired via the allocator (first-fit after the CH0/CH1 reserve), sky lands on CH4 by
  allocator bookkeeping (not luck), `$6C`/`$7C` masks verified from hardware-register
  dumps; DMAP `$03` table layouts deliver complete low+high pairs to both registers of
  each pair atomically per HBlank (table bytes dumped and checked); persp3 is
  guard-by-construction (boot-armed ROM tables, `wai` loop).
- **Interp4 visual quality (capability-critical):** frozen like-for-like interp4 vs
  interp1 at three angles — band-2 **0.00%** differing pixels; band-1 diffs are
  1-pixel-class edge placement (4.5-8.6% of band pixels, max 2 px, zero full-row flips at
  rotated angles); no 4-row stair-stepping anywhere incl. the PV_L0=0 horizon; interp4's
  ramp is locally *smoother* than interp1's 4-unit quantization plateaus. Claim
  substantiated (owner-inspected).
- **3-camera stack (capability-critical):** periods exactly 8/32/16 (per-scanline
  max-run, mean=min=max per band); two single-scanline seams at PPU 75/150, zero smeared
  rows; one shared world (single CGRAM palette, one map+CHR at VRAM $0000, aligned
  checker lattice); `-DONE_CAM` collapses to uniform 8. True 60 fps loop (it just
  `wai`s). Genuine, non-vacuous.
- **Origin-splice world-pan (capability-critical):** red step 0→169 in ONE scanline at
  exactly PPU 112, every frame index probed; `-DSAME_CENTER` folds band-2 back (red 0)
  while remaining a distinct camera by scale. Both-registers-required design confirmed in
  the table dumps (scroll = centre − screen-half invariant holds).
- **No flicker in the shipped default:** 12-frame deterministic filmstrip — band-2
  consecutive diffs 0 except the expected 8-frame pose steps; lag-1 < lag-2 signature
  (opposite of a 2-frame desync); the `-DFIXED_BUFFER_SPLICE` control alternates
  camera-B/camera-A data (M7A 256↔144) in the active buffer AND pixels, caught by the
  same metric that passes the guarded build. The PR's test-blindness diagnosis and
  active-buffer fix are correct.
- **Budget instrument + park decision:** method sound (all systematics ≤0.7%,
  wall-clock cancels in the ratio, counters safe); full pinned table reproduced ≤0.6%
  (interp1/interp2 bit-exact); chamber instrument corroborates (~120% forced-rebuild,
  per-line agreement ~2%). Live-B park **verified and strengthened**: measured fixed
  per-rebuild floor ~65-70k mc (a 16-line band-2 slice still costs 22%) kills every
  slicing route; two-full-solves = 272%; and the double-flip argument is real
  (`pv_rebuild` flips unconditionally and re-commits — a second in-frame rebuild lands in
  the displayed buffer). E010 semantics confirmed exactly as documented.
- **Process:** audit-trail form honest (audit-1 → test-only remediation → audit-2; the
  later audits' numbers re-measured, not transcribed); paper cuts and roadmap honestly
  record the deferred sky-macro follow-up and the E010 lesson; Makefile/variant scripts
  sound; `gen_map.py` assets byte-reproducible; parent-side doc token hits are correctly
  confined to non-shipping files (flagged for publish-time exclusion, as the final audit
  itself noted).

---

## 4. Recommendation

**Hold the merge for one remediation pass.** Two viable paths; both keep the engine
primitives and both rails as shipped:

1. **Docs-honest minimum** (small, test/doc-level, ~1 commit series): M1 wording + in-situ
   cadence gate, M2 manifest entries, M3 P2/P5 test fixes, M4 harness note, M5
   documented phase constraint, and the minors. The rail then ships as an honest
   "30 Hz-motion / 60 fps-display two-camera rail" — still a genuine capability.
2. **Real 60 fps** (adds an engine change + its own audit cycle): band-1-only rebuild
   (measured ≈75-81% total) + splice-tail margin gate + origin-table double-buffer.
   This makes the original headline true and retires M1/M5 together.

The PR's three shaping findings all survived adversarial re-verification — the flicker
really was test-blindness, the budget really is ~6× the parent doc, and E010 really is
display-decoupled. The irony worth recording: that third finding names the exact blind
spot that let the false 60 fps headline ship. The suite reads rendered output everywhere
it was told to; what was missing is the one gate that reads the *loop*.
