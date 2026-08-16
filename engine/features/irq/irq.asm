; =============================================================================
; irq.asm — the scanline-IRQ owner's arming API
; =============================================================================
; This feature owns the one H/V timer (the spanned HVIRQ claim, $4207-$420A)
; and nothing else: the HANDLER is the composing rail's (the mechanism that
; fires at the scanline belongs to the feature that stages it), NMITIMEN is
; scene_mgr's (composed by the arming code under sm_display's scene_writes),
; and the $FFEE vector is a link-time opt-in (SF_IRQ_VECTOR, header.inc).
;
; THE ARM SEQUENCE CONTRACT — run from MAIN's boot block, or from a multi-scene
; game's own post-switch code; NEVER from scene enter, which cannot arm (see
; DISARM-ACROSS-SCENES below). In this order:
;
;  lda #<internal scanline>; A16
;  jsr irq_arm_v; 1. timer first — the owner's own write
;  sep #$20
;  lda #((1 << 7) | (1 << 5)); 2. NMI + V-IRQ enable, composed into
;  sta a:$4200; NMITIMEN (sm_display's scene_writes)
;  rep #$20
;  cli; 3. unmask LAST (coldstart SEI holds
; until here)
;
; Timer BEFORE enable: enabling V-IRQ against a stale/random VTIME can latch a
; fire at an arbitrary line (UpdateIrqLevel runs on the $4200 write too —
; InternalRegisters.cpp:305/:362). Enable BEFORE cli is free either way — the
; CPU only takes the interrupt once I clears — but ARM LATE, ARM UNMASKED is
; load-bearing the other way round: an armed line under SEI makes every `wai`
; fall through immediately (WAI ends on an asserted IRQ line even with I set,
; SnesCpu.Shared.h:336-341; measured at ~28k wakes/s in that state). Do not
; arm and then sleep on a masked line.
;
; DISARM-ACROSS-SCENES comes free — and it is why scene enter CANNOT arm: on a
; switch, scene_mgr masks NMITIMEN (stz $4200 at `@switch`'s head) and rewrites
; it to NMI+auto-joypad only AFTER enter returns ($81, at the tail of
; `@switch`), so a V-IRQ bit composed inside enter is silently stripped before
; the scene's first frame (the writer-side gate PERMITS the write — NMITIMEN is
; sm_display's scene_writes — so nothing refuses it; the restore just undoes
; it. Boot-block arming works because MAIN arms after its direct enter call
; returns). The V/H enable bits do not survive a transition, and clearing both
; immediately drops the IRQ flag (InternalRegisters.cpp: 318-321), so no TIMEUP
; ack is owed at the boundary. THE MULTI-SCENE CONSEQUENCE: the IRQ dies at the
; FIRST scene switch, and re-arming is the caller's job from its own
; post-switch code — never enter — until the deferred per-scene dispatch /
; mid-scene arm-disarm surface lands. Same contract rail-side:
; scenes/seam.asm's header.

; --- irq_arm_v: set the V-count timer to an INTERNAL scanline ---------------
; In: A16 = internal scanline (0..261). VTIME counts INTERNAL scanlines and
; content line L draws during internal scanline L+1 (SnesPpu.cpp:1410,:883) —
; so for a band seam at content line S, pass S, NOT S-1: the fire lands in
; internal scanline S's trailing HBlank, after content line S-1 flushed, and
; content line S picks the new values up. One line early corrupts content line
; S-1 — measured, and tools/plants/seam_irq_trial.py plants it. In/out:
; A16/I16. Preserves A/X/Y (the store is the routine). WIDTH-RISK: callers
; arrive A16 — the 16-bit store is what reaches both VTIMEL ($4209) and VTIMEH
; ($420A) in one instruction, and an A8 caller would arm only the low byte
; against a random high bit.
irq_arm_v:
    .a16
    .i16
    sta a:$4209                     ; VTIME lo+hi ($4209/$420A)
    rts
