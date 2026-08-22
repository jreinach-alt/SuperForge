; =============================================================================
; race scene — the static Mode 7 floor (flat matrix, fixed camera)
; =============================================================================
; The declared composition grows from here: split band, LUT perspective,
; gradient, streaming, sprites. This scene proves the allocator-driven
; Mode 7 floor renders from the declared claims.
.scope race
.include "engine_state_race.inc"    ; GENERATED — this scene's map

; BG3 2bpp tile attr for the HUD (palette 7, priority)
RACE_TXT_ATTR = (7 << 10) | (1 << 13)
; the one HUD cell that changes while the scene RUNS — race_logic stages it
; into the bg_text VBlank queue on every lap (forced-blank writes are not
; available to a running scene)
RACE_LAP_CELL = ES_V_TEXT_MAP + 2 * 32 + 28
; The VWF dialog row: row 3, col 2 (14 strip tiles = 112 px of proportional
; text). Row 3 and not 4 because BG3's glyphs land 6 scanlines BELOW row*8 on
; this scene (measured: the HUD's row 2 ink renders at y=22..28), so row 4 would
; put the dialog's last pixel rows at y=44..45 — past the mode-1 band, which
; ends at HUD_LINES = 44. Row 3 renders at y=30..37: clear of the HUD's ink
; above and wholly inside the band below.
VWF_ROW_CELL  = ES_V_TEXT_MAP + 3 * 32 + 2
; Reveal schedule, game-declared: a 128-frame slot per message, one glyph every
; 4 frames = 15 chars/s — a comfortable reading pace for a dialog crawl. Powers
; of two so the tick costs two masks and no division, and so the schedule is
; exactly reproducible from ES_SM_FRAME by a test.
;
; NOT REGION-SCALED, and the sentence above is the reason rather than an
; oversight. Everything else this rail measures in frames is a rate the player
; reads as SPEED and takes r or r^2 (game.toml carries that ledger); this one
; is an INSTRUMENT. The schedule is declared to be exactly reproducible from
; ES_SM_FRAME, and tests/test_vwf_render.py reads the rendered strip THROUGH
; that declaration — it steps to `frame % 128 == 0` and asserts the composited
; proportional advance of the four messages there. A playhead of its own would
; hold only on NTSC, so the price of a crawl that reads 20% faster on PAL is a
; proof that only works on one machine. Two mechanical facts say the same
; thing from the other side: ES_SM_FRAME is `scene_mgr`'s, so scaling it is a
; change to shared machinery every rail composes; and a scaled playhead
; advancing 1 or 2 SKIPS values, so `& 3 == 0` would drop glyphs and
; `& 127 == 0` could miss a whole message (meteor_event's measured trap, where
; an equality test on a scaled timer had to become a `bcc`).
VWF_SLOT_MASK = 127                 ; frame & this == 0 -> open the next message
VWF_TICK_MASK = 3                   ; frame & this == 0 -> reveal one glyph

; Where rgb_gradient's dusk wash LANDS, declared at the composition site
; because it is this scene's look and not the feature's (rgb_gradient.asm has
; no default). BG1 is the Mode-7 floor and BG2 the sky band; the band split
; already separates them, so one static value covers both, and BG3 (the HUD)
; and OBJ (the car) are absent so they render untinted.
RG_MATH_LAYERS = (1 | 2)

; race-only engine feature code — INSIDE the scope: its claims are scene-scoped
.include "mode7_persp.asm"
.include "rgb_gradient.asm"

; mode7_stream's world binding, declared at the composition site for the same
; reason col_map's is (below): WHICH world the streaming kernels read is the
; game's, not the feature's. mode7_stream carries no default for any of these —
; each missing one is a named `.error` (THE BINDING CONTRACT in
; mode7_stream.asm). The `::` is LOAD-BEARING for the same measured ca65 2.18
; reason spelled out at the col_map block below: inside a `.scope`, only a
; `::`-qualified reference resolves eagerly, and M7S_CHUNKS reaches a `.repeat`
; count, which must be a constant expression.
M7S_WORLD_WIN = ::ES_R_WORLD_MAP_T0_ADDR
M7S_BLOB_BANK = ::ES_R_WORLD_MAP_T0_BANK
M7S_CHUNKS    = ::ES_R_WORLD_MAP_CHUNKS     ; DERIVED, not narrated
.include "mode7_stream.asm"
.include "player_car.asm"
.include "race_logic.asm"
.include "sky_band.asm"
.include "vwf.asm"

; col_map's world binding, declared at the composition site for the same
; reason RG_MATH_LAYERS is: WHICH world the probe reads is the game's, not the
; feature's. col_map carries no default for any of these — each
; missing one is a named `.error`. The sizes are log2 of world.inc's
; WORLD_T_TILES; the `.assert` keeps that derivation honest rather than
; letting two spellings of 512 drift apart.
CM_WORLD_W_LOG2      = 9                        ; 512 tiles wide
CM_WORLD_H_LOG2      = 9                        ; 512 tiles tall
.assert (1 << CM_WORLD_W_LOG2) = WORLD_T_TILES, error, "col_map world width disagrees with world.inc WORLD_T_TILES"
.assert (1 << CM_WORLD_H_LOG2) = WORLD_T_TILES, error, "col_map world height disagrees with world.inc WORLD_T_TILES"
;
; The `::` on the allocator symbols is LOAD-BEARING, not decoration. ca65 2.18
; defers an UNQUALIFIED parent-scope lookup, so the resulting symbol is not a
; constant expression and col_map's assembly-time `.if CM_WORLD_BLOB_CHUNKS`
; fails with "Constant expression expected" — inside a `.scope`, only a
; `::`-qualified reference resolves eagerly. Measured on this ca65, not
; assumed.
CM_WORLD_BLOB        = ::ES_R_WORLD_MAP_T0_ADDR
CM_WORLD_BLOB_BANK   = ::ES_R_WORLD_MAP_T0_BANK
CM_WORLD_BLOB_CHUNKS = ::ES_R_WORLD_MAP_CHUNKS  ; DERIVED, not narrated
CM_FLAGS             = ::col_flags_bin          ; col_map_rom's table
.include "col_map.asm"

; vwf_map_row writes tilemap cells into bg_text's `text_map` claim — a region
; this scene picks and `vwf` neither claims nor depends on. That crossing is
; registered as a missing allocator mechanism (docs/09 §5.1, tilemap side);
; until it
; lands, bound the row's whole span at build time. VWF_STRIP_TILES comes from
; the include above, so this has to sit after it rather than beside VWF_ROW_CELL.
; NOTE what this does NOT catch: a row aimed at the HUD's row 2 is inside
; text_map and passes here. Nothing declares which cells bg_text itself uses,
; which is precisely the sub-range declaration docs/09 §5.1 registers as missing.
.assert VWF_ROW_CELL >= ES_V_TEXT_MAP, error, "VWF dialog row starts before bg_text's text_map claim"
.assert VWF_ROW_CELL + VWF_STRIP_TILES <= ES_V_TEXT_MAP + ES_V_TEXT_MAP_WORDS, error, "VWF dialog row overruns bg_text's text_map claim"

; --- enter: forced blank + NMI masked (scene_mgr contract) ------------------
enter:
    .a16
    .i16
    ; ---- entering a race costs a life; the HUD below renders
    ; the charged value. Floored at zero: title entry refills the run when
    ; lives hits 0, so this cannot underflow — the floor keeps a rules bug
    ; from turning into a 255-life wrap instead of a visible stuck-at-zero.
    sep #$20
    .a8
    lda f:US_LIVES_LONG
    beq :+
    dec
    sta f:US_LIVES_LONG
:   rep #$20
    .a16
    ; ---- race logic: the HUD below renders its lap counter ----------------
    jsr rl_arm
    ; ---- CGRAM: the 17-color floor palette (pinned at index 0) ------------
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
    ; ---- Mode 7: M7A-D are HDMA-owned (pose LUTs); origin via DP shadows --
    sep #$20
    .a8
    stz a:$211A                 ; M7SEL: wrap, no flips
    lda #7
    sta a:$2105                 ; BGMODE 7 (HDMA overrides per line)
    lda #1
    sta a:$212C                 ; TM: BG1 base (HDMA overrides per line)
    rep #$20
    .a16
    ; ---- HUD band: BG3 text over the floor --------------------------------
    ldx #ES_V_TEXT_CHR
    ldy #.loword(font_bin)
    lda #^font_bin
    jsr text_upload_font
    lda #RACE_TXT_ATTR
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    jsr text_clear_map
    lda #RACE_TXT_ATTR
    sta z:ES_TXT_TMP
    lda #.loword(s_hud)
    sta z:ES_TXT_PTR
    sep #$20
    .a8
    lda #^s_hud
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 2*32 + 2)     ; row 2, col 2
    jsr text_puts
    lda f:US_SCORE_LONG
    ldx #(ES_V_TEXT_MAP + 2*32 + 8)
    jsr text_put_hex4
    sep #$20
    .a8
    lda f:US_LIVES_LONG
    rep #$20
    .a16
    and #15
    ldx #(ES_V_TEXT_MAP + 2*32 + 19)
    jsr text_put_digit
    ; ---- HUD lap readout: static label + the live digit cell --------------
    lda #.loword(s_lap)
    sta z:ES_TXT_PTR            ; text_put_hex4 borrowed the ptr slot
    sep #$20
    .a8
    lda #^s_lap
    sta z:ES_TXT_PTR+2
    rep #$20
    .a16
    ldx #(ES_V_TEXT_MAP + 2*32 + 24)
    jsr text_puts
    sep #$20
    .a8
    lda f:US_LAP_LONG           ; rl_arm zeroed it above
    rep #$20
    .a16
    and #15
    ldx #RACE_LAP_CELL
    jsr text_put_digit
    ; ---- VWF dialog row (see VWF_ROW_CELL for why row 3). Cells point at the strip
    ; tiles once, here, under forced blank; from now on the row's CONTENT is
    ; CHR the vwfq claim commits in VBlank, and the tilemap never moves again.
    lda #RACE_TXT_ATTR
    ldx #VWF_ROW_CELL
    jsr vwf_map_row
    lda #.loword(s_vwf0)
    ldy #^s_vwf0
    jsr vwf_open
    ; ---- HUD BG3 regs + text palette (CGRAM words 28..31) -----------------
    sep #$20
    .a8
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                 ; BG3SC
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                 ; BG34NBA
    lda #ES_C_TEXT_PAL
    sta a:$2121
    lda #$00                    ; color 0: transparent slot
    sta a:$2122
    sta a:$2122
    lda #$84                    ; color 1: dark navy
    sta a:$2122
    lda #$10
    sta a:$2122
    lda #$B5                    ; color 2: mid gray
    sta a:$2122
    lda #$56
    sta a:$2122
    lda #$FF                    ; color 3: white
    sta a:$2122
    lda #$7F
    sta a:$2122
    ; ---- arm the split-band HDMA channels in the scene_mgr shadow ---------
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
    sep #$20
    .a8
    ; ---- perspective: index tables + channel shadow + heading 0 -----------
    rep #$20
    .a16
    jsr persp_arm
    lda #0
    jsr persp_set_pose
    ; heading user state starts in sync with the applied pose
    sep #$20
    .a8
    lda #0                      ; (stz has no abs-long form)
    sta f:US_HEADING_LONG
    sta f:US_HEADING_AP_LONG
    rep #$20
    .a16
    ; camera origin shadows (NMI hook commits them every armed frame)
    lda #CAM0_PX
    sta z:ES_M7ORG+0            ; M7X
    lda #CAM0_PY
    sta z:ES_M7ORG+2            ; M7Y
    lda #(CAM0_PX - 128)
    sta z:ES_M7ORG+4            ; HOFS
    lda #(CAM0_PY - PIVOT_LINE)
    sta z:ES_M7ORG+6            ; VOFS (pivot at the car line)
    ; ---- gradient: channel shadow + color-math config ---------------------
    jsr rg_arm
    ; ---- streaming: tile tracking synced to the seeded window -------------
    jsr stream_arm
    ; ---- sky: BG2 ramp CHR/map/palette + the BG2 register bases ----------
    jsr sky_arm
    ; ---- player car: CHR + OBJ palette + OBSEL + the OAM slot -------------
    jsr car_arm
    sep #$20
    .a8
    lda #((1 << ES_H_BGM_CH) | (1 << ES_H_TMI_CH) | (1 << ES_H_M7AB_CH) | (1 << ES_H_M7CD_CH))
    ora #((1 << ES_H_COLR_CH) | (1 << ES_H_COLG_CH) | (1 << ES_H_COLB_CH))
    sta z:ES_SM_NMI+2           ; HDMAEN shadow (NMI applies it)
    rep #$20
    .a16
    rts

