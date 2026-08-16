; =============================================================================
; scenes/cockpit.asm — the whole rail: the seam, the panel, the spin, the toggle
; =============================================================================
; The rail's two entry points, against the emitted symbols:
;
;   enter   upload the floor palette + CHR + a position-wrapped world seed;
;           seed BGMODE/TM for the whole frame; paint the BG3 instrument panel;
;           arm split_band's two band channels and mode7_persp's two matrix
;           channels in the scene_mgr HDMA shadow; set the camera origin.
;   tick    spin the heading from input (the "split under load" stress), flip
;           the split OFF/ON on a fresh A press, and re-stage the BG3 readout
;           only when the shown value is stale.
;
; TWO DEFENCES A HAND-BUDGETED ROM WOULD CARRY, and why neither is here — a
; defensive artefact is not automatically work:
;
;   A TWO-PALETTE CGRAM `.assert` guarding a hand-budgeted floor palette
;   (CGRAM 0..) against a hand-budgeted HUD palette (CGRAM 16..). Here
;   `mode7_floor` claims `cgram words = 17, at = 0` and `bg_text` claims
;   `words = 4, at = 28`; the ALLOCATOR proves they are disjoint, for every
;   composition, before a byte is assembled. The guard is not implemented — it
;   is discharged by the declaration.
;
;   MANUAL BG3 PLACEMENT in the upper 32 KB (hand-picked `BG3SC` / `BG34NBA`
;   bytes, hand-narrated from word addresses also picked by hand), which a
;   fixed-mode graphics path needs because it would otherwise put BG3 inside
;   Mode 7's low 32 KB. Here the map is at ES_V_TEXT_MAP and the CHR at
;   ES_V_TEXT_CHR because the allocator placed them past the `kind = "mode7"`
;   region, and the register bytes are the emitted `_SC_BASE` / `_NBA` — a
;   collision is refused at build time rather than defended against.

.scope cockpit

; --- the scene's engine features (inside the scope: their claims are scene) --
.include "mode7_persp.asm"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
; In/out: A16/I16, DB=0.
enter:
    .a16
    .i16
    ; ---- user state ------------------------------------------------------
    sep #$20
    .a8
    stz a:US_HEADING
    stz a:US_HEADING_AP
    lda #1
    sta a:US_SPLIT_ON           ; the split is ARMED at boot
    rep #$20
    .a16
    stz a:US_FRAMES
    lda #$FFFF
    sta a:US_HUD_VAL            ; impossible value -> the first tick stages
    ; ---- CGRAM: the 17-colour floor palette (pinned at index 0) ----------
    ldx #.loword(floor_pal_bin)
    lda #^floor_pal_bin
    ldy #ES_R_FLOOR_PAL_ROM_SIZE
    jsr m7_upload_pal
    ; ---- Mode 7 CHR: 12 tiles into the odd VRAM bytes --------------------
    ldx #.loword(floor_tiles_bin)
    ldy #ES_R_FLOOR_TILES_SIZE
    lda #^floor_tiles_bin
    jsr m7_upload_chr
    ; ---- a position-wrapped 128x128 seed of the world around the camera --
    ldx #CAM0_TX
    ldy #CAM0_TY
    jsr m7_upload_seed
    ; ---- the scene's base display shape ----------------------------------
    ; BGMODE and TM are SEEDS: split_band's two active-display HDMA claims
    ; override them per scanline from line 0 (its `seed = true` +
    ; `scene_writes` declaration is what says these two writes are a base and
    ; not a second owner). With the split toggled OFF they are what the frame
    ; renders as — full-screen Mode 7, the rail's own control picture.
    sep #$20
    .a8
    stz a:$211A                 ; M7SEL: wrap, no flips
    lda #SB_MODE_BOT
    sta a:$2105                 ; BGMODE (HDMA overrides per line)
    lda #SB_TM_BOT
    sta a:$212C                 ; TM (HDMA overrides per line)
    rep #$20
    .a16
    jsr panel_paint
    jsr band_arm
    ; ---- perspective: index tables + channel shadow + heading 0 ----------
    jsr persp_arm
    lda #0
    jsr persp_set_pose
    ; ---- the camera origin (NMI hook commits it every armed frame) -------
    ; Written once: this camera spins in place and never travels.
    lda #CAM0_PX
    sta z:ES_M7ORG+0            ; M7X
    lda #CAM0_PY
    sta z:ES_M7ORG+2            ; M7Y
    lda #(CAM0_PX - 128)
    sta z:ES_M7ORG+4            ; HOFS: screen centre x
    lda #(CAM0_PY - PIVOT_LINE)
    sta z:ES_M7ORG+6            ; VOFS: pivot at PIVOT_LINE
    ; ---- HDMAEN shadow: the two band channels + the two matrix channels --
    jsr hdmaen_apply
    rts

