; =============================================================================
; sf_scene_mode.inc — the forced-blank bracket for a BG-MODE switch (macro lib)
; =============================================================================
; THE net-new primitive the RPG arc's scene-transition layer is built on. A
; Mode 7 <-> Mode 1 switch is a *discontinuous* reconfiguration: the PPU's
; whole VRAM layout, BGMODE, HDMA matrix channels, and palettes are swapped
; wholesale. None of that can be visible mid-rebuild or the swap frame tears
; (half Mode 7 floor, half garbage). The fix is the classic SNES bracket:
; raise FORCED BLANK around the rebuild so the screen shows nothing while the
; uploads land, then drop it once the new mode is fully programmed.
;
; WHY THIS IS NEW (no existing kit macro raises a standalone blank):
;   - sf_coldstart raises blank ONCE at boot and never lowers it itself.
;   - sf_bright_fade DELIBERATELY preserves INIDISP bit 7 (it animates the
;     brightness nibble 0-15 only — bright_fade_engine.asm) so it can never be
;     used to mask a mode switch: a fade-to-0 still leaves the screen ON
;     (black, but ON), and the PPU's VRAM port is only write-stable under
;     bit 7 = forced blank. A long CPU VRAM upload during a fade would corrupt.
; So the bracket is its own brick. It also masks NMI for the upload window:
; FORCED BLANK does NOT stop the engine's NMI handler (CLAUDE.md "Forced-Blank
; Does NOT Mask NMI"), and the engine NMI commits VMADD + runs tilemap/OAM DMA
; every VBlank. A long CPU-side VRAM upload running with NMI live gets
; preempted mid-loop, VMADD is clobbered, and the rest of the upload lands in
; random VRAM. So sf_blank_enter ALSO masks NMI ($4200=0) and acks any pending
; one; sf_blank_exit re-enables it ($4200=$81, NMI + auto-joypad).
;
; CONTRACT
; --------
;   sf_blank_enter   raise forced blank + mask NMI. Entry/exit A16/I16. The
;                    INIDISP shadow's brightness nibble is PRESERVED (only the
;                    blank bit is forced) so sf_blank_exit restores the same
;                    brightness the scene wants — set SHADOW_INIDISP's low
;                    nibble (e.g. $0F) before sf_blank_exit if you want a
;                    different brightness than was active on enter.
;   sf_blank_exit    drop forced blank (restore INIDISP from SHADOW_INIDISP
;                    with bit 7 cleared) + re-enable NMI. Entry/exit A16/I16.
;
; The two must bracket a contiguous region with NO sf_frame_begin/end (no NMI
; wait) between them — NMI is masked, so a frame-wait would hang. Do all the
; mode-switch uploads (sf_mode7_off/on, gfxmode, sf_load_bg_chr/pals, mset,
; sf_mode7_load_map) inside the bracket, then exit and resume the frame loop.
;
; USAGE (the RPG town init — Mode 7 -> Mode 1):
;   sf_blank_enter
;       sf_mode7_off                ; release CH5/6, zero NMI_HDMA_ENABLE
;       gfxmode #1                  ; <-- writes $2100=$0F (screen ON!) ...
;       sf_blank_enter              ; ... so RE-RAISE blank after gfxmode
;       sf_load_bg_chr ...          ; upload Mode 1 CHR under blank
;       sf_load_bg_pals ...
;       ... mset the tilemap ...
;   sf_blank_exit
; =============================================================================

.ifndef SF_SCENE_MODE_INC
SF_SCENE_MODE_INC = 1

.include "engine_state.inc"     ; SHADOW_INIDISP equate (idempotent — guarded)