exit:
    .a16
    .i16
    jsr rg_disarm               ; color math back to boot state (global regs)
    jsr car_disarm              ; re-park the claimed OAM slot
    rts


; --- cm_tick: query the tile under the live camera, once per frame ----------
; In/out: A16/I16, DB=0 (race tick contract). Called after rl_tick's integrate
; so ES_M7ORG is final for the frame, and before stream_tick, which reads the
; same origin — that ordering is already proven correct for stream_tick.
;
; This lives in the SCENE, not in engine/features/col_map, and the build is
; what drew the line: col_map.asm assembled into the cost probe fails on an
; undefined ES_M7ORG, because the camera origin is mode7_persp's claim. The
; feature answers questions about the world; choosing which coordinate to ask
; about is the game's business.
;
; READ-ONLY BY DESIGN. The flag lands in CM_FLAG and feeds nothing: no
; velocity clamp, no collision response, no branch in the physics. That is
; deliberate. `make measure` pins a rebuild cadence of 240 loop iterations /
; 240 hardware frames at vel $3000 with max turn; a speed penalty touching
; velocity could move a PINNED measurement.
; Feeding nothing keeps physics, laps, streaming and that pin provably
; untouched while still driving the query with the real coordinate stream the
; game produces — including the 4096-px wrap, which a synthetic walk can only
; imitate.
cm_tick:
    .a16
    .i16
    lda z:ES_M7ORG + 0          ; the camera's world pixel x (already wrapped
    sta z:CM_PX                 ;   to 0..4095 by rl_integrate)
    lda z:ES_M7ORG + 2
    sta z:CM_PY
    jsr col_map_at              ; leaves A8; CM_FLAG holds the result
    rep #$20                    ; WIDTH-RISK: col_map_at EXITS A8 — restore the
    .a16                        ;   A16 the race tick's next statement expects
    rts

