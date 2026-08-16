; =============================================================================
; split_v_seamtrial — the seamless split, in isolation
; =============================================================================
; ONE stage viewed by TWO cameras at `mid ± spread`, clipped to opposite halves
; of the screen by an always-on PPU window 1. At spread 0 the halves are
; pixel-identical and the ever-present seam is invisible; as spread grows the
; halves diverge and a bevelled BG3 bar opens from zero width to mark the
; divide. `spread` sweeps 0 -> SVS_SPREAD_MAX -> 0 as a triangle wave, with no
; input at all.
;
; THIS RAIL IS A DIRECTOR, and that is the whole of it. The mechanism below
; (mid, spread) is `split_v_bg`, built for `split_v_fight` and composed here
; unchanged. What the trial replaces is the thing ABOVE it: where the fighting
; rail derives (mid, spread) from a fighter distance through an ease and a
; 72-frame dwell, this one derives them from the frame count.
;
; WHY THAT MATTERS AND IS NOT JUST A SMALLER GAME. `split_v_fight` cannot state
; its own headline claim from its interactive build -- capturing two running
; ROMs at the same instant and hoping the ease had settled is a race a test
; loses intermittently -- so it ships FIVE `-D` variant ROMs to freeze the
; swept variable. A frame-driven triangle needs none of that:
; `Machine(rom).advance(N)` fixes `spread` by construction, so every proof here
; is an absolute-frame picture of a determined state. This rail therefore ships
; NO variants and NO `-D` knobs: a hold knob and a no-window knob would both be
; freezing something that is already determined.
;
; ONE SCENE, no title: the subject is the split. Also not freely available --
; `bg_text` claims BG3SC/BG34NBA and BG3 here IS the divider.

.p816
.smart

.define SF_HDR_TITLE "SEAM V TRIAL"
SF_HDR_TITLE_SET = 1

.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
; The scene map, included UNSCOPED. One scene, and split_v_bg resolves the
; scene's symbols from file scope, so a `.scope` wrapper here would only hide
; them from the feature that needs them (split_v_fight's main.asm makes the same
; call for the same reason).
.include "engine_state_trial.inc"   ; GENERATED — the trial scene's map
.include "seamtrial.inc"            ; the rail's geometry + sweep tuning
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

; --- the ROM claim sites ---------------------------------------------------
; Each site .asserts its blob's linker placement against the allocator's
; emitted claim, so a drift between the map and the tree stops the build; the
; PRESENCE side is `make rom-unbacked` (docs/37).
;
; EIGHT CLAIMS, FIVE OF THEM THIS RAIL'S. `split_v_bg` declares
; `depends = ["split_v_rom"]`, and that blob carries `split_v_fight`'s FIGHTER
; art next to the stage and bevel this rail uploads. The dependency is coarser
; than the use. The three fighter claims are therefore backed by ZERO blobs --
; `svs_pad2048.bin` / `svs_pad32.bin`, generated as zeroes on purpose. Backing
; them with the fighters' real art would have satisfied the gate while hiding
; the coupling behind bytes that look intentional; zeroes say what is true,
; which is that this rail never reads them.
;
; Order follows the allocator's own packing (largest-first from window 1), so
; the .asserts below are a check rather than a coincidence.
.segment "BANK1"
sv_knight_chr_bin:
    .incbin "svs_pad2048.bin"
.assert ^sv_knight_chr_bin = ES_R_SV_KNIGHT_CHR_BANK, error, "sv_knight_chr bank drifted from allocator claim"
.assert .loword(sv_knight_chr_bin) = ES_R_SV_KNIGHT_CHR_ADDR, error, "sv_knight_chr addr drifted from allocator claim"
sv_stage_map_bin:
    .incbin "svs_stage_map.bin"
.assert ^sv_stage_map_bin = ES_R_SV_STAGE_MAP_BANK, error, "sv_stage_map bank drifted from allocator claim"
.assert .loword(sv_stage_map_bin) = ES_R_SV_STAGE_MAP_ADDR, error, "sv_stage_map addr drifted from allocator claim"
sv_stage_chr_bin:
    .incbin "svs_stage_chr.bin"