exit:
    .a16
    .i16
    rts

; --- band_arm: split_band's two channels into the scene_mgr HDMA shadow -----
; In/out: A16/I16, DB=0. race.asm's block, against THIS rail's emitted channel
; numbers — the tables themselves are split_band's, built from this rail's five
; binding symbols.
; WIDTH-RISK: entry A16/I16; toggles to A8 for the byte fields and back; exits
; A16/I16.
band_arm:
    .a16
    .i16
    sep #$20
    .a8
    ldx #(ES_H_BGM_CH * 16)
    lda #ES_H_BGM_DMAP
    sta f:ES_SM_HDMA_LONG+0, x  ; DMAP: direct, 1 byte
    lda #ES_H_BGM_BBAD
    sta f:ES_SM_HDMA_LONG+1, x  ; BBAD: $2105
    lda #^sb_bgmode_tab
    sta f:ES_SM_HDMA_LONG+4, x  ; A1B: table bank
    rep #$20
    .a16
    lda #.loword(sb_bgmode_tab)
    sta f:ES_SM_HDMA_LONG+2, x  ; A1T: table addr
    sep #$20
    .a8
    ldx #(ES_H_TMI_CH * 16)
    lda #ES_H_TMI_DMAP
    sta f:ES_SM_HDMA_LONG+0, x  ; DMAP: indirect, 1 byte
    lda #ES_H_TMI_BBAD
    sta f:ES_SM_HDMA_LONG+1, x  ; BBAD: $212C
    lda #^sb_tm_tab
    sta f:ES_SM_HDMA_LONG+4, x  ; A1B: index-table bank
    sta f:ES_SM_HDMA_LONG+7, x  ; DASB: data bank (same bank)
    rep #$20
    .a16
    lda #.loword(sb_tm_tab)
    sta f:ES_SM_HDMA_LONG+2, x  ; A1T: index table addr
    rts

; --- hdmaen_apply: publish the enable mask the NMI applies ------------------
; The matrix pair is ALWAYS enabled; the two band channels are enabled only
; while US_SPLIT_ON. This is the whole of the toggle — the tables stay armed in
; the shadow, so re-enabling is one OR rather than a re-arm, and the OFF frame
; renders the SEEDED BGMODE/TM for all 224 lines.
; In/out: A16/I16, DB=0.
; WIDTH-RISK: entry A16/I16; A8 for the shadow byte; exits A16/I16.
;
; TWO STRAIGHT-LINE STORES rather than one store fed by a branch: the channel
; lint traces the value reaching ES_SM_NMI+2 back to an immediate built from
; the emitted ES_H_*_CH numbers, and a mask assembled across a branch target
; has no traceable source in the file (it says so, by name). The duplication is
; the gate's price and it is the right price — the alternative is a suppression
; comment on the one write that decides which channels run.
hdmaen_apply:
    .a16
    .i16
    sep #$20
    .a8
    lda a:US_SPLIT_ON
    beq @off
    lda #((1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH) | (1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH))
    sta z:ES_SM_NMI+2           ; HDMAEN shadow: matrix pair + both band channels
    rep #$20
    .a16
    rts
@off:
    .a8
    .i16
    lda #((1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    sta z:ES_SM_NMI+2           ; HDMAEN shadow: the matrix pair alone
    rep #$20
    .a16
    rts