tick:
    .a16
    .i16
    ; ---- steer, accelerate, integrate, count laps (race_logic) -----------
    ; The pose retarget a heading change implies happens in the NMI hook
    ; (VBlank — the spec); the tick only moves state.
    jsr rl_tick
    ; scroll shadows follow the origin (NMI hook commits all four)
    lda z:ES_M7ORG + 0
    sec
    sbc #128
    sta z:ES_M7ORG + 4          ; HOFS: screen center x
    lda z:ES_M7ORG + 2
    sec
    sbc #PIVOT_LINE
    sta z:ES_M7ORG + 6          ; VOFS: pivot at the car line
    jsr cm_tick
    jsr stream_tick
    jsr vwf_dialog_tick
    ; ---- race over? RACE_LAPS scored -> bank the score, fade to results ---
    ; sm_request moves the phase machine off 0, so sm_tick stops calling this
    ; tick entirely — the score can only be banked once.
    sep #$20
    .a8
    lda f:US_LAP_LONG
    cmp #RACE_LAPS
    bcc @running
    rep #$20
    .a16
    lda f:US_SCORE_LONG
    clc
    adc #(RACE_LAPS * RACE_LAP_SCORE)   ; laps x 100, laps fixed at the finish
    sta f:US_SCORE_LONG
    sep #$20
    .a8
    lda #2                      ; scene id: results
    jsr sm_request
