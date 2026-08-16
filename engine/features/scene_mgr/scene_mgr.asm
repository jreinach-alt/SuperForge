; =============================================================================
; scene_mgr.asm — frame heartbeat, NMI core, scene dispatch + transitions
; =============================================================================
; Global-feature runtime (symbols from engine_state_globals.inc):
;  ES_SM_CTL +0 cur scene id +1 next scene id +2 phase +3 spare
;  ES_SM_NMI +0 nmi_ready +1 INIDISP shadow (committed at VBlank)
;  ES_SM_FRAME u16 frame counter (WRAM)
;
; The including ROM provides (in bank 0):
;  sm_enter_tab / sm_tick_tab / sm_exit_tab:
;  .word per-scene routine addrs, indexed by scene id * 2 (manifest order)
;  sm_nmi_hook: VBlank work (DMAs, shadow commits). A8/I16, DB=0. May clobber
;  A/X/Y. Runs ONLY on frames the main loop armed (nmi_ready).
;
; Scene routine contracts (all jsr'd from A16/I16, DB=0, must return so):
;  enter: scene is under FORCED BLANK with NMI masked — upload VRAM/CGRAM,
;  init the scene's declared state (its .inc init contract), set PPU
;  regs. exit: tear down what enter armed (usually nothing — the next
;  enter re-declares everything it owns). tick: one game frame.
;
; Transition phase machine (ES_SM_CTL+2):
;  0 run · 1 fade-out (level -> 0) · 2 blank switch (exit/enter under forced
;  blank, NMI masked) · 3 fade-in (level -> 15) · 4 CUT switch — the SAME
;  phase-2 body, entered with no ramp and left with no ramp
;
; TWO TRANSITION STYLES, AND THE GAME DECLARES WHICH. A `[[edge]]` in game.toml
; carries `style = "fade" | "cut" | "mosaic"`; the allocator emits
; `ES_E_<SRC>_TO_<DST>_CUT` from it, and the SM_SWITCH macro below picks the
; entry point with a `.if` on that symbol at ASSEMBLY time — so an edge's
; declared style is the path its ROM takes, and there is no runtime dispatch to
; get wrong. `SF_SM_CUT` is emitted only where some edge declares "cut", and
; every line the cut adds sits inside `.if SF_SM_CUT`, so a composition of fade
; edges alone assembles byte-for-byte what it did before the cut existed. That
; opt-in shape is the irq `$FFEE` vector's (vendor/rom/header.inc's `.ifndef
; SF_IRQ_VECTOR`), taken for the same reason: a file that lands in every ROM
; grows a capability without moving one byte of the ROMs that do not ask.
;
; THE CUT PATH SHARES PHASE 2'S BODY rather than duplicating it — the
; dispatcher sends both to `@switch` and only the TAIL asks which phase
; arrived. One copy of the mask/exit/clear/enter/restore sequence means "cut"
; cannot drift from "fade" in anything but the ramp, and the alternative (a
; macro expanded twice) was measured and rejected: it is byte-identical but it
; makes width-check read the macro DEFINITION's closing A8 as a fall-through
; into the next label, and moving the definition to a `.inc` to escape that
; would take the NMITIMEN writes out of `no_literals`'s scene_writes
; validation, which scans `.asm` under the feature dir.
; =============================================================================

; --- SM_SWITCH "SRC", "DST": request the transition the EDGE declares -------
; In/out: A8/I16 — the same contract `sm_request` has, because that is what it
; expands to on a fade edge. Loads the destination scene id and calls the entry
; point the declared style names, both from allocator-emitted symbols, both
; resolved at ASSEMBLY time:
;
;  ES_E_<SRC>_TO_<DST>_DST the manifest-order scene id (what sm_request
;  takes) — so a call site does not keep a second
;  copy of the manifest's ordering beside the edge
;  name, where the two can drift in silence.
;  ES_E_<SRC>_TO_<DST>_CUT PRESENT iff `style = "cut"`, absent otherwise.
;
; PRESENCE, not value, and that is forced rather than stylistic: this macro
; expands inside a scene's `.scope`, where ca65 defers an unqualified global
; symbol to end-of-assembly instead of resolving it — so `.if <symbol>` there
; fails with "Constant expression expected" (measured) while `.defined` answers
; immediately. It is the `.ifndef SF_IRQ_VECTOR` idiom, per edge.
;
; A transition the game.toml does not declare has no symbols and stops the
; build naming the edge; an edge declared "fade" expands to exactly `lda #<id>`
; + `jsr sm_request`, which is what every existing call site already assembles
; to. Scene ids are the game.toml ones UPPERCASED (ca65 identifiers are
; case-sensitive, so a lowercase argument simply does not
; resolve and the `.error` fires).
;
; Defined here, at the top, deliberately: a macro DEFINITION is stored tokens,
; never executed where it is written, but `make width-check` is a single-file
; TEXTUAL model and reads the body's last instruction as a fall-through into
; whatever label follows. Above the first label there is no label to fall into.
.macro SM_SWITCH sm_src, sm_dst
    .if .not .defined(.ident(.sprintf("ES_E_%s_TO_%s_DST", sm_src, sm_dst)))
        .error .sprintf("SM_SWITCH: game.toml declares no [[edge]] %s -> %s", sm_src, sm_dst)
    .elseif .defined(.ident(.sprintf("ES_E_%s_TO_%s_CUT", sm_src, sm_dst)))
        lda #.ident(.sprintf("ES_E_%s_TO_%s_DST", sm_src, sm_dst))
        jsr ::sm_request_cut        ; `::` — expanded inside a scene's .scope
    .else
        lda #.ident(.sprintf("ES_E_%s_TO_%s_DST", sm_src, sm_dst))
        jsr ::sm_request
    .endif