; --- panel_paint: the BG3 instrument panel (forced blank, scene enter) ------
; The static frame + labels; the live readout's four cells are painted here too
; so the tilemap is COMPLETE before the screen comes on, and from then on only
; their CONTENT changes through the VBlank cell queue.
; In/out: A16/I16, DB=0.
panel_paint:
    .a16
    .i16
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #SHD_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    lda #SHD_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_rule)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_rule
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 0 * 32 + 1)   ; row 0: the top frame rule
    jsr text_puts
    lda #.loword(s_gauge)
    sta z:ES_TXT_PTR
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 1 * 32 + 1)   ; row 1: the gauge-light row
    jsr text_puts
    lda #.loword(s_label)
    sta z:ES_TXT_PTR
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 2 * 32 + 2)   ; row 2: the instrument label
    jsr text_puts
    lda #.loword(s_claim)
    sta z:ES_TXT_PTR
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 3 * 32 + 1)   ; row 3: what the band IS
    jsr text_puts
    lda #.loword(s_rule)
    sta z:ES_TXT_PTR
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 4 * 32 + 1)   ; row 4: the bottom frame rule
    jsr text_puts
    lda #0                              ; the readout's four cells, painted so
    ldx #SHD_HUD_CELL                   ;   the map is complete under blank
    jsr text_put_hex4
    ; ---- the BG3 register bases + the text palette (CGRAM 28..31) --------
    sep #$20
    .a8
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    stz a:$2111                 ; BG3HOFS: the panel does not scroll
    stz a:$2111
    stz a:$2112                 ; BG3VOFS
    stz a:$2112
    lda #ES_C_TEXT_PAL
    sta a:$2121
    lda #$00                    ; word 28, colour 0: the transparent slot
    sta a:$2122
    sta a:$2122
    lda #$84                    ; word 29, colour 1: dark navy (the panel body)
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$E0                    ; word 30, colour 2: amber (the frame rules)
    sta a:$2122
    lda #$02
    sta a:$2122
    lda #$FF                    ; word 31, colour 3: white (the glyph ink)
    sta a:$2122
    lda #$7F
    sta a:$2122
    rep #$20
    .a16
    rts

