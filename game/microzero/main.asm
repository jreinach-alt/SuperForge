; =============================================================================
; microzero — the tiny complete game. ROM skeleton.
; =============================================================================
; Every RAM/VRAM/CGRAM address and channel comes from the allocator's emitted
; includes; hardware I/O ports are the only literals (no_literals-gated).
; Scene code lives in .scope <scene_id> blocks so same-named claims in
; different scenes stay distinct symbols (see engine_state_<scene>.inc).
.p816
.smart

.define SF_HDR_TITLE "MICROZERO"
SF_HDR_TITLE_SET = 1
; $FFD7 (ROM size) is DERIVED: vendor/rom/header.inc imports
; SF_LD_ROM_SIZE from the linker config, which is the only file that
; knows how big the image is. It used to be declared here, in 17 rails,
; beside 20 that inherited a 32 KB default and shipped 524,288 B.
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "world.inc"                ; world geometry constants (not addresses)
JOY_START = 4096                    ; $4218 bit 12 (decimal: not an address)
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine feature runtimes (shared code, global symbols only) -------------
.include "scene_mgr.asm"
.include "input.asm"
.include "fade.asm"
.include "bg_text.asm"
.include "mode7_floor.asm"
; split_band's binding contract (the five symbols it carries no default for —
; see its header). These are the values that were folded into its tables until
; the split_h_demo port needed a second binding; the bytes are unchanged, so
; microzero's image is byte-identical across the generalisation.
SB_LINES    = HUD_LINES         ; the seam: Mode-1 HUD rows 0..43
SB_MODE_TOP = $09               ; Mode 1, BG3 priority high
SB_MODE_BOT = $07               ; Mode 7 (the floor)
SB_TM_TOP   = $16               ; BG2 (sky_band's ramp) + BG3 (HUD) + OBJ
SB_TM_BOT   = $11               ; BG1 (the Mode 7 floor) + OBJ (the car)
.include "split_band.asm"
.include "oam_sprites.asm"
.include "region.asm"               ; $213F bit 4 -> ES_RGN_PAL, once at boot
.include "tick_scale.asm"           ; TS_STEP: the macro race_logic's publisher
                                    ; and the results tally both expand.
                                    ; INCLUDED BEFORE THE SCENES, and it must
                                    ; be -- a ca65 macro has to be defined
                                    ; before the line that expands it.

; --- text_dp boot init (the text engine's global DP block) ------------------
text_dp_init:
    .a16
    .i16
    stz z:ES_TXT_PTR            ; bytes 0-1
    stz z:ES_TXT_TMP
    sep #$20
    .a8
    stz z:ES_TXT_PTR+2          ; bank byte alone — the claim is 3 B, and a
                                ; 16-bit store would stomp the neighbor claim
    rep #$20
    .a16
    stz z:ES_TXT_Q + 0          ; VBlank cell queue: dirty flag + spare byte
    stz z:ES_TXT_Q + 2          ; ...staged VMADD
    stz z:ES_TXT_Q + 4          ; ...staged tile word
    rts

; --- global ROM blobs (allocator-claimed; .incbin order inside a segment ----
; must match the allocator's packing order — the .asserts refuse drift) ------
;
; The `.repeat` counts are DERIVED (ES_R_<NAME>_CHUNKS, emitted beside the
; per-chunk symbols) — a hand-written count is a build refusal. `.repeat 8` ->
; `.repeat 7` here once left the backing gate, ca65 and ld65 all green and
; 18,478 bytes of world map as $FF fill (docs/37 §5 limit 1).
.repeat ES_R_POSES_AB_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 9)
.ident(.sprintf("poses_ab_t%d", PI)):
    .incbin "poses_ab.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_ab_t%d", PI)) = .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", PI)), error, "poses_ab chunk bank drifted"
.endrepeat
.repeat ES_R_POSES_CD_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 11)
.ident(.sprintf("poses_cd_t%d", PI)):
    .incbin "poses_cd.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_cd_t%d", PI)) = .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", PI)), error, "poses_cd chunk bank drifted"
.endrepeat
.segment "BANK13"
font_bin:
    .incbin "font_2bpp.bin"
.assert ^font_bin = ES_R_FONT_BIN_BANK, error, "font_bin bank drifted from allocator claim"
.assert .loword(font_bin) = ES_R_FONT_BIN_ADDR, error, "font_bin addr drifted from allocator claim"
car_chr_bin:
    .incbin "car_chr.bin"
.assert ^car_chr_bin = ES_R_CAR_CHR_ROM_BANK, error, "car_chr bank drifted from allocator claim"
.assert .loword(car_chr_bin) = ES_R_CAR_CHR_ROM_ADDR, error, "car_chr addr drifted from allocator claim"
vwf_glyphs_bin:
    .incbin "vwf_glyphs.bin"
.assert ^vwf_glyphs_bin = ES_R_VWF_GLYPHS_BANK, error, "vwf_glyphs bank drifted from allocator claim"
.assert .loword(vwf_glyphs_bin) = ES_R_VWF_GLYPHS_ADDR, error, "vwf_glyphs addr drifted from allocator claim"
col_flags_bin:
    .incbin "col_flags.bin"
.assert ^col_flags_bin = ES_R_COL_FLAGS_BANK, error, "col_flags bank drifted from allocator claim"
.assert .loword(col_flags_bin) = ES_R_COL_FLAGS_ADDR, error, "col_flags addr drifted from allocator claim"
vwf_widths_bin:
    .incbin "vwf_widths.bin"