.endmacro

.ifndef SF_SM_CUT
; No edge in this composition declares "cut" — the cut path is not assembled.
; The allocator emits `SF_SM_CUT = 1` into engine_state_globals.inc (included
; before this file in every main.asm) when one does.
SF_SM_CUT = 0
.endif

; --- sm_hdma_shadow_clear: unprogram every channel in the register shadow ----
; sm_nmi_core MVNs this whole 128-byte block to $4300 on every armed frame, so
; a slot NOBODY programmed still reaches the real register file. Two ways a
; slot ends up unprogrammed, and both are hostile:
;
;  * At power-on it holds random DRAM garbage (CLAUDE.md rule 5 — RAM is not
;  zero at boot on real hardware). An arbitrary DMAP/BBAD/A1T is HDMA
;  pointed at an arbitrary PPU port from an arbitrary address.
;  * After a scene it holds the PREVIOUS scene's live HDMA configuration. Any
;  later scene that arms a channel number the old scene used inherits that
;  scene's registers for it.
;
; Either way the only thing standing between the stale slot and the PPU is one
; HDMAEN bit. Clearing the block at boot AND at every transition makes a stray
; arm inert instead of catastrophic. It is defence in depth, not the detector:
; tests/test_decl_impl_channels.py asserts the enablement invariant directly.
;
; Cost: 64 iterations of a straight-line 16-bit store loop, once per scene
; change, inside the forced-blank switch with NMI masked. MEASURED on the
; emulator over ALL 64 stores, not extrapolated — 6,334 mc for the block =
; 1.80% of one NTSC frame. Per-iteration is modally 98.0 mc (59 of 63 gaps),
; plus four gaps of exactly 138 mc: 138-98 = 40 = the DRAM-refresh stall, once
; per scanline, and the loop spans 4.64 scanlines. This is why an earlier
; 7-iteration window read 6,272 mc / 1.755% — a window shorter than a scanline
; cannot see the refresh term. Deliberately NOT converted to "CPU cycles": the
; loop runs at 8 mc/fetch from bank $00, not the 6 mc FastROM rate, which is
; also why per-iteration is 98 and not the 78 a datasheet count predicts. The
; frame it lands on is a forced-blank switch frame with no other work, and
; `make measure` confirms the steady-state per-frame pins are untouched. See
; tests/test_scene_mgr_shadow.py::test_measured_cost_of_the_transition_clear.
; WIDTH-RISK: entry AND exit A16/I16, DB=0 (the MVN destination bank is $00,
; the block itself lives in $7E and is reached long). Clobbers A and X.
sm_hdma_shadow_clear:
    .a16
    .i16
    lda #0
    ldx #(ES_SM_HDMA_SIZE - 2)
:   sta f:ES_SM_HDMA_LONG, x
    dex
    dex
    bpl :-
    rts

; --- sm_init: boot-time init contract (zero exactly the declared claims) ----
; In/out: A16/I16, DB=0.
sm_init:
    .a16
    .i16
    stz z:ES_SM_CTL
    stz z:ES_SM_CTL+2
    stz z:ES_SM_NMI
    sep #$20
    .a8
    stz z:ES_SM_NMI+2           ; HDMAEN shadow (claim is 3 B)
    rep #$20
    .a16
    lda #0
    sta f:ES_SM_FRAME_LONG
    jsr sm_hdma_shadow_clear    ; channel-reg shadow (init contract)
    rts

