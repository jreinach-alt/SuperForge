; =============================================================================
; race — the racer rail's only scene
; =============================================================================
; The whole rail: a Mode-7 perspective floor under a sky band, a kart with
; lean frames and a sprite speed bar over it, a day-night COLDATA wash across
; both, static red/white rumble strips, off-road drag from the map,
; and a START freeze-frame.
;
; SEVEN OF THE EIGHT HDMA CHANNELS ARE ARMED HERE: split_band takes two
; (BGMODE + TM), mode7_persp two (M7A/B + M7C/D) and rc_grad three
; (COLDATA R/G/B), with oam_sprites and mode7_stream time-sharing two of those
; numbers in the VBlank phase. One channel is spare.
.scope race

.include "engine_state_race.inc"    ; GENERATED — this scene's map

; Where rc_grad's day-night wash LANDS, declared at the composition site
; because it is this scene's look and not the feature's (rc_grad.asm has no
; default). BG1 is the Mode-7 floor and BG2 the sky band; the band split
; already separates them, so one value covers both. OBJ is absent, so the kart
; and the speed bar render UNTINTED — which is what keeps the bar readable at
; midnight and is the same routing microzero's HUD relies on.
RCG_MATH_LAYERS = (1 | 2)
RCG_KEYS_ADDR   = ::ES_R_SKY_KEYS_ADDR
RCG_KEYS_BANK   = ::ES_R_SKY_KEYS_BANK
RCG_KEYS_COUNT  = ::RC_TOD_KEYS     ; the generator's count, via racer_move.inc.
                                    ; `::` LOAD-BEARING: it reaches a `.repeat`
                                    ; count in rc_grad.asm, which must be a
                                    ; constant expression, and ca65 2.18 defers
                                    ; an unqualified parent-scope lookup inside
                                    ; a `.scope` (the same measurement col_map's
                                    ; binding block records).

; race-only engine feature code — INSIDE the scope: its claims are scene-scoped
.include "mode7_persp.asm"
.include "rc_grad.asm"

; mode7_stream's world binding, declared at the composition site for the same
; reason: WHICH world the streaming kernels read is the game's, not the
; feature's. The `::` is LOAD-BEARING — inside a `.scope`, ca65 2.18 defers an
; unqualified parent-scope lookup, and M7S_CHUNKS reaches a `.repeat` count,
; which must be a constant expression.
M7S_WORLD_WIN = ::ES_R_WORLD_MAP_T0_ADDR
M7S_BLOB_BANK = ::ES_R_WORLD_MAP_T0_BANK
M7S_CHUNKS    = ::ES_R_WORLD_MAP_CHUNKS     ; DERIVED, not narrated
.include "mode7_stream.asm"

; rc_kart's binding: where this rail plants its vehicle and its HUD.
RCK_LINE     = KART_LINE
RCK_BAR_LINE = BAR_LINE
.include "rc_kart.asm"
.include "sky_band.asm"

; col_map's world binding. The sizes are log2 of world.inc's WORLD_T_TILES;
; the `.assert` keeps that derivation honest rather than letting two spellings
; of 512 drift apart.
CM_WORLD_W_LOG2      = 9                        ; 512 tiles wide
CM_WORLD_H_LOG2      = 9                        ; 512 tiles tall
.assert (1 << CM_WORLD_W_LOG2) = WORLD_T_TILES, error, "col_map world width disagrees with world.inc WORLD_T_TILES"
.assert (1 << CM_WORLD_H_LOG2) = WORLD_T_TILES, error, "col_map world height disagrees with world.inc WORLD_T_TILES"
CM_WORLD_BLOB        = ::ES_R_WORLD_MAP_T0_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_WORLD_MAP_T0_BANK
CM_WORLD_BLOB_CHUNKS = ::ES_R_WORLD_MAP_CHUNKS  ; DERIVED, not narrated
CM_FLAGS             = ::col_flags_bin          ; col_map_rom's table
.include "col_map.asm"

