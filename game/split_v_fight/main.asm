; =============================================================================
; split_v_fight — the seamless distance-driven fighting split
; =============================================================================
; A ground-level two-fighter arena whose camera splits SEAMLESSLY into left and
; right halves as the fighters part, and merges just as seamlessly as they
; close. The split is not a toggle: the two cameras diverge continuously from
; the fighter distance, so at zero separation the halves are pixel-identical
; and the ever-present seam is invisible. A beveled BG3 bar grows from zero
; width once the halves part. The fighters may walk past each other and swap
; sides, and the split follows the crossover.
;
; ONE SCENE. This rail's subject is the split itself; a title screen would add
; surface with no showcase value, and it could not share the fight scene
; anyway (bg_text owns BG3SC/BG34NBA and BG3 here IS the divider).
;
; BUILD VARIANTS, for race-free proofs (the generic make rule cannot pass -D;
; see tools/build_split_v_variants.sh):
;   -D SV_HOLD=n   freeze the fighters symmetric at +-n px about centre and let
;                  the spread ease to its fixed point. A STATIC state, so a
;                  framebuffer comparison has nothing to race against.
;                  A NEGATIVE n puts fighter 1 to the RIGHT of fighter 2 — the
;                  crossed/swapped state.
;   -D SV_NOWIN    the no-split REFERENCE: window off, BG3 off the main screen.
;                  One camera, no divider. The merge proof is hold-merge
;                  diffing to zero against this.
;   -D SV_AUTODEMO ignore input; march the fighters wall to wall THROUGH each
;                  other so the whole separate/merge/side-swap cycle plays out
;                  on its own.

.p816
.smart

.define SF_HDR_TITLE "SPLIT V FIGHT"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. The generated header suggests wrapping it
; in `.scope <id>` for a multi-scene ROM so two scenes' symbols cannot collide;
; this rail has exactly one scene, and both split_v_bg and split_v_obj resolve
; its symbols from file scope, so a wrapper here would only hide them from the
; features that need them.
.include "engine_state_fight.inc"   ; GENERATED — the fight scene's map
.include "tad-audio.inc"            ; vendor/tad — the TAD API imports + enums
.include "tad_audio_enums.inc"      ; GENERATED — Song:: / SFX:: ids
.include "split_v.inc"              ; the rail's geometry + tuning
.include "header.inc"
.include "init.inc"                 ; RESET: native, A16/I16, forced blank

.segment "CODE"

; The vectors header.inc points at. The stub is the pre-arm handler; NMI proper
; hands straight to the scene manager's core, which commits INIDISP and runs
; sm_nmi_hook exactly once per armed VBlank.
NMI_STUB:
    rti
NMI:
    jmp sm_nmi_core

; --- engine features (the composition game.toml declares) ------------------
.include "scene_mgr.asm"
.include "fade.asm"
.include "input.asm"
.include "input2.asm"
.include "oam_sprites.asm"

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build. The
; PRESENCE side is `make rom-unbacked` (docs/37): a claim with no .incbin here
; would reserve the window and let whatever the linker left there be read as
; art, which is exactly the grad_tabs bug that gate exists to close.
.segment "BANK2"
sv_knight_chr_bin:
    .incbin "sv_knight_chr.bin"
.assert ^sv_knight_chr_bin = ES_R_SV_KNIGHT_CHR_BANK, error, "sv_knight_chr bank drifted from allocator claim"
.assert .loword(sv_knight_chr_bin) = ES_R_SV_KNIGHT_CHR_ADDR, error, "sv_knight_chr addr drifted from allocator claim"
sv_stage_map_bin:
    .incbin "sv_stage_map.bin"
.assert ^sv_stage_map_bin = ES_R_SV_STAGE_MAP_BANK, error, "sv_stage_map bank drifted from allocator claim"
.assert .loword(sv_stage_map_bin) = ES_R_SV_STAGE_MAP_ADDR, error, "sv_stage_map addr drifted from allocator claim"
sv_stage_chr_bin:
    .incbin "sv_stage_chr.bin"
.assert ^sv_stage_chr_bin = ES_R_SV_STAGE_CHR_BANK, error, "sv_stage_chr bank drifted from allocator claim"
.assert .loword(sv_stage_chr_bin) = ES_R_SV_STAGE_CHR_ADDR, error, "sv_stage_chr addr drifted from allocator claim"
sv_bevel_chr_bin:
    .incbin "sv_bevel_chr.bin"
