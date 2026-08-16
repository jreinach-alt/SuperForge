; =============================================================================
; scenes/chamber.asm — the plane, the four effects, and the roll set running
; =============================================================================
; Enter uploads the plane, seeds the roll, builds two matrix index tables and
; arms SEVEN channels: m7_barrel's A and D columns, split_band's BGMODE and TM,
; and rgb_gradient's three COLDATA planes. After that the picture drives itself
; off the PPU — the per-frame work is one roll kernel on the main thread and
; two commits in VBlank.
;
; WHAT MAKES THE FOUR EFFECTS COOPERATE RATHER THAN COLLIDE, which is the whole
; subject of this rail: they touch DISJOINT ports, and the allocator proved it
; before a line of this file was written. BGMODE and TM belong to split_band (a
; seed the scene writes, then HDMA drives per line); M7A and M7D to m7_barrel;
; the three COLDATA planes to rgb_gradient, which owns them independently
; because the plane-select bits are the hardware's own partition. Reaching the
; same arrangement by hand would mean picking channel numbers and keeping them
; out of a hand-maintained owned-mask; here it is five declarations and a build
; gate.

.scope chamber

; --- enter ------------------------------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
enter:
    .a16
    .i16
    jsr floor_arm                   ; 32 KB interleaved plane + 6 colours + M7SEL

    ; ---- the roll, seeded before anything reads it ------------------------
    ; This also stamps the camera origin shadow — both the constant half
    ; (M7X/M7HOFS) and the moving half (M7Y/M7VOFS from posy) — so the FIRST
    ; VBlank's commit has real values rather than power-on garbage.
    jsr roll_init

    ; ---- the bow axis, likewise ------------------------------------------
    ; Boots at the FULL bow: the bowed curve is what the
    ; rail is a showcase of, so that is what a viewer sees without touching
    ; anything. Step 0 (flat) is reachable by holding Down — the runtime
    ; non-vacuity control, inside the shipping binary.
    ;
    ; MB_BOW_AP is seeded to the SAME value deliberately: mb_arm points the A
    ; table at MB_BOW directly, so the applied word must agree or the first
    ; VBlank would re-point to a table that is already pointed at.
    lda #MB_BOW_MAX
    sta z:MB_BOW
    sta z:MB_BOW_AP

    jsr mb_arm                      ; both index tables + both channel shadows
    jsr rg_arm                      ; the three COLDATA planes + colour math

    ; ---- the scene's base display ----------------------------------------
    ; BGMODE and TM are split_band's `seed = true` reg claim: the value written
    ; here is a base its two HDMA claims then drive per scanline from line 0.
    ; The seed is the FLOOR band's, so a frame in which HDMA never armed would
    ; render a coherent Mode 7 picture rather than whatever the PPU powered on
    ; holding.
    sep #$20
    .a8
    lda #SB_MODE_BOT                ; BGMODE 7: the affine plane, BG1 only
    sta a:$2105
    lda #SB_TM_BOT
    sta a:$212C                     ; TM: the floor

    ; ---- arm split_band's two channels in the scene_mgr shadow -----------
    ; The feature ships the TABLES and no arm routine (it is two ROM tables and
    ; five bound symbols), so the scene stages the channel registers — the same
    ; block microzero's and racer's race scenes carry. Both tables live in the
    ; CODE bank, so A1B comes from `^` on the label; the indirect TM channel
    ; needs DASB as well, and its data sits in the same bank as its index table.
    rep #$10
    .i16
    ldx #(ES_H_BGM_CH * 16)
    lda #ES_H_BGM_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: direct, 1 byte
    lda #ES_H_BGM_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: $2105
    lda #^sb_bgmode_tab
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: table bank
    rep #$20
    .a16
    lda #.loword(sb_bgmode_tab)
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: table addr
    sep #$20
    .a8
    ldx #(ES_H_TMI_CH * 16)
    lda #ES_H_TMI_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 1 byte
    lda #ES_H_TMI_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: $212C
    lda #^sb_tm_tab
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: index-table bank
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: data bank (same bank)
    rep #$20
    .a16
    lda #.loword(sb_tm_tab)
    sta f:ES_SM_HDMA_LONG+2, x
    sep #$20
    .a8

    ; ---- arm the seven channels ------------------------------------------
    ; The scene_mgr NMI applies this shadow to HDMAEN on every armed frame; the
    ; channel REGISTERS were staged by mb_arm and rg_arm into the 128-byte
    ; shadow the same NMI MVNs to $4300. Enabling a channel whose shadow was
    ; never staged is the shape that reads as "the picture is garbage" — hence
    ; both halves in one enter, in this order.
    lda #((1 << ES_H_MBA_CH) | (1 << ES_H_MBD_CH))
    ora #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH))
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH))
    sta z:ES_SM_NMI+2               ; HDMAEN shadow (NMI applies it)

    ; ---- lift the blank, through the FADE ---------------------------------
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` and its `lda #1`
    ; therefore assembles as a ONE-byte immediate; call it from A16 and the CPU
    ; eats the following opcode byte as that immediate's high half, the ramp
    ; never arms, INIDISP stays at brightness 0, and the ROM renders black with
    ; perfectly correct VRAM and CGRAM. That is rule 6's
    ; silent-corruption class arriving through a CROSS-FILE contract width-lint
    ; cannot see in either direction.
    jsr fade_start_in
    rep #$20
    .a16
    rts

; --- tick: one game frame ---------------------------------------------------
; In/out: A16/I16, DB=0.
;
; TWO CALLS.
;   mb_input   the pad's one axis: Up/Down walks the bow step, clamped at both
;  ends. The axis exists deliberately: an axis nothing drives is a
;              claim without evidence, and step 0 is the control that makes
;              "the floor bows" assertable.
;   roll_tick  the leg cycle and the 24-bit position add. It runs
;              UNCONDITIONALLY: the roll is the rail, and there is no pause.
;
; ADVANCE-THEN-COMMIT: this frame's tick moves the state, the next VBlank's
; hook commits it to the ports. So the picture a frame renders is always the
; state its own tick produced, and no write-twice port is touched during
; active display.
tick:
    .a16
    .i16
    jsr mb_input
    jsr roll_tick
    rts

; --- exit: undo what enter armed --------------------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr exit contract).
;
; The plane's VRAM and CGRAM are NOT torn down: the next enter re-declares
; everything it owns (scene_mgr's contract), and re-uploading 32 KB to prove a
; point costs a frame. What IS undone is the display state this scene turned on
; — including rgb_gradient's colour math, which would otherwise leave a
; successor adding a stray fixed colour to layers it never asked to tint.
; HDMAEN is scene_mgr's own to clear at the transition. This rail has no edges,
; so nothing reaches here — it is the contract, kept honest.
exit:
    .a16
    .i16
    jsr rg_disarm                   ; CGWSEL/CGADSUB/COLDATA back to boot state
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