; --- sm_request: ask for a scene switch (fade-out begins next tick) ---------
; In: A8 = target scene id. A8/I16 in and out.
sm_request:
    .a8
    .i16
    sta z:ES_SM_CTL+1           ; next
    cmp z:ES_SM_CTL             ; already there?
    beq :+
    lda #1
    sta z:ES_SM_CTL+2           ; phase = fade-out
    jsr fade_start_out
:   rts

; --- sm_request_cut: ask for a CUT switch (no ramp, either direction) -------
; In: A8 = target scene id. A8/I16 in and out. ASSEMBLED ONLY where an edge
; declares `style = "cut"`, and reached only through SM_SWITCH — which picks it
; from the allocator's emitted per-edge symbol, so the declaration and the path
; cannot disagree.
;
; The fade path's phase 1 exists to WAIT for the ramp to reach black and only
; then arm the forced blank (@fading_out below). With no ramp there is nothing
; to wait for, so this does that tail directly and skips phase 1 entirely. The
; switch still runs one `sm_frame_sync` later, and that is not a frame this
; could shave: the NMI has to have COMMITTED $80 to $2100 before exit/enter
; touch VRAM, which is the same requirement the fade path meets by the same
; means.
.if SF_SM_CUT
sm_request_cut:
    .a8
    .i16
    sta z:ES_SM_CTL+1           ; next
    cmp z:ES_SM_CTL             ; already there?
    beq :+
    ; Cancel any ramp still in flight, or fade_tick — which runs AFTER sm_tick
    ; in every main loop — overwrites the forced blank below on this very
    ; frame, and the switch's VRAM uploads happen with the screen live. Not
    ; reachable on meteor_event (its trigger is ~120 frames of walking past the
    ; boot fade-in), and reachable in general: a scene tick runs in phase 0,
    ; and phase 0 is where the BOOT scene's own fade-in is still ramping. The
    ; mirror of @cut_done's cancel, on the way in.
    stz z:ES_FADE_CTL+1         ; dir = idle
    lda #$80
    sta z:ES_SM_NMI+1           ; INIDISP shadow = forced blank (NMI commits)
    lda #4
    sta z:ES_SM_CTL+2           ; phase = CUT switch (after one more VBlank)
:   rts
.endif

; --- sm_tick: run one frame of the phase machine ----------------------------
; In/out: A16/I16, DB=0. Calls scene tick / transition steps.
sm_tick:
    .a16
    .i16
    sep #$20
    .a8
    lda z:ES_SM_CTL+2           ; phase
    bne @transition
    ; ---- phase 0: run the current scene -----------------------------------
    lda z:ES_SM_CTL             ; cur
    rep #$20
    .a16
    and #$00FF
    asl
    tax
    jsr (sm_tick_tab, x)
    rts

@transition:
    .a8
    cmp #1
    beq @fading_out
    cmp #2
    beq @switch
.if SF_SM_CUT
    cmp #4
    beq @switch                 ; phase 4: the SAME body; the tail differs
.endif
    ; ---- phase 3: fading in ----------------------------------------------
    lda z:ES_FADE_CTL+1         ; dir still running?
    bne @tr_done
    stz z:ES_SM_CTL+2           ; phase = 0 (run)
@tr_done:
    .a8                         ; every entry path is A8
    rep #$20
    .a16
    rts
@fading_out:
    .a8                         ; reached only via A8 beq (textual pred is A16!)
    ; ---- phase 1: wait for the ramp to hit black --------------------------
    lda z:ES_FADE_CTL+1         ; dir: 0 once the ramp finished
    bne @tr_done
    lda #$80
    sta z:ES_SM_NMI+1           ; INIDISP shadow = forced blank (NMI commits)
    lda #2
    sta z:ES_SM_CTL+2           ; phase = switch (runs after one more VBlank)
    bra @tr_done

