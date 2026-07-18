; =============================================================================
; mode_showcase — the PPU showcase HARNESS (S1): a discovery/authoring instrument
; =============================================================================
; Not a demo reel — an INSTRUMENT. A SNES PPU effect playground: discover effect
; combinations, tune them live with no recompile, record the finds. This ROM is
; the generic HARNESS the per-mode pages compose; S1 proves it end-to-end on
; Mode 1 (one mode fully wired with real knobs + its structural presets).
;
; Spec : docs/sprints/showcase_composition.md   (the instrument vision)
; Alloc: docs/sprints/showcase_allocations.md   (the binding $-map contract)
;
; THE FRAMEWORK (built once; every mode page reuses it):
;   - Shell      : menu -> instructions -> live demo, via sf_scene. Start=menu,
;                  Select=advance HUD slot.
;   - Param model: WRAM $7E:E200 (init under forced blank — RAM is garbage).
;                  6 slots x 5 params = up to 30 live knobs. TABLE-DRIVEN: a page
;                  supplies a 30-entry descriptor table (min/max/step/default) +
;                  an apply hook; the router is generic (see SHOW_* below).
;   - Router     : Select cycles the active slot; the 5 button-pairs
;                  </>  v/^  A/B  X/Y  L/R adjust the active slot's 5 params.
;   - HUD readout: OBJ pal 7 (CGRAM 240-255), composes sf_obj_text (brick B1):
;                  top strip = active slot label + 5 values; bottom strip = the
;                  6-slot bar, active slot lit.
;   - Param-sheet: Start+Select freezes the demo -> a B/W full-param dump (OBJ
;                  font, static forced-blank-style frame), paged with </> v/^.
;   - Record     : SRAM slots (sf_save) survive reset; a debug-region mirror at
;                  $7E:E300 lets the harness be read out programmatically.
;   - Limits     : a green/yellow/red meter (heartbeat / HDMA ch / OAM-per-line)
;                  + the $C000 arena mutex (a 2nd heavy effect auto-disables #1).
;
; DISPATCH / REGISTRATION INTERFACE (S1.5 — the fan-out contract). The menu
; selects a mode (SHOW_CUR_MODE); the demo enters that mode's page through the
; per-mode vtables (showcase_dispatch.inc). A page registers its row ONCE with
; UNIQUE (mode-prefixed) symbols — it never edits the tables, the Makefile, or
; this file:
;   show_register_mode N, init, apply, field, arena, ptbl, snames, pnames, costknob
;     init/apply/field/arena : .proc, A16/I16 in/out (the 4 generic-called procs)
;     ptbl   : 30 x 4 bytes (min,max,step,default), slot-major [slot*5+param]
;     snames : 6 .addr slot-label string ptrs (<=6 glyphs)
;     pnames : 30 .addr param-tag string ptrs (<=3 glyphs)
;     costknob : the meter cost/OAM proxy knob index (byte)
; show_dispatch_emit_tables (below the includes) builds the vtables from every
; registration. The router, HUD, param-sheet, record, and limit meter are all
; generic over the ACTIVE mode's resolved tables (SHOW_A_*, copied on demo entry).
; Full contract: docs/sprints/showcase_page_authoring.md.
;
; LINK SHAPE (S1.5, all-modes dispatch): lorom_show.cfg (256KB + SRAM) — a
; GENEROUS LoROM+SRAM cfg so the S2..Sn fan-out (8 real pages + the Mode-7 engine
; + its PV LUTs + per-mode CHR/LUT data) never has to resize the linker cfg.
; CODE/RODATA live in bank 0 (~17KB of 32KB at S1.5); BANK1..BANK7 are spare data
; banks for the fan-out. Links the all-modes BG dispatcher (bg_mode_engine;
; Mode-7 falls to its BGMODE-only stub until a Mode-7 page .includes mode7_engine)
; + the full sf_fx engine set + sf_window + sf_obj_text + the S1.5 dispatch layer.
; ; LDCFG: lorom_show.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"            ; sf_coldstart, sf_debug_magic
.include "sf_video.inc"
.include "sf_sprite.inc"          ; spr / spr_clear
.include "sf_input.inc"           ; btn / btnp / BTN_*
.include "sf_frame.inc"           ; sf_engine_init / sf_frame_begin / sf_frame_end
.include "sf_scene.inc"           ; scene state machine + dispatch
.include "sf_save.inc"            ; SRAM slots (record)
.include "sf_fx.inc"              ; color-math / mosaic / gradient / bright knobs
.include "sf_window.inc"          ; spotlight preset
.include "engine_state.inc"       ; address SSoT

; =============================================================================
; PARAM MODEL — WRAM $7E:E200-$E2FF (allocations contract §1). Long-addressed.
; =============================================================================
SHOW_BASE         = $7EE200
SHOW_KNOB_VAL     = $7EE200       ; 30 B: [slot*5 + param] current value
SHOW_KNOB_AUX     = $7EE21E       ; 30 B: per-knob aux byte (reserved)
SHOW_ACTIVE_SLOT  = $7EE23C       ; 1 B : lit slot 0..5
SHOW_CUR_MODE     = $7EE23D       ; 1 B : active BG mode 0..7
SHOW_FLAGS        = $7EE23E       ; 2 B : harness flags (see SHOW_FL_* below)
SHOW_SPR_FIELD    = $7EE240       ; 192 B: 32 sprites x 6 B (field model)
; Debug-export mirror + harness telemetry — verified-free $7E:E300 tail
; (allocations §1: "extend into $7E:E300-$EFFF and record the claim here").
SHOW_DBG_MIRROR   = $7EE300       ; 32 B: live param block mirror (M6 export)
SHOW_PRESET       = $7EE320       ; 1 B : active structural preset 0..2
SHOW_SHEET_PAGE   = $7EE321       ; 1 B : param-sheet current page
SHOW_METER_CYC    = $7EE322       ; 1 B : limit meter — cycle/heartbeat level
SHOW_METER_HDMA   = $7EE323       ; 1 B : limit meter — HDMA channel level
SHOW_METER_OAM    = $7EE324       ; 1 B : limit meter — OAM-per-line level
SHOW_ARENA_OWNER  = $7EE325       ; 1 B : $C000 arena mutex current owner (0=none)
SHOW_LAST_HEART   = $7EE326       ; 2 B : last frame-counter snapshot (heartbeat)
SHOW_SHEET_TMP    = $7EE328       ; 2 B : param-sheet scratch (long-addressed)
SHOW_MOS_TMP      = $7EE32A       ; 1 B : mosaic-byte assembly scratch (long)
SHOW_FLD_FLAGS    = $7EE32B       ; 1 B : field OBJ attr (pal<<1)
SHOW_FLD_TMP      = $7EE32C       ; 2 B : field math scratch
SHOW_FLD_TMP2     = $7EE32E       ; 1 B : field math scratch (multiplier)
SHOW_FLD_TMP3     = $7EE32F       ; 2 B : field math scratch (accumulator)
; HUD / sheet render scratch (long-addressed, $7E:E33x)
SHOW_STR_LO       = $7EE331       ; 2 B : string lo16 (for show_print_at)
SHOW_STR_BANK     = $7EE333       ; 1 B : string bank byte
SHOW_PEN_X        = $7EE334       ; 1 B : print pen X
SHOW_PEN_Y        = $7EE335       ; 1 B : print pen Y
SHOW_HUD_TMP      = $7EE336       ; 2 B : HUD math scratch
SHOW_HUD_TMP2     = $7EE338       ; 2 B : HUD math scratch
SHOW_HUD_KNOB     = $7EE33A       ; 1 B : HUD current knob index
SHOW_HUD_P        = $7EE33B       ; 1 B : HUD/sheet loop counter
; knob clamp scratch (cached table min/max/step — long indexing is X-only)
SHOW_KMIN         = $7EE33C       ; 1 B
SHOW_KMAX         = $7EE33D       ; 1 B
SHOW_KSTEP        = $7EE33E       ; 1 B
; show_num3 scratch (compact 3-digit HUD value renderer)
SHOW_NUM_X        = $7EE33F       ; 1 B : pen X
SHOW_NUM_Y        = $7EE340       ; 1 B : pen Y
SHOW_NUM_V        = $7EE341       ; 1 B : remaining value
SHOW_NUM_DV       = $7EE342       ; 1 B : current place value (100/10/1)
; harness control bytes (read-before-write -> seeded in show_param_init, F8)
SHOW_TM_SNAP      = $7EE343       ; 1 B : SHADOW_TM snapshot for the param-sheet
SHOW_OAM_OVF      = $7EE344       ; 1 B : HUD OAM-budget overflow flag (>48 guard)
SHOW_SAVE_SLOT_SEL= $7EE345       ; 1 B : active SRAM save slot 0..3 (record screen)
SHOW_OAM_USED     = $7EE346       ; 1 B : realized SPRITE_COUNT (meter O signal)

; SHOW_FLAGS bit assignments
SHOW_FL_SHEET     = $0001         ; param-sheet (freeze) active

; Slot / param geometry
SHOW_N_SLOTS      = 6
SHOW_N_PARAMS     = 5

; Scene ids (dense from 0 — sf_scene contract)
SC_MENU   = 0
SC_INSTR  = 1
SC_DEMO   = 2

SCENE     = $1804                 ; scene-state word (sf_scene-owned WRAM)

.segment "CODE"

NMI:
.include "nmi_handler.asm"
NMI_STUB:
    rti

; =============================================================================
; The dispatcher + bricks linked into the ROM. Included BEFORE the RESET/scene
; code so their MACROS (sf_obj_print/num/init) are defined before use — ca65
; resolves jsr labels by link, but macros must be defined first.
; =============================================================================
    .include "bg_mode_engine.asm" ; all-modes engine_gfxmode (Mode-7 -> stub)

.include "sf_obj_text_data.inc"   ; glyph CHR + ascii->glyph (include ONCE)
.include "sf_obj_text.inc"        ; sf_obj_print / sf_obj_num (HUD readout)

; --- harness logic modules (templates/mode_showcase/assets is on -I) ---
; DISPATCH FIRST: it defines the show_register_mode macro + the SHOW_A_* active-
; table bases + the generic dispatch entry points (show_demo_init / show_apply /
; show_field_tick / show_arena_indicator) the shell calls. Per-mode pages then
; register themselves; show_dispatch_emit_tables (below the pages) emits the
; vtables from those registrations.
.include "showcase_dispatch.inc"  ; S1.5 all-modes dispatch layer (vtables + macro)
.include "showcase_param.inc"     ; param model: init + clamp router (M2)
.include "showcase_hud.inc"       ; OBJ-HUD readout (M3)
.include "showcase_mode1.inc"     ; Mode-1 knobs + presets + apply (M4)
.include "showcase_scene1.inc"    ; Mode-1 BG content + sprite field (M4) + register
.include "showcase_mode0.inc"     ; Mode-0 PLANES knobs + presets + apply (fan-out)
.include "showcase_scene0.inc"    ; Mode-0 4-layer BG content + field (+ register)
.include "showcase_stub.inc"      ; generic stub page + registers modes 2-7
.include "showcase_sheet.inc"     ; param-sheet freeze (M5)
.include "showcase_record.inc"    ; SRAM save/recall + debug export (M6)
.include "showcase_meter.inc"     ; limit meter + arena mutex (M7)

; --- emit the per-mode vtables from every registration above (deliverable 1) ---
show_dispatch_emit_tables

RESET:
    sf_coldstart
    sf_engine_init
    jsr init_ppu                  ; engine PPU bring-up (Mode 1, OBJ; turns screen on)

    ; --- FORCED BLANK for the VRAM/CGRAM uploads. init_ppu ends with the screen
    ;     ON ($2100=$0F); VRAM/CGRAM writes need forced blank or VBlank, so blank
    ;     here, upload, then restore screen-on before the frame loop. ---
    sep #$20
    .a8
    lda #$80
    sta $2100                     ; forced blank
    ; OBSEL: OBJ name base VRAM word $4000 + 8x8 small (per-page VRAM rule,
    ; allocations §3). $02 = size %000 (8x8) + name base %010 (word $4000).
    lda #$02
    sta $2101
    rep #$20
    .a16

    ; --- HUD glyph CHR -> OBJ VRAM word $4000 + OBJ pal 7 -> CGRAM 240-255. ---
    sf_obj_text_init              ; default base tile 1024 = word $4000

    ; --- Limit-meter colours -> OBJ pals 4/5/6 (green/yellow/red). ---
    jsr show_meter_init

    ; --- Seed the selected mode to 0 at boot (RAM is garbage). show_param_init
    ;     PRESERVES SHOW_CUR_MODE, so set the boot default BEFORE it runs; the
    ;     menu cursor then owns it from here (dispatch SSoT). ---
    sep #$20
    .a8
    lda #0
    sta f:SHOW_CUR_MODE
    rep #$20
    .a16

    ; --- F-3 power-on: resolve the boot mode's tables into the SHOW_A_* staging
    ;     window BEFORE show_param_init reads SHOW_A_PARAM_TBL for its knob seed.
    ;     show_resolve_active_tables only runs on demo entry; at RESET the staging
    ;     window ($7E:E380-$E440) is still power-on garbage, so seeding the knob
    ;     defaults from it would be an uninitialized-RAM read (CLAUDE.md rule 5).
    ;     SHOW_CUR_MODE is already 0 (set above), so this resolves mode 0's table;
    ;     demo entry re-runs resolve+param_init for the menu-selected mode later. ---
    jsr show_resolve_active_tables

    ; --- Init the param model (RAM is garbage at boot). ---
    jsr show_param_init

    ; --- Restore screen on (full brightness); the NMI keeps SHADOW_INIDISP. ---
    sep #$20
    .a8
    lda #$0F
    sta $2100
    sta SHADOW_INIDISP
    rep #$20
    .a16

    sf_debug_magic                ; "SFDB" @ $7E:E000 — boot reached

    ; --- Enable NMI + auto-joypad, then land on the menu ---
    sep #$20
    .a8
    lda #$81
    sta $4200
    rep #$20
    .a16

    sf_scene_goto SC_MENU

game_loop:
    sf_frame_begin
    ; Global Start/Select handling lives in each scene's tick (context-sensitive).
    sf_scene_dispatch
    sf_frame_end
    jmp game_loop

; =============================================================================
; SCENES — menu / instructions / live demo.
; =============================================================================

; --- SC_MENU: vertical list MODE 0..7 + tagline; a cursor selects a mode; A sets
;     SHOW_CUR_MODE to the highlighted mode and advances to SC_INSTR (deliverable
;     4). Up/Down move the cursor in the left column (0-3), Left/Right jump the
;     cursor between the two columns (left 0-3, right 4-7). The highlighted slot
;     renders a '>' caret so the OUTPUT shows the selection. ----------------------
; Strings kept SHORT so the whole menu stays well under the 128-OAM / 32-per-line
; budget (an OBJ-font menu is sprite-priced; the per-mode taglines live on each
; page's instructions, not here). Two columns of mode labels keep it compact.
str_title:    .byte "PPU SHOWCASE", 0
str_tagline:  .byte "TUNE LIVE INSTRUMENT", 0
str_m0:  .byte "0 PLANES", 0
str_m1:  .byte "1 GLASS", 0
str_m2:  .byte "2 WARP", 0
str_m3:  .byte "3 256COL", 0
str_m4:  .byte "4 WGRAD", 0
str_m5:  .byte "5 HIRES", 0
str_m6:  .byte "6 INTER", 0
str_m7:  .byte "7 AFFINE", 0
str_press:    .byte "PRESS A", 0

; per-mode menu label pointer table (0..7) for the caret-position lookup
menu_label_tbl:
    .addr str_m0, str_m1, str_m2, str_m3, str_m4, str_m5, str_m6, str_m7
; per-mode menu (x,y) positions: left column 0-3 at x=40, right 4-7 at x=144;
; rows at y=56,72,88,104. Stored as parallel byte tables (x then y), mode-indexed.
menu_x_tbl: .byte 40, 40, 40, 40, 144, 144, 144, 144
menu_y_tbl: .byte 56, 72, 88, 104, 56, 72, 88, 104

scene_menu:
    ; seed the cursor to the previously-selected mode (or 0 at boot) so the menu
    ; opens on a valid highlight. SHOW_CUR_MODE is the SSoT for the cursor.
    rts

menu_tick:
    spr_clear
    sf_obj_print str_title,   #56, #8
    sf_obj_print str_tagline, #40, #24
    ; left column (modes 0-3) at x=40, right column (4-7) at x=144
    sf_obj_print str_m0, #40, #56
    sf_obj_print str_m1, #40, #72
    sf_obj_print str_m2, #40, #88
    sf_obj_print str_m3, #40, #104
    sf_obj_print str_m4, #144, #56
    sf_obj_print str_m5, #144, #72
    sf_obj_print str_m6, #144, #88
    sf_obj_print str_m7, #144, #104
    sf_obj_print str_press, #88, #136

    ; --- cursor movement (btnp edges). SHOW_CUR_MODE 0..7 is the highlight. ---
    jsr menu_cursor_move
    ; --- render the caret at the highlighted mode's (x-8, y) ---
    jsr menu_draw_caret

    btnp #BTN_A
    beq @done
    ; A: commit the highlighted mode (already in SHOW_CUR_MODE) -> instructions
    sf_scene_goto SC_INSTR
    rts
@done:
    rts

; --- menu_cursor_move: Up/Down step the mode within a column; Left/Right swap
;     columns. Clamped to 0..7. SHOW_CUR_MODE holds the highlight. -------------
; WIDTH-RISK: A16/I16 entry; A8 for the byte RMW; exits A16/I16.
.proc menu_cursor_move
    rep #$30
    .a16
    .i16
    btnp #BTN_DOWN
    bne @down
    btnp #BTN_UP
    bne @up
    btnp #BTN_RIGHT
    bne @right
    btnp #BTN_LEFT
    bne @left
    rts
@down:
    ; +1 within the column (rows 0-3 / 4-7); wrap inside the column of 4
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    tay                              ; Y unused; keep A
    inc a
    and #$03                         ; wrap within the 0..3 row offset
    sta f:SHOW_HUD_TMP              ; new row offset
    lda f:SHOW_CUR_MODE
    and #$04                         ; column base (0 or 4)
    ora f:SHOW_HUD_TMP
    sta f:SHOW_CUR_MODE
    rep #$20
    .a16
    rts
@up:
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$03
    dec a
    and #$03
    sta f:SHOW_HUD_TMP
    lda f:SHOW_CUR_MODE
    and #$04
    ora f:SHOW_HUD_TMP
    sta f:SHOW_CUR_MODE
    rep #$20
    .a16
    rts
@right:
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    ora #$04                          ; jump to the right column (4-7)
    and #$07
    sta f:SHOW_CUR_MODE
    rep #$20
    .a16
    rts
@left:
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$03                          ; jump to the left column (0-3)
    sta f:SHOW_CUR_MODE
    rep #$20
    .a16
    rts
.endproc

; --- menu_draw_caret: render a solid BAR-glyph cursor just left of the
;     highlighted mode's label, at (menu_x_tbl[m]-10, menu_y_tbl[m]). The BAR
;     glyph (SF_OBJG_BAR) is a real font tile (unlike '>', absent from the font),
;     so the selection is unambiguous in the rendered OUTPUT. Placed via a direct
;     sprite in call order from SPRITE_COUNT (after the menu text glyphs).
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr A16/I16; exits A16/I16.
.proc menu_draw_caret
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    rep #$20
    .a16
    and #$00FF
    tax                              ; X = mode
    ; sprite X = menu_x_tbl[m] - 10 (just left of the label), Y = menu_y_tbl[m]
    sep #$20
    .a8
    lda f:menu_x_tbl, x
    sec
    sbc #10
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_X
    sep #$20
    .a8
    lda f:menu_y_tbl, x
    rep #$20
    .a16
    and #$00FF
    sta SF_SPR_Y
    lda #SF_OBJG_BAR                  ; solid bar glyph = the cursor
    sta SF_SPR_TILE
    lda #SF_OBJ_HUD_FLAGS             ; HUD pal 7 (white)
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    rts
.endproc

; --- SC_INSTR: per-mode control legend; A enters the SELECTED mode's demo. The
;     header reflects SHOW_CUR_MODE ("MODE n NAME"); the legend is generic (the
;     instrument's controls are the same across modes). Deliverable 5. ----------
str_i_t:  .byte "MODE", 0
str_i_1:  .byte "SELECT NEXT SLOT", 0
str_i_2:  .byte "DPAD AB XY LR TUNE", 0
str_i_3:  .byte "START MENU", 0
str_i_4:  .byte "START+SEL SHEET", 0
str_i_5:  .byte "SHEET A SAVE B LOAD", 0
str_i_6:  .byte "PRESS A DEMO", 0

; per-mode short name (echoes the menu labels' descriptor; <=8 glyphs)
str_in0: .byte "PLANES", 0
str_in1: .byte "GLASS", 0
str_in2: .byte "WARP", 0
str_in3: .byte "256COL", 0
str_in4: .byte "WGRAD", 0
str_in5: .byte "HIRES", 0
str_in6: .byte "INTER", 0
str_in7: .byte "AFFINE", 0
instr_name_tbl:
    .addr str_in0, str_in1, str_in2, str_in3, str_in4, str_in5, str_in6, str_in7

scene_instr:
    rts

instr_tick:
    spr_clear
    sf_obj_print str_i_t, #48, #16
    ; mode number after "MODE " + the mode name (reflects SHOW_CUR_MODE)
    jsr instr_draw_header
    sf_obj_print str_i_1, #24, #48
    sf_obj_print str_i_2, #24, #62
    sf_obj_print str_i_3, #24, #76
    sf_obj_print str_i_4, #24, #90
    sf_obj_print str_i_5, #24, #104
    sf_obj_print str_i_6, #24, #136
    btnp #BTN_START
    beq @chk_a
    sf_scene_goto SC_MENU
    rts
@chk_a:
    btnp #BTN_A
    beq @done
    sf_scene_goto SC_DEMO
    rts
@done:
    rts

; --- instr_draw_header: "<n> <NAME>" after the "MODE" label, reflecting the
;     selected mode. Draws the digit then the mode-name string. ----------------
; WIDTH-RISK: A16/I16 entry; A8 for byte math; exits A16/I16.
.proc instr_draw_header
    rep #$30
    .a16
    .i16
    ; mode digit at x=96, y=16
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    rep #$20
    .a16
    and #$00FF
    sta SF_OBJT_TMP
    sep #$20
    .a8
    lda #96
    sta SF_OBJT_X
    stz SF_OBJT_X+1
    lda #16
    sta SF_OBJT_Y
    stz SF_OBJT_Y+1
    lda #SF_OBJ_HUD_FLAGS
    sta SF_OBJT_FLAGS
    stz SF_OBJT_FLAGS+1
    rep #$20
    .a16
    jsr _sf_obj_num_run
    ; mode NAME at x=120, y=16
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    rep #$20
    .a16
    and #$00FF
    asl                              ; *2 (.addr)
    tax
    lda f:instr_name_tbl, x
    sta f:SHOW_STR_LO
    sep #$20
    .a8
    lda #^instr_name_tbl
    sta f:SHOW_STR_BANK
    lda #120
    sta f:SHOW_PEN_X
    lda #16
    sta f:SHOW_PEN_Y
    rep #$20
    .a16
    jsr show_print_at
    rts
.endproc

; --- SC_DEMO: the SELECTED mode's live demo (DISPATCH). show_demo_init (the
;     dispatch wrapper, showcase_dispatch.inc) resolves the active mode's tables
;     and calls SHOW_DEMO_INIT[SHOW_CUR_MODE] under forced blank; then the knob
;     router + the dispatched apply/field/arena run every frame. ----------------
scene_demo:
    jsr show_demo_init            ; dispatch: resolve tables + SHOW_DEMO_INIT[mode]
    rts

demo_tick:
    ; Start+Select -> toggle the param sheet (freeze). Start alone -> menu.
    btnp #BTN_START
    beq @run
    btn #BTN_SELECT
    beq @to_menu
    jsr show_sheet_toggle         ; Start+Select: enter/leave param sheet
    rts
@to_menu:
    sf_scene_goto SC_MENU
    rts
@run:
    ; If the param sheet is frozen, just service its paging + render.
    lda f:SHOW_FLAGS
    and #SHOW_FL_SHEET
    beq @live
    jsr show_sheet_tick
    rts
@live:
    btnp #BTN_SELECT
    beq @no_sel
    jsr show_slot_advance         ; Select cycles the active slot
@no_sel:
    jsr show_knob_router          ; the 5 button-pairs adjust active slot params
    spr_clear                     ; start the OAM frame (HUD takes slots 0..)
    jsr show_apply                ; push knobs to PPU shadows (+ arena mutex)
    jsr show_hud_render           ; OBJ-HUD readout: top (0-35) + bottom bar (40-45)
    jsr show_meter_tick           ; limit meter — 3 distinct bars (OBJ 36-38)
    jsr show_arena_indicator      ; $C000 arena-owner glyph (OBJ 39) — mutex F5
    jsr show_hud_budget_guard     ; enforce HUD OAM <=48 before the field (F4)
    jsr show_field_tick           ; sprite field at OAM 48.. (allocations §2 band)
    jsr show_dbg_export           ; mirror live params to $7E:E300
    rts

; --- the scene table (sf_scene_end emits the tick jump table) ---
sf_scene_begin SCENE
sf_scene SC_MENU,  scene_menu,  menu_tick
sf_scene SC_INSTR, scene_instr, instr_tick
sf_scene SC_DEMO,  scene_demo,  demo_tick
sf_scene_end

; =============================================================================
; Engine link partners (order per sf_fx.inc: hdma_alloc -> hdma_engine ->
; hdma_color_engine; the rest order-independent).
; =============================================================================
.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "bg_engine.asm"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
.include "bright_fade_engine.asm"
.include "palette_engine.asm"
.include "save_load_engine.asm"
