; =============================================================================
; mosaic.asm — the pixelate-to-black scene wipe: curves, stepper, NMI commit
; =============================================================================
; Four entry points and one seven-byte DP state block (ES_MOS_CTL):
;
;  mosaic_arm main thread start a wipe (bg mask + swap routine)
;  mosaic_tick main thread step it one frame — call EVERY frame
;  mosaic_active main thread the query the consumer gates on
;  mosaic_nmi_commit NMI hook the shadow byte -> $2106
;
; THE SHAPE. 20 frames OUT (brightness 15->0), the caller's swap routine JSR'd
; at peak black, 15 frames IN (brightness 0->15). Mosaic size is LOCKED to `15
; - brightness` on every frame of both phases, so the two ends of the curve are
; "clean image, full brightness" and "black, full pixelation" and there is no
; third parameter to get out of step. The two ease curves below are
; hand-authored — a quarter-cosine out and a quarter-sine in, continuous and
; monotonic — so the dissolve reaches black exactly at the swap and rises
; smoothly out of it.
;
; WHAT THIS FEATURE DOES NOT DO, AND WHY — the short version; the long version,
; with the evidence, is the header of this directory's feature.toml.
;
;  It does not claim INIDISP. scene_mgr owns $2100 and commits it from
;  ES_SM_NMI+1 every armed frame, so the only way to drive brightness is to
;  write that shadow — which is exactly what `fade` does, claiming nothing.
;  mosaic does the same, preserving the shadow's high nibble so a forced-blank
;  bit set by boot or by the caller's swap survives the wipe.
;
;  It does not claim TM, so it does not drop OBJ. Clearing the OBJ bit from
;  the TM shadow is the obvious way to hide sprites through the wipe; here
;  TM belongs to the scene's BG feature and
;  check_reg_ownership refuses a second owner. Composing a TM claim on this
;  feature against a scene holding `backdrop` gives, verbatim:
;
;  ALLOCATION FAILED: REGISTER ownership contention in scene 'probe': mos
;  (engine:mosaic) and backdrop_mode (engine:backdrop) both write ['TM'] —
;  a CPU-written register has one owner per scene. If one of these only
;  seeds a base value that a declared hdma claim overwrites, mark it
;  `seed = true` (docs/09 §2.1)
;
;  ...and adding `seed = true` produces the identical refusal, because seed
;  exempts the reg x hdma check and not the reg x reg one. Hiding OBJ for the
;  duration of the wipe is therefore the CONSUMER'S job, gated on
;  `mosaic_active`: clear TM bit 4 in the feature that owns TM (static-TM
;  scene), or park the actor OAM at Y >= $F0 (HDMA-TM Mode 7 scene, where the
;  TM drop is defeated per scanline anyway).
;
; ES_MOS_CTL layout:
;  +0 state +1 timer +2 bright +3 bg_mask +4 swap_ptr(2) +6 shadow

MOS_IDLE       = 0
MOS_OUT        = 1
MOS_IN         = 2

MOS_OUT_FRAMES = 20             ; brightness 15 -> 0
MOS_IN_FRAMES  = 15             ; brightness 0 -> 15
MOS_FULL       = 15             ; INIDISP full brightness / mosaic size 15

; --- the ease curves --------------------------------------------------------
; Indexed by `elapsed` = PHASE_FRAMES - timer, i.e. 0 on the first frame of the
; phase. Values are brightness 0..15; the mosaic size the frame renders at is
; MOS_FULL minus the value. The OUT curve's last entry is 1, not 0: the swap
; frame forces 0 explicitly so the black frame is exact regardless of the
; curve. `.byte` in the code bank rather than a rom claim — see feature.toml.
_mos_curve_out:
    .byte 15, 15, 15, 15, 14, 14, 13, 13   ; elapsed 0-7
    .byte 12, 11, 11, 10,  9,  8,  7,  6   ; elapsed 8-15
    .byte  5,  4,  2,  1                   ; elapsed 16-19 (swap forces 0)