@switch:
    .a8                         ; reached only via A8 beq
    ; ---- phase 2 (and phase 4, the cut): forced blank is on screen; swap
    ;  scenes safely. ONE body, two styles — only the tail differs ------
    ; Long uploads under NMI corrupt VRAM (VMADD clobber) — mask NMI first.
    stz a:$4200                 ; NMITIMEN: mask NMI + auto-joypad
    stz a:$420C                 ; HDMAEN off NOW (HDMA runs in forced blank)
    stz z:ES_SM_NMI+2           ; and the shadow (scenes re-arm in enter)
    lda a:$4210                 ; RDNMI: ack any pending edge
    rep #$20
    .a16
    lda z:ES_SM_CTL             ; cur (low byte)
    and #$00FF
    asl
    tax
    jsr (sm_exit_tab, x)
    ; The incoming scene must find an UNPROGRAMMED channel register file, not
    ; the outgoing scene's. Placed AFTER exit so it holds regardless of what a
    ; teardown routine touches, and BEFORE enter so the scene's own arm code is
    ; the only thing in the shadow. See sm_hdma_shadow_clear.
    jsr sm_hdma_shadow_clear
    sep #$20
    .a8
    lda z:ES_SM_CTL+1           ; cur = next
    sta z:ES_SM_CTL
    rep #$20
    .a16
    and #$00FF
    asl
    tax
    jsr (sm_enter_tab, x)
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMI + auto-joypad back on
.if SF_SM_CUT
    ; Which phase asked for this switch? Nothing in the body writes the phase
    ; byte, so it still reads what the requesting routine put there. Still A8
    ; on both sides of this block, so the fade tail below is unaffected.
    lda z:ES_SM_CTL+2
    cmp #4
    beq @cut_done
.endif
    lda #3
    sta z:ES_SM_CTL+2           ; phase = fade-in
    jsr fade_start_in
    rep #$20
    .a16
    rts

.if SF_SM_CUT
@cut_done:
    .a8                         ; reached only via A8 beq
    ; ---- full brightness NOW, not through fade's ramp ---------------------
    ; The scene `enter` this switch just ran may have armed one: EVERY scene
    ; enter in this tree calls fade_start_in, because that is also how the BOOT
    ; scene lifts init.inc's forced blank when MAIN calls enter outside the
    ; phase machine. So a cut that only wrote the INIDISP shadow would be
    ; overwritten by fade_tick on this very frame. One 16-bit store cancels the
    ; ramp and re-seats the level: ES_FADE_CTL is +0 level, +1 dir, so #15 is
    ; "level = full, dir = idle". Re-seating matters beyond this frame — a
    ; later FADE edge on the same rail would otherwise ramp out from a stale
    ; level and skip most of its own ramp.
    rep #$20
    .a16
    lda #15
    sta z:ES_FADE_CTL           ; level = 15, dir = 0 (idle) — one store
    sep #$20
    .a8
    sta z:ES_SM_NMI+1           ; INIDISP shadow = full brightness (NMI commits)
    stz z:ES_SM_CTL+2           ; phase = 0 (run): the switch frame is the last
    rep #$20
    .a16
    rts
.endif

; --- sm_frame_sync: arm the NMI and block until it consumed the frame -------
; In/out: A16/I16, DB=0. The NMI commits INIDISP + runs sm_nmi_hook exactly
; once per armed frame (the reference build handshake pattern).
sm_frame_sync:
    .a16
    .i16
    sep #$20
    .a8
    lda #1
    sta z:ES_SM_NMI             ; nmi_ready
:   wai
    lda z:ES_SM_NMI
    bne :-                      ; cleared by the NMI when consumed
    rep #$20
    .a16
    rts

; --- sm_nmi_core: the NMI handler body (game ROM: NMI: jmp sm_nmi_core) -----
; WIDTH-RISK: interrupt entry — full push, explicit widths, full restore.
sm_nmi_core:
    rep #$30
    .a16
    .i16
    pha
    phx
    phy
    phb
    phd
    sep #$20
    .a8
    lda #$00
    pha
    plb                         ; DB = 0 for I/O
    lda z:ES_SM_NMI             ; armed this frame?
    beq @skip
    lda z:ES_SM_NMI+1
    sta a:$2100                 ; commit INIDISP shadow (fade / forced blank)
    jsr sm_nmi_hook             ; game VBlank work (A8/I16, DB=0)
    .a8
    ; re-arm the HDMA channel registers from the shadow (a GP-DMA above may
    ; have time-shared a channel's regs; HDMA re-inits from these at line 0)
    rep #$30
    .a16
    .i16
    phb
    ldx #ES_SM_HDMA
    ldy #$4300
    lda #(ES_SM_HDMA_SIZE - 1)
    .byte $54, $00, $7E         ; MVN dst=$00, src=$7E (ca65 arg order quirk)
    plb
    sep #$20
    .a8
    lda z:ES_SM_NMI+2
    sta a:$420C                 ; HDMAEN from shadow
    stz z:ES_SM_NMI             ; frame consumed
@skip:
    .a8
    rep #$20
    .a16
    lda f:ES_SM_FRAME_LONG
    inc a
    sta f:ES_SM_FRAME_LONG
    sep #$20
    .a8
    lda a:$4210                 ; RDNMI: acknowledge
    rep #$30
    .a16
    .i16
    pld
    plb
    ply
    plx
    pla
    rti