; --- tick: the once-per-frame heartbeat ------------------------------------
; In/out: A16/I16, DB=0 (scene_mgr's tick contract).
tick:
    .a16
    .i16
    inc a:US_FRAMES
    jsr spin_step
    jsr toggle_step
    jsr hud_step
    rts

.ifdef SHD_AUTODEMO
; --- spin_step (-DSHD_AUTODEMO): the self-running camera ---------------------
; The autonomous build: the frame counter replaces the pad axis, so the
; split-under-load stress runs with no controller attached.
;
; ONE AXIS, driving both bands. The instrument here is bg_text's 4-cell readout
; of the HEADING itself (`hud_step` reprints on change), so the single
; autonomous heading step animates the floor band's matrix AND the panel band's
; readout — two moving things from one axis, because the instrument is a
; function of the camera.
;
; THE RATE: `pose_rom` is indexed by 64 headings, so stepping ROT_SPD once every
; FOUR frames is a full turn in 256 frames — a sweep slow enough to read and
; fast enough to exercise every pose within a capture window.
;
; NO NEW STATE. `US_FRAMES` is the scene's existing free-running heartbeat
; (state.toml) and the phase is read out of it. A dp claim that existed only in
; the -D build would shift the allocator's map and move the SHIPPING ROM's md5
; for a variant it does not contain — split_v_fight's demo_walk pays the same
; toll (fight.asm:326-330).
;
; `toggle_step` is deliberately left ARMED and pad-driven: a self-toggling split
; would make the picture unstable to drive.
; In/out: A16/I16, DB=0.
SHD_AUTO_MASK = 3               ; step every 4th frame — a full turn in 256
spin_step:
    .a16
    .i16
    lda a:US_FRAMES
    and #SHD_AUTO_MASK
    bne @auto_done
    sep #$20
    .a8
    lda a:US_HEADING
    clc
    adc #ROT_SPD
    and #HEAD_MASK
    sta a:US_HEADING
    rep #$20
    .a16
@auto_done:
    ; Reached A16 by the `bne` above and A16 by fall-through past the `rep`.
    .a16
    .i16
    rts
.else
; --- spin_step: Left/Right spin the camera ---------------------------------
; The heading is what pose_rom is indexed by, so a change here means the NMI
; hook re-points both INDIRECT matrix channels — the live rebuild the split
; must hold under. HELD, not edge-triggered: the camera spins for as long as the
; direction is down.
; In/out: A16/I16, DB=0.
spin_step:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_RIGHT
    beq @spin_left
    sep #$20
    .a8
    lda a:US_HEADING
    clc
    adc #ROT_SPD
    and #HEAD_MASK
    sta a:US_HEADING
    rep #$20
    .a16
    rts
@spin_left:
    .a16
    .i16
    lda z:ES_INP_CUR
    bit #JOY_LEFT
    beq @spin_done
    sep #$20
    .a8
    lda a:US_HEADING
    sec
    sbc #ROT_SPD
    and #HEAD_MASK
    sta a:US_HEADING
    rep #$20
    .a16
@spin_done:
    .a16
    .i16
    rts
.endif

; --- toggle_step: A cycles the mode/TM split OFF and back ON ----------------
; The split's lifecycle, deliberately without two things a hand-rolled version
; of it tends to grow:
;
;   NO ONE-SHOT LATCH. A terminal "already toggled" state means "drive the
;   claimed transition BOTH directions" stops after one round trip. Every fresh
;   press flips it here, so a test walks ON -> OFF -> ON -> OFF.
;
;   NO HAND-ROLLED EDGE DETECTOR. `input` already publishes ES_INP_PRESS = cur
;   AND NOT prev every frame. Writing a second one here cost a real debugging
;   round: `ldx a:US_PREV_A` under I16 reads TWO bytes, so it picked up
;   US_SPLIT_ON in the high half and the branch never took the edge — the split
;   rendered armed in every state. The state word went with the code.
;
; In/out: A16/I16, DB=0.
toggle_step:
    .a16
    .i16
    lda z:ES_INP_PRESS          ; the FRESH press edge, not the held state
    bit #JOY_A
    beq @tog_done
    sep #$20
    .a8
    lda a:US_SPLIT_ON
    eor #$01                    ; 1 <-> 0
    sta a:US_SPLIT_ON
    rep #$20
    .a16
    jsr hdmaen_apply            ; republish the mask the NMI applies
@tog_done:
    .a16
    .i16
    rts

; --- hud_step: re-stage the readout only when the shown value is stale ------
; hud_game's reprint-on-change discipline. The queue's staging is therefore a
; real test surface: a frame with no heading change stages nothing.
; In/out: A16/I16, DB=0.
hud_step:
    .a16
    .i16
    sep #$20
    .a8
    lda a:US_HEADING
    rep #$20
    .a16
    and #$00FF                  ; the A8 load left the high byte stale
    cmp a:US_HUD_VAL
    beq @hud_done
    sta a:US_HUD_VAL
    ldx #SHD_HUD_CELL
    ldy #SHD_TXT_ATTR
    sty z:ES_TXT_TMP
    jsr text_queue_hex4
@hud_done:
    .a16
    .i16
    rts

; --- strings ----------------------------------------------------------------
; The panel's five rows. Rows 0 and 4 are the frame rules, row 1 the decorative
; gauge-light row of alternating lit/dim cells, row 2 the instrument label + the
; live readout, and row 3 says what the band IS — the picture is the claim, so
; the picture states it.
s_rule:  .byte "==============================", 0
s_gauge: .byte ".o.o.o.o.o.o.o.o.o.o.o.o.o.o.o", 0
s_label: .byte "HEAD", 0
s_claim: .byte "MODE 1 BG3 OVER MODE 7 BG1", 0

.endscope