.assert ^sv_stage_chr_bin = ES_R_SV_STAGE_CHR_BANK, error, "sv_stage_chr bank drifted from allocator claim"
.assert .loword(sv_stage_chr_bin) = ES_R_SV_STAGE_CHR_ADDR, error, "sv_stage_chr addr drifted from allocator claim"
sv_bevel_chr_bin:
    .incbin "svs_bevel_chr.bin"
.assert ^sv_bevel_chr_bin = ES_R_SV_BEVEL_CHR_BANK, error, "sv_bevel_chr bank drifted from allocator claim"
.assert .loword(sv_bevel_chr_bin) = ES_R_SV_BEVEL_CHR_ADDR, error, "sv_bevel_chr addr drifted from allocator claim"
sv_bevel_pal_bin:
    .incbin "svs_bevel_pal.bin"
.assert ^sv_bevel_pal_bin = ES_R_SV_BEVEL_PAL_BANK, error, "sv_bevel_pal bank drifted from allocator claim"
.assert .loword(sv_bevel_pal_bin) = ES_R_SV_BEVEL_PAL_ADDR, error, "sv_bevel_pal addr drifted from allocator claim"
sv_knight_pal_b_bin:
    .incbin "svs_pad32.bin"
.assert ^sv_knight_pal_b_bin = ES_R_SV_KNIGHT_PAL_B_BANK, error, "sv_knight_pal_b bank drifted from allocator claim"
.assert .loword(sv_knight_pal_b_bin) = ES_R_SV_KNIGHT_PAL_B_ADDR, error, "sv_knight_pal_b addr drifted from allocator claim"
sv_knight_pal_r_bin:
    .incbin "svs_pad32.bin"
.assert ^sv_knight_pal_r_bin = ES_R_SV_KNIGHT_PAL_R_BANK, error, "sv_knight_pal_r bank drifted from allocator claim"
.assert .loword(sv_knight_pal_r_bin) = ES_R_SV_KNIGHT_PAL_R_ADDR, error, "sv_knight_pal_r addr drifted from allocator claim"
sv_stage_pal_bin:
    .incbin "svs_stage_pal.bin"
.assert ^sv_stage_pal_bin = ES_R_SV_STAGE_PAL_BANK, error, "sv_stage_pal bank drifted from allocator claim"
.assert .loword(sv_stage_pal_bin) = ES_R_SV_STAGE_PAL_ADDR, error, "sv_stage_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene-scoped feature (after the blobs its uploads read) -----------
.include "split_v_bg.asm"

; --- the scene ------------------------------------------------------------
.include "scenes/trial.asm"

; --- sm_nmi_hook: per-frame VBlank work -----------------------------------
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
;
; ONE writer. sv_vblank commits both cameras and the divider band from the one
; (mid, spread) shadow, so they cannot disagree about where the seam is.
sm_nmi_hook:
    .a8
    .i16
    jsr sv_vblank               ; the two cameras + the divider band
    rts

; --- scene dispatch tables (manifest order: trial=0) -----------------------
sm_enter_tab:   .word trial::enter
sm_tick_tab:    .word trial::tick
sm_exit_tab:    .word trial::exit

; --- MAIN: boot -----------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr fade_init
    ; ---- enter the boot scene (id 0 = trial) under forced blank ----------
    ldx #0
    jsr (sm_enter_tab, x)
    ; ---- screen on: NMI (no auto-joypad — this rail reads no pad) --------
    sep #$20
    .a8
    lda #$80
    sta a:$4200                 ; NMITIMEN: VBlank NMI, auto-joypad OFF
    ; Forced blank is lifted by the FADE, not by a bare INIDISP write:
    ; scene_mgr commits INIDISP in its NMI, so a direct write here would be
    ; overwritten on the first VBlank.
    ;
    ; CALLED IN A8, DELIBERATELY. fade_start_in is `.a8` (fade.asm:18) and its
    ; `lda #1` therefore assembles as a ONE-byte immediate. Called from A16 the
    ; CPU eats the following opcode byte as the immediate's high half, the ramp
    ; never arms, and the ROM renders black with correct VRAM and CGRAM. That
    ; is rule 6's silent-corruption class arriving through a CROSS-FILE
    ; caller/callee contract, which width-lint cannot see in either direction.
    ; It cost split_v_fight a real debugging round.
    jsr fade_start_in
    rep #$20
    .a16
@loop:
    .a16
    .i16
    jsr sm_tick
    jsr fade_tick
    jsr sm_frame_sync
    bra @loop
