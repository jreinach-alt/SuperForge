; =============================================================================
; railshooter — THE POOL DEBUT
; =============================================================================
; ROM skeleton. Every RAM/VRAM/CGRAM address and channel comes from the
; allocator's emitted includes; hardware I/O ports are the only literals
; (no_literals-gated). The one scene lives in a `.scope` so its claims stay
; distinct symbols, matching every other rail's shape.
.p816
.smart

.define SF_HDR_TITLE "RAIL BLASTER"
SF_HDR_TITLE_SET = 1
SF_HDR_ROM_SIZE = $09               ; 512 KB
.include "engine_state_globals.inc" ; GENERATED — system + game-lifetime map
.include "railshooter.inc"          ; the rail's constants (no addresses)
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
.include "pool.asm"                 ; four routines (init/spawn/kill/count)
                                    ;   + POOL_BIND, over ES_POOL_PTR
; split_band's binding contract — the five symbols it carries no default for.
; THIS RAIL'S TOP BAND HAS NO BG3: Mode 7 has one BG layer plus OBJ, so there
; is no text renderer to give a canvas to. The sky band shows BG2 (sky_band's
; ramp) + OBJ, so a hazard or the ship crossing the horizon still draws.
SB_LINES    = RS_SKY_LINES      ; the seam: sky band rows 0..43
SB_MODE_TOP = $09               ; Mode 1, BG3 priority high
SB_MODE_BOT = $07               ; Mode 7 (the grid)
SB_TM_TOP   = $12               ; BG2 (sky_band's ramp) + OBJ
SB_TM_BOT   = $11               ; BG1 (the Mode 7 grid) + OBJ
.include "split_band.asm"
.include "oam_sprites.asm"

; --- global ROM blobs (allocator-claimed; the .asserts refuse drift) --------
; ORDER AND SEGMENT ARE THE ALLOCATOR'S, NOT A CHOICE — the allocation report
; is the authority and the `.assert`s turn a wrong guess into a build refusal
; instead of a ROM that reads the neighbouring blob's bytes.
.repeat ES_R_POSES_AB_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 1)
.ident(.sprintf("poses_ab_t%d", PI)):
    .incbin "poses_ab.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_ab_t%d", PI)) = .ident(.sprintf("ES_R_POSES_AB_T%d_BANK", PI)), error, "poses_ab chunk bank drifted"
.endrepeat
.repeat ES_R_POSES_CD_CHUNKS, PI
.segment .sprintf("BANK%d", PI + 3)
.ident(.sprintf("poses_cd_t%d", PI)):
    .incbin "poses_cd.bin", PI * 32768, 32768
.assert ^.ident(.sprintf("poses_cd_t%d", PI)) = .ident(.sprintf("ES_R_POSES_CD_T%d_BANK", PI)), error, "poses_cd chunk bank drifted"
.endrepeat