@running:
    .a8
    .i16
    rep #$20
    .a16
    rts

; the heading -> forward-step table (generated; the tests' movement oracle)
.include "move_lut.inc"

; --- this scene's ROM blobs (allocator-claimed; order matches the map) ------
; --- vwf_dialog_tick: the game's reveal schedule ----------------------------
; Four messages on a 128-frame rotation. The first three are the extremes the
; rendered proportional-advance test measures — 'iiii' and 'mmmm' are equal in
; CHARACTER count and 8 px (one whole tile) apart in RENDERED width, which a
; fixed-width renderer cannot reproduce; '....' is the narrowest glyph in the
; face. The fourth is prose with punctuation, and fits the 112 px window (77 px).
; In/out: A16/I16, DB=0.
vwf_dialog_tick:
    .a16
    .i16
    lda a:ES_SM_FRAME
    and #VWF_SLOT_MASK
    bne @maybe_reveal
    ; slot boundary: open the next message
    lda a:ES_SM_FRAME
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr
    lsr                         ; frame / 128 = slot index
    and #3                      ; 4 messages
    asl                         ; x2 -> word index into the table
    tax
    lda f:vwf_msg_tab, x
    ldy #^s_vwf0                ; all four live in this scene's RODATA bank
    jmp vwf_open
@maybe_reveal:
    .a16
    .i16
    lda a:ES_SM_FRAME
    and #VWF_TICK_MASK
    bne @done
    jmp vwf_tick
@done:
    .a16
    .i16
    rts

.segment "RODATA"
s_hud:  .byte "SCORE ", 0
s_lap:  .byte "LAP", 0
; --- VWF messages. See vwf_dialog_tick for why these four. -----------------
s_vwf0: .byte "iiii", 0
s_vwf1: .byte "mmmm", 0
s_vwf2: .byte "....", 0
s_vwf3: .byte "End. Next: go", 0
vwf_msg_tab:
    .word .loword(s_vwf0), .loword(s_vwf1), .loword(s_vwf2), .loword(s_vwf3)
.segment "BANK13"
sky_map_bin:
    .incbin "sky_map.bin"
.assert ^sky_map_bin = ES_R_SKY_MAP_ROM_BANK, error, "sky_map bank drifted from allocator claim"
.assert .loword(sky_map_bin) = ES_R_SKY_MAP_ROM_ADDR, error, "sky_map addr drifted from allocator claim"
floor_tiles_bin:
    .incbin "floor_tiles.bin"
.assert ^floor_tiles_bin = ES_R_FLOOR_TILES_BANK, error, "floor_tiles bank drifted from allocator claim"
.assert .loword(floor_tiles_bin) = ES_R_FLOOR_TILES_ADDR, error, "floor_tiles addr drifted from allocator claim"
grad_tabs_bin:
    .incbin "gradient_tabs.bin"
.assert ^grad_tabs_bin = ES_R_GRAD_TABS_BANK, error, "grad_tabs bank drifted from allocator claim"
.assert .loword(grad_tabs_bin) = ES_R_GRAD_TABS_ADDR, error, "grad_tabs addr drifted from allocator claim"
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