_mos_curve_out_end:
.assert (_mos_curve_out_end - _mos_curve_out) = MOS_OUT_FRAMES, error, "OUT curve length"

_mos_curve_in:
    .byte  2,  3,  5,  6,  7,  9, 10, 11   ; elapsed 0-7
    .byte 12, 13, 14, 14, 15, 15, 15       ; elapsed 8-14 (settled = 15)
_mos_curve_in_end:
.assert (_mos_curve_in_end - _mos_curve_in) = MOS_IN_FRAMES, error, "IN curve length"

; --- mosaic_init: the boot init contract -----------------------------------
; CONTRACT mosaic_init
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole mos_ctl claim zeroed — state, timer, shadow and
;             bg_mask. That is `[init] zero` given a routine behind it:
;             the declaration emits a comment in the scene map and no code
;   clobbers: A, X, N, Z. The prose above claims A as well and the loop
;             does not in fact write it; the wider claim is kept rather
;             than narrowed
;   assumes:  ONCE, from MAIN's boot block. Mesen's
;             break-on-uninitialised-read detector fired on three of these
;             bytes the first time a ROM composed this feature — that
;             measurement, not a preference, is why the routine exists
;   tail:     rts
;
; THE CONTRACT THE feature.toml DECLARES, AND WHICH NOTHING IMPLEMENTED UNTIL
; THIS ROUTINE. `[init] zero = ["mos_ctl"]` is a DECLARATION — the allocator
; emits it as a comment in the scene map and no code falls out of it (the
; convention every other feature follows is a `<name>_init` routine the game's
; boot block calls: sm_init, fade_init, input_init). Mosaic shipped without
; one, so the two bytes its own header names as "genuinely READ BEFORE ANY
; WRITE" — `state`, read by mosaic_tick and mosaic_active on every frame from
; boot, and `shadow`, committed to $2106 by the NMI hook on every armed frame —
; held power-on garbage.
;
; MEASURED, not reasoned: Mesen's break-on-uninitialized-read detector fired on
; $000010, $000011 and $000013 (state, timer and bg_mask) the first time a ROM
; composed this feature. A non-zero `state` at boot is a wipe nobody armed,
; ticking a curve from a random elapsed index and JSR'ing a swap pointer made
; of DRAM noise; a non-zero `shadow` is a mosaic on screen before the first
; frame. Both are rule 5's class exactly, and both are why the establishment
; the header claims for `[init] zero` needed a routine behind it.
mosaic_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mosaic_init"
    ldx #(ES_MOS_CTL_SIZE - 1)      ; 7 bytes: odd, so this is a BYTE loop
    sep #$20
    .a8
:   stz z:ES_MOS_CTL, x
    dex
    bpl :-
    rep #$20
    .a16
    rts

; --- mosaic_arm: start a wipe ----------------------------------------------
; In: A8/I16, DB=0. A = the affected-BG nibble for $2106's low nibble
;  (1 = BG1, 3 = BG1+BG2, ...). X = the swap routine's address in the
;  program bank, or 0 for none (a pure flash / fade-out-fade-in).
; Out: A8/I16. Clobbers A.
;
; Arming does not itself write either shadow: the first tick reads curve[0] =
; 15 and applies it, which is the same "clean, full brightness" frame the
; display is already showing. The caller drops OBJ here if its scene needs it
; (see the file header) — this feature cannot.
mosaic_arm:
    .a8
    .i16
    sta z:ES_MOS_CTL + 3            ; affected-BG nibble, held for both phases
    stx z:ES_MOS_CTL + 4            ; swap routine (I16, so both bytes)
    lda #MOS_OUT
    sta z:ES_MOS_CTL + 0
    lda #MOS_OUT_FRAMES
    sta z:ES_MOS_CTL + 1
    lda #MOS_FULL
    sta z:ES_MOS_CTL + 2            ; OUT starts at full brightness
    rts