; -----------------------------------------------------------------------------
; sf_blank_enter — raise forced blank ($2100 bit 7) and mask NMI for an upload.
; -----------------------------------------------------------------------------
; Sets SHADOW_INIDISP bit 7 (so the engine NMI, if it were to fire before the
; mask lands, would re-commit a blanked INIDISP), writes $2100 directly for
; immediate effect, then masks NMI ($4200=0) and acks any pending NMI by
; reading $4210 (RDNMI, read-to-clear). Idempotent — safe to call twice (e.g.
; re-raising after gfxmode turns the screen back on).
;
; WIDTH-RISK: entry A16/I16 (asserted, safe-by-default). The body toggles to
; A8 for the INIDISP / $4200 / $4210 byte writes (1-byte PPU + CPU regs), then
; restores A16/I16 at the tail. The A8 region is the documented blank+NMI-mask
; toggle; exit = A16/I16.
.macro sf_blank_enter
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    ; Order matters: mask NMI FIRST, ack any pending one, THEN raise blank.
    ; If blank were raised before the mask, an NMI firing in the gap would
    ; run the engine's commit/DMA path (committing the half-set shadows and
    ; re-reading auto-joypad) mid-swap — a race that silently corrupts the
    ; transition (CLAUDE.md "Forced-Blank Does NOT Mask NMI" canonical order).
    stz $4200                   ; NMITIMEN: mask NMI + IRQ + auto-joypad
    lda $4210                   ; RDNMI — ack/clear any pending NMI (read-clear)
    lda SHADOW_INIDISP
    ora #$80                    ; force blank bit, preserve brightness nibble
    sta SHADOW_INIDISP
    sta $2100                   ; INIDISP — immediate forced blank
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_blank_exit — drop forced blank (restore INIDISP) and re-enable NMI.
; -----------------------------------------------------------------------------
; Clears SHADOW_INIDISP bit 7 (keeping the brightness nibble the scene set),
; writes $2100 directly, then re-enables NMI + auto-joypad ($4200=$81 — the
; standard engine bootstrap value). After this the screen shows the new mode at
; the shadow's brightness and the frame loop's sf_frame_begin can wait on NMI
; again.
;
; WIDTH-RISK: entry A16/I16 (asserted). The body toggles A8 for the INIDISP /
; $4200 byte writes, then restores A16/I16 at the tail. Exit = A16/I16.
.macro sf_blank_exit
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda SHADOW_INIDISP
    and #$7F                    ; clear force-blank bit, keep brightness nibble
    sta SHADOW_INIDISP
    sta $2100                   ; INIDISP — screen ON at the shadow brightness
    lda #$81
    sta $4200                   ; NMITIMEN: NMI on + auto-joypad
    rep #$30
    .a16
    .i16
.endmacro