.assert ^sv_bevel_chr_bin = ES_R_SV_BEVEL_CHR_BANK, error, "sv_bevel_chr bank drifted from allocator claim"
.assert .loword(sv_bevel_chr_bin) = ES_R_SV_BEVEL_CHR_ADDR, error, "sv_bevel_chr addr drifted from allocator claim"
sv_bevel_pal_bin:
    .incbin "sv_bevel_pal.bin"
.assert ^sv_bevel_pal_bin = ES_R_SV_BEVEL_PAL_BANK, error, "sv_bevel_pal bank drifted from allocator claim"
.assert .loword(sv_bevel_pal_bin) = ES_R_SV_BEVEL_PAL_ADDR, error, "sv_bevel_pal addr drifted from allocator claim"
sv_knight_pal_b_bin:
    .incbin "sv_knight_pal_b.bin"
.assert ^sv_knight_pal_b_bin = ES_R_SV_KNIGHT_PAL_B_BANK, error, "sv_knight_pal_b bank drifted from allocator claim"
.assert .loword(sv_knight_pal_b_bin) = ES_R_SV_KNIGHT_PAL_B_ADDR, error, "sv_knight_pal_b addr drifted from allocator claim"
sv_knight_pal_r_bin:
    .incbin "sv_knight_pal_r.bin"
.assert ^sv_knight_pal_r_bin = ES_R_SV_KNIGHT_PAL_R_BANK, error, "sv_knight_pal_r bank drifted from allocator claim"
.assert .loword(sv_knight_pal_r_bin) = ES_R_SV_KNIGHT_PAL_R_ADDR, error, "sv_knight_pal_r addr drifted from allocator claim"
sv_stage_pal_bin:
    .incbin "sv_stage_pal.bin"
.assert ^sv_stage_pal_bin = ES_R_SV_STAGE_PAL_BANK, error, "sv_stage_pal bank drifted from allocator claim"
.assert .loword(sv_stage_pal_bin) = ES_R_SV_STAGE_PAL_ADDR, error, "sv_stage_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped features (after the blobs their uploads read) --------
.include "split_v_bg.asm"
.include "split_v_obj.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/fight.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; Every writer programs its own VMADD where it needs one, so the order is
; free. sv_vblank commits the two cameras and the divider band from the one
; shadow pair; oam_nmi_dma commits the sprite shadow the tick staged.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow
    jsr sv_vblank               ; the two cameras + the divider band
    rts

; --- scene dispatch tables (manifest order: fight=0) -----------------------
sm_enter_tab:   .word fight::enter
sm_tick_tab:    .word fight::tick
sm_exit_tab:    .word fight::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr input2_init
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- audio boot (TAD contract): interrupts are DISABLED here by
    ; construction — init.inc leaves NMI off and $4200 is written only below —
    ; so the S-SMP is still in the IPL.
    sep #$20
    .a8
    jsl Tad_Init
    lda #Song::slice_b_song
    jsr Tad_LoadSong
    rep #$20
    .a16
    ; ---- enter the boot scene (id 0 = fight) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI + auto-joypad ------------------------------------
    sep #$20
    .a8
    lda #$81
    sta a:$4200                 ; NMITIMEN: NMI + auto-joypad
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write: scene_mgr
    ; commits INIDISP in its NMI, so a direct write here would be overwritten on
    ; the first VBlank. Without this the ROM is correct in VRAM, CGRAM and OAM
    ; and renders a black screen — which is exactly what the first boot did.
    ;
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate. Call it from A16 and
    ; the CPU reads the following opcode byte as the immediate's high half — the
    ; ramp never arms, INIDISP stays at brightness 0, and the ROM renders black
    ; with correct VRAM, CGRAM and OAM. That is rule 6's silent-corruption class
    ; arriving through a CROSS-FILE caller/callee contract, which width-lint
    ; cannot see in either direction (CLAUDE.md rule 6, "the single-file limit
    ; remains"). It cost a real debugging round here.
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    .i16
    jsr input_read
    jsr input2_read
    jsr sm_tick
    jsr fade_tick
    ; ---- audio pump: once per frame, MAIN THREAD ONLY (the TAD ABI forbids
    ; ISR calls).
    sep #$20
    .a8
    jsl Tad_Process
    rep #$20
    .a16
    jsr sm_frame_sync
    bra @loop