; --- mosaic_active: is a wipe in flight? -----------------------------------
; CONTRACT mosaic_active
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       the mosaic state byte
;   out:      A = the state byte, Z SET when idle — the flag IS the
;             answer, so the caller branches on it directly
;   clobbers: A, N, Z
;   assumes:  nothing. It is a read, and the three gates that use it are
;             named in the prose above
;   tail:     rts
;
; The consumer gates on this in three places, all of which matter:
;  * its own per-frame game work (both scenes freeze while the wipe runs),
;  * any other writer of the INIDISP shadow — a fade ramp, a boot ramp — which
;  must skip, because mosaic owns brightness for the duration,
;  * whatever hides OBJ for the wipe (TM bit 4, or an OAM park).
mosaic_active:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mosaic_active"
    lda z:ES_MOS_CTL + 0            ; sets Z when idle
    rts

; --- mosaic_nmi_commit: the shadow byte -> $2106 ---------------------------
; CONTRACT mosaic_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       the mosaic shadow byte
;   out:      $2106 (MOSAIC) written from the shadow, unconditionally —
;             the final IN frame is also the frame that goes idle, so a
;             hook that tested the state byte would skip the very write
;             that clears the mosaic
;   clobbers: A, N, Z. DB is unchanged
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; WIDTH-RISK: entry = A8/I16, DB=0 — the sm_nmi_hook contract. The caller is in
; ANOTHER FILE (the game's main.asm), which make width-check cannot see in
; either direction (CLAUDE.md rule 6, "the single-file limit remains"), so this
; contract is proven only on the emulator and this marker is what carries it.
;
; UNCONDITIONAL, on purpose. The final IN frame is also the frame that goes
; idle, so a hook that tested the state byte would skip the very write that
; clears the mosaic; and with `[init] zero` on the claim an idle mosaic commits
; $00 every frame, which ESTABLISHES a register that would otherwise hold
; power-on garbage (rule 5) instead of merely not disturbing it.
mosaic_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mosaic_nmi_commit"
    lda z:ES_MOS_CTL + 6
    sta a:$2106
    rts

; --- _mos_apply: brightness -> both shadows --------------------------------
; In/out: A8/I16, DB=0. Clobbers A.
;
; Reads ES_MOS_CTL+2 (brightness) and writes BOTH shadows the wipe drives, so
; the two can never drift out of the locked relationship:
;  INIDISP shadow low nibble = brightness, high nibble PRESERVED
;  MOSAIC shadow size = 15 - brightness, the caller's mask under it
;
; The size-0 case writes a TRUE $00 rather than `0 | bg_mask`: a size-0 mosaic
; with the enable bits still set perturbs the image compared with a true $00
; frame — measured on the emulator. Leaving the BG bits set at size 0 is a
; latent difference, so it is not folded into the general path.
_mos_apply:
    .a8
    .i16
    lda z:ES_SM_NMI + 1
    and #240                        ; keep the forced-blank bit + high nibble
    ora z:ES_MOS_CTL + 2
    sta z:ES_SM_NMI + 1             ; scene_mgr's NMI commits this to $2100
    lda #MOS_FULL
    sec
    sbc z:ES_MOS_CTL + 2            ; size = 15 - brightness, 0..15
    beq @clean
    asl
    asl
    asl
    asl                             ; size into the high nibble
    ora z:ES_MOS_CTL + 3            ; | the caller's affected-BG nibble
    sta z:ES_MOS_CTL + 6
    rts
@clean:
    .a8
    stz z:ES_MOS_CTL + 6            ; size 0 -> a true $00, no BG bits
    rts

; --- _mos_call_swap: call the caller's swap routine ------------------------
; In: A8/I16, DB=0, ES_MOS_CTL+4 non-zero.
;
; WIDTH-RISK: this transfers control to a routine in ANOTHER FILE through a
; pointer, so neither make width-check nor ca65 can see the contract in either
; direction. THE CONTRACT: the swap routine is entered A8/I16 with DB=0 and
; MUST return A8/I16 with DB=0. It runs on the swap frame, at brightness 0 with
; the mosaic at full size, so it is free to assert its own forced blank for the
; VRAM/CGRAM rebuild — the high nibble of the INIDISP shadow is preserved by
; _mos_apply, so a blank it leaves set stays set through the IN ramp.
;
; `jmp (abs)` reads its pointer from BANK 0 — which is where ES_MOS_CTL lives,
; because DP is $0000 for the whole engine (vendor/rom/init.inc:34, "DP =
; $0000"), so the DP symbol and the bank-0 absolute address coincide. That is
; the reason for the indirect JMP rather than `jsr (abs,x)`, which reads its
; pointer from the PROGRAM bank instead. This is a TAIL CALL: control never
; returns here, and the swap's own RTS returns to the instruction after the
; `jsr _mos_call_swap` in mosaic_tick.
_mos_call_swap:
    .a8
    .i16
    jmp (ES_MOS_CTL + 4)

; --- mosaic_tick: step the wipe one frame ----------------------------------
; CONTRACT mosaic_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       the mosaic state, timer and curve position
;   out:      the wipe stepped one frame: the shadow byte and the INIDISP
;             shadow updated, the state advanced, and the swap callback
;             JSR'd at the turn
;   clobbers: A, X, N, Z, C, V
;   assumes:  ONCE per frame, unconditionally; it returns immediately when
;             idle. It shares fade_tick's A16/I16 convention so a main
;             loop can call the two the same way, and it must be ticked
;             LAST of the two — both write the INIDISP shadow and neither
;             claims INIDISP, so the allocator has nothing to check
;   tail:     rts
;
; Ordering against fade: BOTH write the INIDISP shadow, and neither claims
; INIDISP, so the allocator has nothing to check. Gate the fade tick on
; `mosaic_active`; if you tick both anyway, tick mosaic LAST.
mosaic_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mosaic_tick"
    sep #$20
    .a8
    lda z:ES_MOS_CTL + 0
    beq @done                       ; idle — nothing to step
    cmp #MOS_OUT
    beq @out
    jmp @in

; ---- OUT: brightness 15 -> 0, size 0 -> 15, then the swap -----------------
@out:
    .a8
    lda #MOS_OUT_FRAMES
    sec
    sbc z:ES_MOS_CTL + 1            ; elapsed = FRAMES - timer, 0 on frame one
    rep #$20
    .a16
    and #255                        ; a clean 16-bit index for I16 X
    tax
    sep #$20
    .a8
    lda f:_mos_curve_out, x         ; long-indexed: bank-independent
    sta z:ES_MOS_CTL + 2
    jsr _mos_apply
    dec z:ES_MOS_CTL + 1
    bne @done
    ; ---- the swap frame: force exact black, hold full pixelation ----------
    stz z:ES_MOS_CTL + 2
    jsr _mos_apply                  ; brightness 0 -> size 15 | outgoing mask
    lda z:ES_MOS_CTL + 4
    ora z:ES_MOS_CTL + 5
    beq @no_swap                    ; null pointer -> flash / fade only
    jsr _mos_call_swap              ; tail-called; returns here (see its header)
@no_swap:
    .a8
    lda #MOS_IN
    sta z:ES_MOS_CTL + 0
    lda #MOS_IN_FRAMES
    sta z:ES_MOS_CTL + 1
    bra @done

; ---- IN: brightness 0 -> 15, size 15 -> 0, then settle -------------------
@in:
    .a8
    lda #MOS_IN_FRAMES
    sec
    sbc z:ES_MOS_CTL + 1
    rep #$20
    .a16
    and #255
    tax
    sep #$20
    .a8
    lda f:_mos_curve_in, x
    sta z:ES_MOS_CTL + 2
    jsr _mos_apply
    dec z:ES_MOS_CTL + 1
    bne @done
    ; ---- the last IN frame: pin full brightness, clear the mosaic, idle ---
    lda #MOS_FULL
    sta z:ES_MOS_CTL + 2
    jsr _mos_apply                  ; brightness 15 -> size 0 -> shadow $00
    stz z:ES_MOS_CTL + 0            ; idle; the consumer's gate reopens
@done:
    .a8
    rep #$20
    .a16
    rts
