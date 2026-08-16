; =============================================================================
; mode7_persp.asm — PPU-offloaded per-scanline perspective (split_h_2p style)
; =============================================================================
; Two INDIRECT HDMA channels (DMAP $43: indirect + write-2-regs-twice) stream
; ROM pose tables through M7A/B (CH ES_H_M7AB_CH) and M7C/D (ES_H_M7CD_CH). The
; WRAM index tables (ES_PERSP_IDX: 2 x 16 B) shape the band:
;  [HUD_LINES non-repeat, ptr] one harmless unit at line 0, skip band
;  [$80|127, ptr] band rows 0..126 (lines 44..170)
;  [$80|BAND_TAIL, ptr + 127*4] band rows 127..end (lines 171..223)
;  [0]
; Retarget = persp_set_pose: rewrite the three pointers per table + the two
; DASB banks in the scene_mgr channel shadow — ~30 stores, VBlank-safe. Camera
; origin is CPU shadow stores (ES_M7ORG, committed by the NMI hook).
;
; PERSP_LINES = 224 - HUD_LINES (the generated blobs carry exactly this many
; rows; gen_pose_tables.py --lines must match — asserted in the game build).
PERSP_LINES = 224 - HUD_LINES
BAND_TAIL   = PERSP_LINES - 127

; --- persp_arm: build index tables + channel shadow (scene enter) -----------
; In: A16/I16, DB=0. Uses the scene's emitted ES_H_*_CH + ES_PERSP_IDX. Caller
; then persp_set_pose to point at a heading, and ORs the enable bits.
persp_arm:
    .a16
    .i16
    ; ---- the declared init contract: zero the WHOLE claim first ----------
    ; The tail bytes past each table's terminator are never stamped, but the
    ; DMA controller's terminator processing still fetches indirect-address
    ; bytes after the $00 — real hardware reads them, so they must not be
    ; power-on garbage (uninit-read contract, caught by the race-path boot
    ; detector).
    lda #0
    ldx #(ES_PERSP_IDX_SIZE - 2)
:   sta f:ES_PERSP_IDX_LONG, x
    dex
    dex
    bpl :-
    ; ---- index table skeletons (counts + terminators; ptrs by set_pose) ---
    sep #$20
    .a8
    lda #HUD_LINES
    sta f:ES_PERSP_IDX_LONG+0       ; AB head: non-repeat skip
    sta f:ES_PERSP_IDX_LONG+16      ; CD head
    lda #255                        ; repeat flag | 127 lines
    sta f:ES_PERSP_IDX_LONG+3
    sta f:ES_PERSP_IDX_LONG+19
    lda #(128 | BAND_TAIL)          ; repeat flag | tail lines
    sta f:ES_PERSP_IDX_LONG+6
    sta f:ES_PERSP_IDX_LONG+22
    lda #0
    sta f:ES_PERSP_IDX_LONG+9       ; terminators
    sta f:ES_PERSP_IDX_LONG+25
    ; ---- channel shadow: CH m7ab ------------------------------------------
    rep #$10
    .i16
    ldx #(ES_H_M7AB_CH * 16)
    lda #ES_H_M7AB_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 2-regs-write-twice
    lda #ES_H_M7AB_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_PERSP_IDX_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: index table bank ($7E)
    rep #$20
    .a16
    lda #ES_PERSP_IDX
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: AB index table
    sep #$20
    .a8
    ldx #(ES_H_M7CD_CH * 16)
    lda #ES_H_M7CD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_M7CD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7C
    lda #ES_PERSP_IDX_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    rep #$20
    .a16
    lda #(ES_PERSP_IDX + 16)
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: CD index table
    rts

; --- persp_set_pose: point both channels at heading A (0..63) ---------------
; In: A16 = heading. VBlank- or forced-blank-safe (index tables + DASB only).
; ptr = $8000-window ADDR + (h & 31)*1024; bank = blob base + (h >> 5).
; AB and CD blobs share the same in-window layout, so the three pointer words
; are identical for both tables; only the DASB banks differ.
persp_set_pose:
    .a16
    .i16
    pha
    and #31
    xba                             ; *256
    asl
    asl                             ; *1024
    clc
    adc #ES_R_POSES_AB_T0_ADDR      ; window-aligned base ($8000)
    ; head + span A pointers = pose base; span B = base + 127*4
    sta f:ES_PERSP_IDX_LONG+1
    sta f:ES_PERSP_IDX_LONG+4
    sta f:ES_PERSP_IDX_LONG+17
    sta f:ES_PERSP_IDX_LONG+20
    clc
    adc #(127 * 4)
    sta f:ES_PERSP_IDX_LONG+7
    sta f:ES_PERSP_IDX_LONG+23
    ; ---- DASB banks: blob base + (h >> 5) ---------------------------------
    pla
    .repeat 5
        lsr
    .endrepeat
    pha
    clc
    adc #ES_R_POSES_AB_T0_BANK
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #(ES_H_M7AB_CH * 16)
    sta f:ES_SM_HDMA_LONG+7, x      ; CH ab DASB
    rep #$20
    .a16
    pla
    clc
    adc #ES_R_POSES_CD_T0_BANK
    sep #$20
    .a8
    ldx #(ES_H_M7CD_CH * 16)
    sta f:ES_SM_HDMA_LONG+7, x      ; CH cd DASB
    rep #$20
    .a16
    rts

; --- persp_commit_origin: NMI-side M7X/Y/HOFS/VOFS from the DP shadows ------
; In: A8/I16, DB=0 (NMI hook context). ES_M7ORG: +0 M7X +2 M7Y +4 HOFS +6 VOFS.
persp_commit_origin:
    .a8
    .i16
    lda z:ES_M7ORG+0
    sta a:$211F
    lda z:ES_M7ORG+1
    sta a:$211F                     ; M7X (13-bit, low then high)
    lda z:ES_M7ORG+2
    sta a:$2120
    lda z:ES_M7ORG+3
    sta a:$2120                     ; M7Y
    lda z:ES_M7ORG+4
    sta a:$210D
    lda z:ES_M7ORG+5
    sta a:$210D                     ; M7HOFS
    lda z:ES_M7ORG+6
    sta a:$210E
    lda z:ES_M7ORG+7
    sta a:$210E                     ; M7VOFS
    rts
