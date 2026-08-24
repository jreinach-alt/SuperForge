; =============================================================================
; rpg_logic.asm — the rpg rail's cross-scene game state + the save round trip
; =============================================================================
; GAME code, not engine (`role = "game_logic"`). It lives here because that is
; where the allocator looks for a claim, and it holds the two things that must
; outlive a scene: the player's position in BOTH worlds, and the save payload.
;
; The per-scene movement is NOT here — it is in the scenes, because each reads
; something scene-scoped (the overworld reads mode7_persp's ES_M7ORG and probes
; col_map; the town reads rpgt_blocks). Splitting it that way keeps this file
; free of any symbol that only exists in one scene.

; --- the global hot block (rpg_hot; feature.toml documents the layout) ------
RPG_CAM_TX = ES_RPG_HOT + 0         ; overworld camera tile — the player's world
RPG_CAM_TY = ES_RPG_HOT + 2         ;   position, always on an 8-px boundary
RPG_TOWN_TX = ES_RPG_HOT + 4        ; town avatar tile
RPG_TOWN_TY = ES_RPG_HOT + 6
RPG_STEP_DX = ES_RPG_HOT + 8        ; the in-flight slide's DIRECTION on each
RPG_STEP_DY = ES_RPG_HOT + 10       ;  axis: -1, 0 or +1, applied once per
                                    ;  pixel laid down (not per frame — how
                                    ;  many pixels a frame lays is the
                                    ;  region's answer, not this pair's)
RPG_STEP_PX = ES_RPG_HOT + 12       ; 1 B: PIXELS LEFT to the destination tile
                                    ;  (0 = at rest). Armed to TILE_PX by
                                    ;  try_step and spent down by the walk;
                                    ;  arrival is this reaching zero. It counts
                                    ;  DISTANCE, and it counted frames until
                                    ;  `region` + `tick_scale` were composed —
                                    ;  the two were the same number only
                                    ;  because an NTSC frame lays exactly one
                                    ;  pixel, which is what a PAL frame does
                                    ;  not do. game.toml's region note derives
                                    ;  the change.
RPG_PEND = ES_RPG_HOT + 13          ; 1 B: pending swap id + 1 (0 = none)
RPG_T0 = ES_RPG_HOT + 14            ; 2 B: shared TRANSIENT scratch, consumed
                                    ;  inside one call — rpg_town and rpg_obj
                                    ;  use it the same way, and never across a
                                    ;  jsr that could reach the other
RPG_TOWN_REP = ES_RPG_HOT + 16      ; 1 B: town hold-to-walk throttle — THE
                                    ;  UNITS LEFT before the next tile commits,
                                    ;  spent by the same published step the
                                    ;  overworld spends in pixels. 0 means no
                                    ;  direction is held, so the next press
                                    ;  steps at once. Town-only — the
                                    ;  overworld's step_px is its sibling.
RPG_TOWN_FLARE = ES_RPG_HOT + 17    ; 1 B: save-torch flare countdown,
                                    ;  NMI-driven; 0 = idle

RPG_SAVE_TX = ES_RPG_SAVE + 0       ; the payload, staged where sv_save reads it
RPG_SAVE_TY = ES_RPG_SAVE + 2
RPG_SAVE_VISITS = ES_RPG_SAVE + 4
RPG_SAVE_LEN = 6
RPG_SAVE_VER = 1

; --- rpg_do_save: stage the payload and write slot 0 ------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16 (sv_save's contract too).
.a16
.i16
rpg_do_save:
    lda z:RPG_TOWN_TX
    sta a:RPG_SAVE_TX
    lda z:RPG_TOWN_TY
    sta a:RPG_SAVE_TY
    lda a:US_VISITS
    sta a:RPG_SAVE_VISITS
    lda #0
    sta z:SV_SLOT                   ; slot 0
    lda #RPG_SAVE_LEN
    sta z:SV_LEN
    lda #RPG_SAVE_VER
    sta z:SV_VER
    lda #ES_RPG_SAVE
    sta z:SV_PTR
    lda #ES_RPG_SAVE_BANK
    sep #$20
    .a8
    sta z:SV_PTR + 2
    rep #$20
    .a16
    jsr sv_save
    rts

; --- rpg_try_load: restore from slot 0 if it verifies -----------------------
; Out: A16 = 1 if a valid save was applied, 0 otherwise (dest untouched on
; every reject — sv_load's contract, and the reason this branches on the RETURN
; CODE rather than on any SRAM byte: virgin SRAM is power-on garbage under the
; random regime, exactly like a real cart's first power-up). In/out: A16/I16,
; DB=0. Clobbers A, X, Y. WIDTH-RISK: exported. Entry A16/I16, exit A16/I16.
.a16
.i16
rpg_try_load:
    lda #0
    sta z:SV_SLOT
    lda #RPG_SAVE_LEN
    sta z:SV_CAP                    ; the dest really is this big; a longer
                                    ;  stored payload is corrupt-shaped and
                                    ;  sv_load rejects it whole
    lda #ES_RPG_SAVE
    sta z:SV_PTR
    lda #ES_RPG_SAVE_BANK
    sep #$20
    .a8
    sta z:SV_PTR + 2
    rep #$20
    .a16
    jsr sv_load
    cmp #RPG_SAVE_LEN
    beq @apply
    lda #0
    rts
@apply:
    .a16
    .i16
    lda a:RPG_SAVE_TX
    sta z:RPG_TOWN_TX
    lda a:RPG_SAVE_TY
    sta z:RPG_TOWN_TY
    lda a:RPG_SAVE_VISITS
    sta a:US_VISITS
    lda #1
    rts