; The Mode 7 plane is a whole 32 KB window on its own.
; RS_PROBE_MARKER (-D, tools/build_rs_probe.sh) swaps the plane for the
; MEASUREMENT one: same 32 KB, same geometry, same everything the rail does
; with it — only the tile COLOURS differ, so the magenta index marks the grid
; intersections and nothing else. It is how "how fast does the surface move at
; screen row r" is read off the picture. The shipping ROM never sees it, and
; the two builds' OBJ trajectories are asserted identical
; (tests/test_railshooter.py, the calibration case).
;
; THE SWITCH IS ON THE FILENAME, NOT ON THE `.incbin`. `make rom-unbacked`'s
; backing gate refuses to credit a claim site inside ANY `.if`/`.ifdef` (docs/37
; §5, limit 4 — deliberately over-strict, because `.if 0` around an `.incbin`
; with the drift asserts left outside is the exact shape that once shipped a
; claim reading its neighbour's bytes). One unconditional `.incbin` of a
; conditionally-defined name keeps the site credited in BOTH builds.
.ifdef RS_PROBE_MARKER
.define RS_MAP_BLOB "rs_map_probe.bin"
.else
.define RS_MAP_BLOB "rs_map.bin"
.endif

.segment "BANK5"
rs_map_bin:
    .incbin RS_MAP_BLOB
.assert ^rs_map_bin = ES_R_RS_MAP_BANK, error, "rs_map bank drifted from allocator claim"
.assert .loword(rs_map_bin) = ES_R_RS_MAP_ADDR, error, "rs_map addr drifted from allocator claim"

; The rest of this rail's bytes share the next window, in the allocator's
; packing order — a `.incbin` out of order fails the addr assert.
.segment "BANK6"
rs_obj_chr_bin:
    .incbin "rs_obj_chr.bin"
.assert ^rs_obj_chr_bin = ES_R_RS_OBJ_CHR_BANK, error, "rs_obj_chr bank drifted from allocator claim"
.assert .loword(rs_obj_chr_bin) = ES_R_RS_OBJ_CHR_ADDR, error, "rs_obj_chr addr drifted from allocator claim"
; The S-curve the rail flies. 512 B packs directly BEHIND the OBJ sheet — the
; packer is largest-first and 512 is the second-largest claim in this window,
; ahead of both projection halves. At 128 B it sorted between them instead, so
; growing the table to one entry per frame MOVED this site, and the addr assert
; is exactly what refused the link until it moved.
rs_path_bin:
    .incbin "rs_path.bin"
.assert ^rs_path_bin = ES_R_RS_PATH_BANK, error, "rs_path bank drifted from allocator claim"
.assert .loword(rs_path_bin) = ES_R_RS_PATH_ADDR, error, "rs_path addr drifted from allocator claim"
rs_proj_scale_bin:
    .incbin "rs_proj_scale.bin"
.assert ^rs_proj_scale_bin = ES_R_RS_PROJ_SCALE_BANK, error, "rs_proj_scale bank drifted from allocator claim"
.assert .loword(rs_proj_scale_bin) = ES_R_RS_PROJ_SCALE_ADDR, error, "rs_proj_scale addr drifted from allocator claim"
rs_proj_scan_bin:
    .incbin "rs_proj_scan.bin"
.assert ^rs_proj_scan_bin = ES_R_RS_PROJ_SCAN_BANK, error, "rs_proj_scan bank drifted from allocator claim"
.assert .loword(rs_proj_scan_bin) = ES_R_RS_PROJ_SCAN_ADDR, error, "rs_proj_scan addr drifted from allocator claim"
rs_obj_pal_bin:
    .incbin "rs_obj_pal.bin"
.assert ^rs_obj_pal_bin = ES_R_RS_OBJ_PAL_BANK, error, "rs_obj_pal bank drifted from allocator claim"
.assert .loword(rs_obj_pal_bin) = ES_R_RS_OBJ_PAL_ADDR, error, "rs_obj_pal addr drifted from allocator claim"
rs_floor_pal_bin:
    .incbin "rs_floor_pal.bin"
.assert ^rs_floor_pal_bin = ES_R_RS_FLOOR_PAL_BANK, error, "rs_floor_pal bank drifted from allocator claim"
.assert .loword(rs_floor_pal_bin) = ES_R_RS_FLOOR_PAL_ADDR, error, "rs_floor_pal addr drifted from allocator claim"
.segment "CODE"

; --- the scene (before the dispatch tables: ca65 scopes resolve backward) ---
.include "scenes/rail.asm"

; --- sm_nmi_hook: per-frame VBlank work (after the scene: scope refs resolve)
; In: A8/I16, DB=0 (from sm_nmi_core). May clobber A/X/Y.
; THERE IS NO POSE RETARGET HERE, AND ITS ABSENCE IS THE POINT.
;
; The obvious shape for a curving rail is a desired->applied heading commit in
; this hook, eased +/-2 across the pose table's 64 headings. Two of 64 is 11
; degrees in two steps, and that quantisation reads on screen as binary
; turning: the plane snaps rather than banks.
;
; So the whole S-curve is expressed as a TRANSLATION of the camera origin
; instead — `persp_commit_origin` below is that commit, and M7X/M7Y are
; a free per-frame CPU-written VBlank shadow over a wrapping 16-bit world
; position (mode7_persp/feature.toml:36,50). `persp_set_pose` is called ONCE,
; from the scene's enter, with heading 0. So "the plane never rotates" is not a
; discipline anyone has to keep: after enter there is no code path in this ROM
; that can change the pose.
sm_nmi_hook:
    .a8
    .i16
    jsr oam_nmi_dma             ; commit the OAM shadow (the whole foreground)
    jsr rail::persp_commit_origin   ; M7X/M7Y: the S-curve reaching the PPU
    rts

; --- scene dispatch tables (manifest order: rail=0) -------------------------
sm_enter_tab:   .word rail::enter
sm_tick_tab:    .word rail::tick
sm_exit_tab:    .word rail::exit

; --- MAIN: boot -------------------------------------------------------------
; init.inc leaves: native, A16/I16, DB=0, forced blank, NMI+HDMA off.
MAIN:
    .a16
    .i16
    ; ---- boot init contracts (each feature zeroes exactly its claims) -----
    jsr sm_init
    jsr input_init
    jsr fade_init
    jsr oam_park_all            ; whole shadow written before its first DMA
    ; ---- enter the only scene under forced blank --------------------------
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