; rc_logic's binding: the heading LUT and the world's wrap. Both belong to the
; rail's world, not to the kernel.
RCL_MOVE_LUT   = ::rc_move_lut
RCL_WORLD_MASK = WORLD_PX_MASK
.include "rc_logic.asm"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
enter:
    .a16
    .i16
    jsr rc_arm                  ; physics + the day-night clock
    ; ---- CGRAM: the 17-colour floor palette (pinned at index 0) -----------
    ldx #.loword(floor_pal_bin)
    lda #^floor_pal_bin
    ldy #ES_R_FLOOR_PAL_ROM_SIZE
    jsr m7_upload_pal
    ; ---- Mode 7 CHR: 12 tiles into the odd VRAM bytes ---------------------
    ldx #.loword(floor_tiles_bin)
    ldy #ES_R_FLOOR_TILES_SIZE
    lda #^floor_tiles_bin
    jsr m7_upload_chr
    ; ---- position-wrapped 128x128 seed of the world around the camera -----
    ldx #CAM0_TX
    ldy #CAM0_TY
    jsr m7_upload_seed
    ; ---- Mode 7: M7A-D are HDMA-owned (pose LUTs); origin via DP shadows ---
    sep #$20
    .a8
    stz a:$211A                 ; M7SEL: wrap, no flips
    lda #7
    sta a:$2105                 ; BGMODE 7 (HDMA overrides per line)
    lda #1
    sta a:$212C                 ; TM: BG1 base (HDMA overrides per line)
    ; ---- arm the split-band HDMA channels in the scene_mgr shadow ---------
    rep #$10
    .i16
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
    sta f:ES_SM_HDMA_LONG+2, x
    ; ---- perspective: index tables + channel shadow + heading 0 -----------
    jsr persp_arm
    lda #0
    jsr persp_set_pose
    ; camera origin shadows (the NMI hook commits them every armed frame)
    lda #CAM0_PX
    sta z:ES_M7ORG+0            ; M7X
    lda #CAM0_PY
    sta z:ES_M7ORG+2            ; M7Y
    lda #(CAM0_PX - 128)
    sta z:ES_M7ORG+4            ; HOFS: screen centre x
    lda #(CAM0_PY - PIVOT_LINE)
    sta z:ES_M7ORG+6            ; VOFS: pivot at the kart line
    ; ---- day-night: the three WRAM header tables + colour math ------------
    jsr rcg_arm
    ; ---- streaming: tile tracking synced to the seeded window -------------
    jsr stream_arm
    ; ---- sky: BG2 ramp CHR/map/palette + the BG2 register bases -----------
    jsr sky_arm
    ; ---- kart + speed bar: CHR, OBJ palette, OBSEL, the OAM slots ---------
    jsr kart_arm
    ; ---- HDMAEN shadow: SEVEN channels (the NMI applies it) ---------------
    sep #$20
    .a8
    lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH) | (1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    ora #((1 << ES_H_RCGR_CH) | (1 << ES_H_RCGG_CH) | (1 << ES_H_RCGB_CH))
    sta z:ES_SM_NMI+2
    rep #$20
    .a16
    rts

exit:
    .a16
    .i16
    jsr rcg_disarm              ; colour math back to boot state (global regs)
    jsr kart_disarm             ; re-park every claimed OAM slot
    rts

; --- tod_tick: the day-night phase machine ----------------------------------
; DAY(0)/NIGHT(2) holds count down RC_TOD_HOLD frames and change nothing.
; Blends (TO_NIGHT=1 / TO_DAY=3) step the keyframe index every RC_TOD_STEP
; frames and RETARGET the three gradient header tables — six stores, no
; rebuild. Entering a hold snaps the index to the exact endpoint, so a
; rounding drift cannot accumulate across cycles.
; In/out: A16/I16, DB=0.
tod_tick:
    .a16
    .i16
    lda f:US_TOD_T_LONG
    dec a
    sta f:US_TOD_T_LONG
    bne @in_phase
    ; ---- the timer expired: advance the phase -----------------------------
    sep #$20
    .a8
    lda f:US_TOD_PH_LONG
    inc a
    and #3
    sta f:US_TOD_PH_LONG
    and #1
    bne @enter_blend
    ; entering a HOLD: snap the keyframe to the exact endpoint
    lda f:US_TOD_PH_LONG
    beq @snap_day
    lda #(RC_TOD_KEYS - 1)      ; phase 2 = the NIGHT hold
    bra @snap_store
@snap_day:
    .a8
    .i16
    lda #0                      ; phase 0 = the DAY hold
@snap_store:
    .a8
    .i16
    sta f:US_GRAD_K_LONG
    rep #$20
    .a16
    lda #RC_TOD_HOLD
    sta f:US_TOD_T_LONG
    bra @apply
@enter_blend:
    .a8
    .i16
    rep #$20
    .a16
    lda #((RC_TOD_KEYS - 1) * RC_TOD_STEP)
    sta f:US_TOD_T_LONG
    rts
@in_phase:
    .a16
    .i16
    sep #$20
    .a8
    lda f:US_TOD_PH_LONG
    and #1
    beq @hold_ret               ; holds: nothing to retarget
    rep #$20
    .a16
    ; step on the frames where the timer is a multiple of RC_TOD_STEP: the
    ; timer runs (KEYS-1)*STEP-1 .. 0 here, so this fires exactly KEYS-1 times
    lda f:US_TOD_T_LONG
    and #(RC_TOD_STEP - 1)
    bne @tod_done
    sep #$20
    .a8
    lda f:US_TOD_PH_LONG
    cmp #3
    beq @toward_day
    lda f:US_GRAD_K_LONG        ; toward night: k++
    inc a
    cmp #RC_TOD_KEYS
    bcc @k_store
    lda #(RC_TOD_KEYS - 1)
    bra @k_store
@toward_day:
    .a8
    .i16
    lda f:US_GRAD_K_LONG        ; toward day: k--
    beq @k_store
    dec a
@k_store:
    .a8
    .i16
    sta f:US_GRAD_K_LONG
    rep #$20
    .a16
    bra @apply
@hold_ret:
    .a8
    .i16
    rep #$20
    .a16
    rts
@apply:
    .a16
    .i16
    sep #$20
    .a8
    lda f:US_GRAD_K_LONG
    rep #$20
    .a16
    and #255                    ; the A8 load left the high byte stale
    jsr rcg_set_key
@tod_done:
    .a16
    .i16
    rts

; THE RUMBLE STRIPES ARE STATIC — there is no kerb routine here, and the
; absence is the design. Cycling a pair of kerb CGRAM entries reads on screen
; as the kerb flickering rather than as the kart moving past it, which is the
; opposite of the speed cue it is meant to give. The red and white blocks are
; two fixed entries of the floor palette mode7_floor uploads at enter, and
; nothing writes CGRAM after that.

; --- tick: one frame ---------------------------------------------------------
tick:
    .a16
    .i16
    jsr rc_pause
    beq @racing
    rts                         ; frozen: the whole body is skipped
@racing:
    .a16
    .i16
    jsr rc_steer
    jsr rc_throttle
    jsr rc_offroad              ; the map is collision ground truth
    jsr rc_move
    ; scroll shadows follow the origin (the NMI hook commits all four)
    lda z:ES_M7ORG + 0
    sec
    sbc #128
    sta z:ES_M7ORG + 4          ; HOFS: screen centre x
    lda z:ES_M7ORG + 2
    sec
    sbc #PIVOT_LINE
    sta z:ES_M7ORG + 6          ; VOFS: pivot at the kart line
    jsr stream_tick
    ; ---- draw: the kart's frame and the bar's lit count --------------------
    jsr rc_bar_ticks            ; Y = lit ticks
    sep #$20
    .a8
    lda f:US_LEAN_LONG
    rep #$20
    .a16
    and #255
    tax                         ; X = lean index
    jsr kart_draw
    ; ---- effects ----------------------------------------------------------
    jsr tod_tick
    rts

; --- this scene's ROM blobs (allocator-claimed; the .asserts refuse drift) --
.segment "BANK14"
sky_map_bin:
    .incbin "sky_map.bin"
.assert ^sky_map_bin = ES_R_SKY_MAP_ROM_BANK, error, "sky_map bank drifted from allocator claim"
.assert .loword(sky_map_bin) = ES_R_SKY_MAP_ROM_ADDR, error, "sky_map addr drifted from allocator claim"
floor_tiles_bin:
    .incbin "floor_tiles.bin"
.assert ^floor_tiles_bin = ES_R_FLOOR_TILES_BANK, error, "floor_tiles bank drifted from allocator claim"
.assert .loword(floor_tiles_bin) = ES_R_FLOOR_TILES_ADDR, error, "floor_tiles addr drifted from allocator claim"
sky_chr_bin:
    .incbin "sky_chr.bin"
.assert ^sky_chr_bin = ES_R_SKY_CHR_ROM_BANK, error, "sky_chr bank drifted from allocator claim"
.assert .loword(sky_chr_bin) = ES_R_SKY_CHR_ROM_ADDR, error, "sky_chr addr drifted from allocator claim"
floor_pal_bin:
    .incbin "floor_pal.bin"
.assert ^floor_pal_bin = ES_R_FLOOR_PAL_ROM_BANK, error, "floor_pal bank drifted from allocator claim"
.assert .loword(floor_pal_bin) = ES_R_FLOOR_PAL_ROM_ADDR, error, "floor_pal addr drifted from allocator claim"
sky_pal_bin:
    .incbin "sky_pal.bin"
.assert ^sky_pal_bin = ES_R_SKY_PAL_ROM_BANK, error, "sky_pal bank drifted from allocator claim"
.assert .loword(sky_pal_bin) = ES_R_SKY_PAL_ROM_ADDR, error, "sky_pal addr drifted from allocator claim"
.segment "CODE"

.endscope