; =============================================================================
; sf_swap_to_mode7 — the first-class Mode-1 -> Mode-7 SCENE SWAP primitive.
; =============================================================================
; The promotion of the RPG/boss "forced-blank mode swap" sequence into ONE
; parameterized brick. A Mode-1 -> Mode-7 switch is discontinuous (BGMODE,
; the whole VRAM image, and the shared CGRAM 0-15 all change at once); this
; macro brackets the whole rebuild in forced blank + NMI mask so no torn frame
; is ever shown, and bakes in the three gotchas the hand-rolled sequence hit:
;
;   GOTCHA 1 — CGRAM 0-15 is SHARED between the Mode-1 BG palette and the
;     Mode-7 plane palette. A Mode-1 BG-palette load earlier overwrote 0-15,
;     so the Mode-7 plane would render with the wrong (often near-black)
;     colours. This macro RE-STAGES the Mode-7 palette under the blank.
;   GOTCHA 2 — BG1 CHR (word $2000) sits INSIDE the Mode-7 map region
;     ($0000-$3FFF). The Mode-1 BG CHR upload clobbered the Mode-7 image, so
;     this macro RE-UPLOADS the Mode-7 map under the blank.
;   GOTCHA 3 — sf_boss_mode7_on must run under the blank (it writes BGMODE +
;     TM + M7SEL immediately); the matrix/center come from the caller AFTER.
;
; CONTRACT
; --------
;   sf_swap_to_mode7 map_label, map_size, pal_src, pal_count
;     map_label   LABEL of the interleaved Mode 7 VRAM blob (sf_mode7_load_map
;                 takes .loword/bank, so any bank works).
;     map_size    transfer size in BYTES (#$8000 = full 32KB), verbatim 16-bit.
;     pal_src     ROM label of the Mode 7 / plane palette (N .word BGR15).
;     pal_count   number of COLOURS to restage into CGRAM 0.. as a BARE
;                 constant (e.g. 16, NOT #16 — it is used in a `cpx #(N*2)`
;                 expression). The macro writes pal_count*2 bytes to CGDATA.
;
;   Brackets blank_enter ... blank_exit internally — do NOT nest it inside
;   another sf_blank_enter/exit. After it returns the screen shows the Mode 7
;   plane (BG1) + OBJ at the shadow brightness; call sf_boss_center / the first
;   sf_boss_matrix AFTER it (they only touch shadows the NMI commits, and NMI
;   is live again by then). Requires sf_mode7.inc (sf_mode7_load_map) and
;   sf_mode7_affine.inc (sf_boss_mode7_on) to be included by the template.
;   Clobbers A, X, Y.
;
; WIDTH-RISK: entry A16/I16. sf_blank_enter / sf_mode7_load_map /
; sf_boss_mode7_on each manage their own A8/A16 toggles and exit A16/I16; the
; CGRAM restage loop here runs A8/I16 (byte writes to $2122, 16-bit index) and
; is restored to A16/I16 before sf_blank_exit. Exit = A16/I16.
.macro sf_swap_to_mode7 sf_map, sf_map_size, sf_pal_src, sf_pal_count
    .local cgloop
    rep #$30
    .a16
    .i16
    sf_blank_enter                  ; forced blank + NMI mask for the swap

    ; GOTCHA 2 — re-upload the Mode 7 plane image (the Mode-1 BG CHR clobbered
    ; VRAM $2000, which lives inside the $0000-$3FFF Mode 7 region).
    sf_mode7_load_map sf_map, sf_map_size

    ; GOTCHA 1 — re-stage the Mode 7 / plane palette into CGRAM 0.. (a prior
    ; Mode-1 BG palette load overwrote the shared 0-15 region).
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                       ; CGADD = 0
    ldx #$0000
cgloop:
    .a8
    lda f:sf_pal_src, x
    sta $2122                       ; CGDATA (low then high byte auto-pair)
    inx
    cpx #((sf_pal_count) * 2)
    bne cgloop
    rep #$30
    .a16
    .i16

    ; GOTCHA 3 — switch the PPU to the whole-plane affine Mode 7 (sets BGMODE=7,
    ; TM=BG1+OBJ, M7SEL, M7_PV_ACTIVE=1; arms NO HDMA; installs identity matrix).
    sf_boss_mode7_on

    sf_blank_exit                   ; drop forced blank + re-enable NMI
    rep #$30
    .a16
    .i16
.endmacro

; =============================================================================
; sf_swap_to_mode1 — the Mode-7 -> Mode-1 reverse SCENE SWAP primitive.
; =============================================================================
; The mirror of sf_swap_to_mode7: leave Mode 7 (release its HDMA channels +
; restore a Mode-1 layer set) and rebuild a Mode-1 BG scene under one forced
; blank. gfxmode turns the screen back ON mid-sequence, so the macro RE-RAISES
; the blank after it (the documented gfxmode gotcha) before the caller's CHR /
; palette / tilemap uploads land. The caller supplies those uploads via a
; "body" — but ca65 macros can't take a code block, so this macro does the
; FRAMING (off -> gfxmode -> re-blank ... exit) and the caller runs its BG
; uploads BETWEEN sf_swap_to_mode1_begin and sf_swap_to_mode1_end.
;
;   sf_swap_to_mode1_begin mode    raise blank, sf_mode7_off, gfxmode #mode,
;                                  re-raise blank. After it: do BG CHR/pal/mset
;                                  uploads (all under the still-raised blank).
;   sf_swap_to_mode1_end TM_value  set SHADOW_TM (verbatim imm, e.g. #$11 for
;                                  BG1+OBJ — mask BG2/BG3 so uninit CHR doesn't
;                                  decode as garbage) + drop blank + re-enable NMI.
;
; Phase 2 owns the meteor-event EXIT, so the template here uses _to_mode7 only;
; the reverse pair ships now so the swap primitive is complete + symmetric.
; WIDTH-RISK: both halves enter/exit A16/I16; internal A8 toggles for the
; gfxmode/TM/INIDISP byte writes are local to each half.
.macro sf_swap_to_mode1_begin sf_mode
    rep #$30
    .a16
    .i16
    sf_blank_enter
    sf_mode7_off                    ; release CH5/6, restore saved BGMODE
    gfxmode sf_mode                 ; sets bases + clears tilemaps + screen ON
    sf_blank_enter                  ; ...so RE-RAISE blank after gfxmode
    rep #$30
    .a16
    .i16
.endmacro

; WIDTH-RISK: entry A16/I16; A8 for the SHADOW_TM/$212C byte writes; sf_blank_exit
; restores A16/I16. Exit = A16/I16.
.macro sf_swap_to_mode1_end sf_tm
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda sf_tm
    sta SHADOW_TM
    sta $212C                       ; TM — immediate effect under forced blank
    rep #$30
    .a16
    .i16
    sf_blank_exit
    rep #$30
    .a16
    .i16
.endmacro

.endif ; SF_SCENE_MODE_INC