.assert ^vwf_widths_bin = ES_R_VWF_WIDTHS_BANK, error, "vwf_widths bank drifted from allocator claim"
.assert .loword(vwf_widths_bin) = ES_R_VWF_WIDTHS_ADDR, error, "vwf_widths addr drifted from allocator claim"
car_pal_bin:
    .incbin "car_pal.bin"
.assert ^car_pal_bin = ES_R_CAR_PAL_ROM_BANK, error, "car_pal bank drifted from allocator claim"
.assert .loword(car_pal_bin) = ES_R_CAR_PAL_ROM_ADDR, error, "car_pal addr drifted from allocator claim"

; world map: 8 bank-tiled chunks, 64 rows x 512 B each
.repeat ES_R_WORLD_MAP_CHUNKS, WI
.segment .sprintf("BANK%d", WI + 1)
.ident(.sprintf("world_map_t%d", WI)):
    .incbin "world_map.bin", WI * 32768, 32768
.assert ^.ident(.sprintf("world_map_t%d", WI)) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)), error, "world chunk bank drifted"
.assert .loword(.ident(.sprintf("world_map_t%d", WI))) = .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)), error, "world chunk addr drifted"
; The allocator first-fits chunks into a growable list of window free lists
; (allocate.py::place_rom), so CONSECUTIVE banks are an outcome, not a
; guarantee. Three call sites already depend on it — mode7_stream's MVN stub
; table (M7S_BLOB_BANK + i), stream_stage_col's span bank, mode7_floor's seed
; upload — and each spells it `T0_BANK + index`. State it once, here, where
; the per-chunk symbols legitimately live: this is the only file that can name
; them all (a `%s` template is refused everywhere by no_literals' blanket-rom
; -template pass, so a feature file cannot).
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_BANK", WI)) = ES_R_WORLD_MAP_T0_BANK + WI, error, "world chunk banks are not consecutive — the T0_BANK + index addressing in mode7_stream/mode7_floor would read the wrong bank"
; The banks being consecutive is half of it. M7S_WORLD_WIN / CM_WORLD_BLOB is
; ONE window base used for every chunk, so the chunks must also sit at the
; SAME in-window offset. That is automatic while every chunk is a full 32 KB
; window, and stops being automatic the moment a blob is ragged — a short
; tail chunk first-fits into whatever partial window it finds. Both halves of
; the obligation are named in mode7_stream.asm's and col_map.asm's BINDING
; CONTRACT blocks; this is where they are discharged for this rail.
.assert .ident(.sprintf("ES_R_WORLD_MAP_T%d_ADDR", WI)) = ES_R_WORLD_MAP_T0_ADDR, error, "world chunks are not window-aligned alike — M7S_WORLD_WIN/CM_WORLD_BLOB is one base for all of them"
.endrepeat
.segment "CODE"

; --- scenes (before the dispatch tables: ca65 scopes resolve backward) ------
.include "scenes/title.asm"
.include "scenes/race.asm"
.include "scenes/results.asm"

; --- sm_nmi_hook: per-frame VBlank work (after scenes: scope refs resolve) --
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; every scene: commit the OAM shadow
    lda z:ES_SM_CTL             ; current scene
    cmp #1                      ; race?
    bne :+
    jsr race::persp_commit_origin
    jsr race::stream_nmi_dispatch
    jsr race::vwf_nmi_commit
    ; pose retarget in VBlank (the spec): desired -> applied, index tables +
    ; DASB shadows re-stamped BEFORE the core's shadow MVN applies them
    lda f:race::US_HEADING_LONG
    cmp f:race::US_HEADING_AP_LONG
    beq :+
    sta f:race::US_HEADING_AP_LONG
    rep #$20
    .a16
    and #63                     ; A8 load left the high byte stale — mask it
    jsr race::persp_set_pose
    sep #$20
    .a8
    ; It is last, and its POSITION IS FREE — the two are not connected. Setting
    ; your own VMAIN/VMADD is exactly what stops the DMAs ahead of you from
    ; reaching you. MEASURED: moved to run FIRST here, ahead of every stream and
    ; VWF DMA, all 20 hud-lap / vwf / stream tests stay green. Every VBlank VRAM
    ; writer in this hook programs both registers itself (bg_text.asm,
    ; mode7_stream.asm's rows + cols, vwf.asm's commit), so hook order is free
    ; for all of them. A FUTURE consumer that does NOT program its own must be
    ; ordered last — that is the rule, and today it has no instance.
:   .a8                         ; every path in (both beq/bne + fall-through)
    .i16
    jsr text_vblank_commit
    rts

; --- scene dispatch tables (manifest order: title=0, race=1, results=2) -----
sm_enter_tab:   .word title::enter, race::enter, results::enter
sm_tick_tab:    .word title::tick,  race::tick,  results::tick
sm_exit_tab:    .word title::exit,  race::exit,  results::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr region_init             ; the console's own region line, once. It is
                                ;   game-lifetime state: a console does not
                                ;   change region between scenes.
    jsr text_dp_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- game-lifetime user state (game logic owns these values) ----------
    lda #0
    sta f:US_SCORE_LONG
    sep #$20
    .a8
    lda #LIVES_START
    sta f:US_LIVES_LONG
    rep #$20
    .a16
    ; ---- enter the boot scene (id 0 = title) under forced blank -----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad, fade in from black -----------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    jsr input_read
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
