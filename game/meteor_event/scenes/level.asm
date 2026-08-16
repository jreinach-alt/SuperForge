; =============================================================================
; scenes/level.asm — the Mode-1 slice: the walk, the freeze, and THE CAPTURE
; =============================================================================
; One scope holding this scene's map, its scene-scoped BG feature, and the
; first three states of the rail's machine (PLAY / FREEZE / CAPTURE). The
; driver lives here rather than in a `role = "game_logic"` feature: there is
; no second consumer for any of it.
;
; THE CAPTURE IS THE RAIL'S CRUX and it is game-side.
; `capture_emit` walks the candidate rows of met_bg's TILEMAP SHADOW — the
; same bytes one DMA pushed to VRAM, so it is reading what the PPU is showing
; — and for every PLATFORM cell on screen emits a 16x16 OBJ block at the
; screen pixel that tile occupies: x = sc*8 - (frozen_camx & 7), y = row*8.
; Then `bg_black` drops BG1 from TM, so what remains is OBJ only, standing on
; exactly the pixels the BG had. That equality is the alignment proof, and
; because the block CHR and the BG platform tile are one colour constant
; (gen_meteor_assets.py's selftest) it is a pixel-exact one.
;
; WRITTEN ONCE, NOT PER FRAME. A draw loop that wiped shadow OAM at the top of
; every frame would have to re-emit the whole set each time. The OAM shadow here
; is STATE, so the blocks are written once and stand untouched through the
; fade-out, the scene switch and the whole cutscene; `enter` re-parks them on
; the way back, which is this rail's "captured ground dropped".

.scope level

.include "engine_state_level.inc"    ; GENERATED — this scene's map
.include "met_bg.asm"                ; scene-scoped: the Mode-1 layer

; --- the capture's candidate rows ------------------------------------------
; The only tilemap rows the level paints platform tiles on, as BLOCK rows: a
; 16x16 block spans two BG rows, so the four-row ground band (24..27) is
; covered by block rows 24 and 26, and each two-row platform by its own top
; row. $FF-terminated.
cand_rows:
    .byte MET_PLAT_B_R0             ; 14 — platform B
    .byte MET_PLAT_A_R0             ; 18 — platform A
    .byte MET_GND_ROW0              ; 24 — ground, block row 0 (BG rows 24,25)
    .byte MET_GND_ROW0 + 2          ; 26 — ground, block row 1 (BG rows 26,27)
    .byte $FF                       ; terminator

; The scan's column step and stop. A 16x16 block spans two BG cells, and the
; extra column past 32 exists so the right edge is still covered once the
; sub-tile remainder has shifted every block left.
CAP_COL_STEP = 2
CAP_COL_END  = 34

; =============================================================================
; game_init — every [global] state word, before anything reads one
; =============================================================================
; In/out: A16/I16, DB=0. Called from MAIN's boot block, ahead of this scene's
; `enter`, because power-on WRAM is random and `enter` runs on the RETURN leg
; too — where these must NOT be reset (rule 5's write-before-read met by the
; code path, and the one-shot guard kept).
game_init:
    .a16
    .i16
    stz z:US_G_STATE                ; MET_ST_PLAY
    stz z:US_G_TIMER
    stz z:US_G_WORLDX
    stz z:US_G_CAMX
    stz z:US_G_FROZEN_CAMX
    stz z:US_G_EVENT_DONE
    stz z:US_G_GLOW
    stz z:US_G_CM_ON
    stz z:US_G_SCR
    rts

; =============================================================================
; enter — the layer, the camera, the released control
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr enter contract).
;
; Runs TWICE per event: at boot, and again when the cutscene hands back. The
; second run re-uploads the CHR, re-stages the palette and repaints the tilemap
; — except that here nothing was clobbered to begin with (met_bg's VRAM is
; pinned above the Mode 7 region), so it is the enter contract rather than
; restore code.
enter:
    .a16
    .i16
    jsr bg_arm                      ; CHR + palette + the painted tilemap
    jsr ::met_park_all              ; DROP the captured ground and the meteor
                                    ;   sprite; the tick re-draws the player

    ; ---- the m7_affine shadow, seeded before the first NMI is armed -------
    ; All sixteen bytes: the matrix half from the track's entry 0 (inert in
    ; Mode 1 — M7A-D have no effect outside Mode 7 — but written, because the
    ; NMI commit reads them every frame in every scene), and the pivot/origin
    ; half from camera_commit. Rule 5's write-before-read contract, met by the
    ; code path rather than by a zero fill.
    M7T_BIND ::met_grow_bin
    lda #0
    jsr ::m7t_apply
    jsr camera_commit

    ; ---- control released; the walk resumes where it froze ----------------
    lda #MET_ST_PLAY
    sta z:US_G_STATE
    stz z:US_G_TIMER
    jsr draw_player

    ; ---- the scene's base display (met_bg's scene_writes) -----------------
    sep #$20
    .a8
    lda #1
    sta a:$2105                     ; BGMODE 1: BG1 4bpp, BG2 4bpp, BG3 2bpp
    lda #(MET_TM_BG1 | MET_TM_OBJ)
    sta a:$212C                     ; TM: the level AND the cast

    ; ---- lift the blank, through the fade (called in A8, deliberately —
    ; fade_start_in is .a8; from A16 the CPU eats the next opcode byte as the
    ; immediate's high half and the ROM renders black) --------------------
    jsr ::fade_start_in
    rep #$20
    .a16
    rts

; =============================================================================
; exit — nothing to unwind, and that is the point
; =============================================================================
; The captured OBJ blocks and the player MUST survive into the cutscene: they
; are what the Mode-7 meteor is composited under. So this scene tears down
; nothing it drew. (met_bg's VRAM and CGRAM are the incoming scene's to
; overwrite or not; it overwrites CGRAM 0..15 and leaves the pinned Mode-1
; CHR and tilemap standing.)
exit:
    .a16
    .i16
    rts

; =============================================================================
; tick — one game frame of the Mode-1 half
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; WIDTH-RISK: A16/I16 entry; every state handler and helper is A16/I16 on both
; sides. The one A8 window is the `sm_request` call in `do_capture`, which
; restores A16 before returning.
tick:
    .a16
    .i16
    lda z:US_G_STATE
    asl                             ; *2 for the word jump table
    tax
    jmp (st_jump, x)

st_jump:
    .addr do_play                   ; MET_ST_PLAY    (0)
    .addr do_freeze                 ; MET_ST_FREEZE  (1)
    .addr do_capture                ; MET_ST_CAPTURE (2)
    .addr st_none                   ; MET_ST_SCENE   (3) — the other scene's
    .addr st_none                   ; MET_ST_RESTORE (4) — in flight

st_none:
    .a16
    .i16
    rts

; --- PLAY: walk right; the camera follows; the trigger arms the event ------
do_play:
    .a16
    .i16
    jsr play_input
    ; camera = worldx - the player's fixed screen x, clamped at 0
    lda z:US_G_WORLDX
    sec
    sbc #MET_PLAYER_SCRN_X
    bpl :+
    lda #0                          ; clamp: the world does not scroll left of 0
:   sta z:US_G_CAMX
    jsr camera_commit
    jsr draw_player
    ; ---- the trigger: world X reached the event point, and it has not fired
    ; yet. Without the one-shot guard the walk would re-trigger on its first
    ; frame after the restore, since the player is already past it.
    lda z:US_G_EVENT_DONE
    bne @done
    lda z:US_G_WORLDX
    cmp #MET_TRIGGER_X
    bcc @done
    lda #1
    sta z:US_G_EVENT_DONE
    lda #MET_ST_FREEZE
    sta z:US_G_STATE
    stz z:US_G_TIMER
    lda z:US_G_CAMX
    sta z:US_G_FROZEN_CAMX          ; the capture reads the FROZEN view
@done:
    .a16
    .i16
    rts

; --- FREEZE: input GATED; the frozen frame held so it is observable --------
; play_input is simply not called — the whole of the gate, and the thing a
; no-freeze control build would compile back IN to prove the test non-vacuous.
do_freeze:
    .a16
    .i16
    jsr camera_commit               ; the same camera, re-committed: frozen
    jsr draw_player
    lda z:US_G_TIMER
    inc a
    sta z:US_G_TIMER
    cmp #MET_FREEZE_HOLD
    bcc @done
    lda #MET_ST_CAPTURE
    sta z:US_G_STATE
    stz z:US_G_TIMER
@done:
    .a16
    .i16
    rts

; --- CAPTURE: emit the blocks, then black the BG a frame later, then swap ---
; THE TWO STEPS ARE ONE FRAME APART, AND MEASURED. The OAM shadow a tick
; writes is DMA'd by that frame's VBlank and therefore appears in the NEXT
; frame's picture, while the TM write lands mid-frame in the tick's own. Doing
; both in one tick leaves a single frame with the BG already gone and the
; blocks not yet committed — measured on the emulator as a 9,216-pixel black
; hole exactly the size of the level's green. Emitting at timer 0 and blacking
; at timer 1 closes it, and turns the capture's claim into something a test can
; state as an equality: every frame from the last FREEZE frame onward is
; pixel-IDENTICAL, because the sprites land on the pixels the BG vacated.
do_capture:
    .a16
    .i16
    lda z:US_G_TIMER
    bne @maybe_black
    jsr capture_emit                ; ONE pass; the blocks then stand
    bra @hold
@maybe_black:
    .a16
    .i16
    cmp #1
    bne @hold
    jsr bg_black                    ; TM = OBJ only — the BG goes away
@hold:
    .a16
    .i16
    lda z:US_G_TIMER
    inc a
    sta z:US_G_TIMER
    cmp #MET_CAPTURE_HOLD
    bcc @done
    ; ---- ask scene_mgr for the swap. From here the phase machine owns the
    ; frame: forced blank, exit + enter (32 KB of Mode-7 plane under it), and
    ; straight back to full brightness. Our tick is not called again until
    ; `impact` is running.
    ;
    ; SM_SWITCH, not a hand-written id + entry point: it takes BOTH from the
    ; `[[edge]]` in game.toml through the allocator's emitted symbols, so the
    ; declared style IS the path this takes and the scene id cannot drift from
    ; the manifest order.
    sep #$20
    .a8
    SM_SWITCH "LEVEL", "IMPACT"
    rep #$20
    .a16
@done:
    .a16
    .i16
    rts

; =============================================================================
; helpers
; =============================================================================
; --- play_input: D-pad RIGHT advances the player's world X ----------------
; In/out: A16/I16, DB=0. Clobbers A.
play_input:
    .a16
    .i16
    lda z:ES_INP_CUR
    and #MET_JOY_RIGHT
    beq @done
    lda z:US_G_WORLDX
    clc
    adc #MET_WALK_SPEED
    sta z:US_G_WORLDX
@done:
    .a16
    .i16
    rts

; --- camera_commit: the camera, through m7_affine's owned API -------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; This rail does not claim BG1HOFS: `m7_affine` is global here and its NMI
; commit writes $210D/$210E every frame in every scene (they are BG1HOFS/
; BG1VOFS in Mode 1 and M7HOFS/M7VOFS in Mode 7 — one port under one name).
; So the camera is set by calling that feature's own `m7a_set_center`, which
; writes the origin as pivot minus half a screen: passing (camx + 128, 111)
; gives HOFS = camx and VOFS = -1.
;
; VOFS = -1 rather than 0 is the BGnVOFS off-by-one: the register names the
; line ABOVE the first displayed one, so 0 would shift the level up a pixel
; and the ground band would end at y 222 instead of 223 — which the capture,
; drawing at row*8 exactly, would then not match. pfs_bg and maze_bg carry the
; same measured -1.
camera_commit:
    .a16
    .i16
    lda z:US_G_CAMX
    clc
    adc #128                        ; half of the 256 active pixels
    tax
    ldy #111                        ; half of 224 active scanlines, minus one
    jsr ::m7a_set_center
    rts

; --- draw_player: slot 0, at its fixed screen position --------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
draw_player:
    .a16
    .i16
    lda #MET_PLAYER_SCRN_X
    sta z:ES_MET_DRAW + MET_D_X
    lda #MET_PLAYER_Y
    sta z:ES_MET_DRAW + MET_D_Y
    stz z:ES_MET_DRAW + MET_D_SIZE  ; 16x16: the SMALL half of OBSEL pair 3
    ldx #(ES_O_PLAYER * 4)
    lda #(MET_T_PLAYER | (MET_PRIO << 8))
    jsr ::met_put
    rts

; --- bg_black: drop BG1 from TM so only the captured OBJ remains ----------
; In/out: A16/I16, DB=0. Clobbers A.
;
; TM is met_bg's register, opened to this scene by its `scene_writes`. This is
; the write that makes the capture VISIBLE as a capture: the instant the BG
; goes, the ground is still there, on the same pixels, made of sprites.
;
; WIDTH-RISK: toggles A8 for the one byte store and restores A16.
bg_black:
    .a16
    .i16
    sep #$20
    .a8
    lda #MET_TM_OBJ
    sta a:$212C                     ; TM: OBJ only (BG1 dropped)
    rep #$20
    .a16
    rts

; =============================================================================
; capture_emit — THE CRUX: the visible BG platforms, as OBJ
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Screen pixel x shows world pixel (frozen_camx + x), and the BG1 tilemap is
; 32 columns wide and WRAPS every 256 px. So screen block column `sc` reads
; tilemap column ((frozen_camx >> 3) + sc) & 31 and the block draws at
; x = sc*8 - (frozen_camx & 7) — exactly the pixels that tile occupied, at any
; camera position, wrap included.
;
; THE BOUND IS THE CLAIM. The emit cursor is compared against
; ES_O_CAPTURE_SPRITES before every write, so the loop physically cannot reach
; a slot met_obj did not claim. The bound is 40 (met_obj's feature.toml derives
; it from this level's geometry); the shipped path emits 38.
capture_emit:
    .a16
    .i16
    jsr ::met_hi_clear              ; rebuild all eleven hi bytes this pass
    jsr draw_player                 ; slot 0 first: its hi bits were just cleared
    stz z:US_CAP_N
    ; leftmost on-screen tilemap column, and the sub-tile remainder
    lda z:US_G_FROZEN_CAMX
    .repeat 3
        lsr
    .endrepeat
    sta z:US_CAP_BASECOL
    lda z:US_G_FROZEN_CAMX
    and #7
    sta z:US_CAP_SUBX
    stz z:US_CAP_ROW
@rowloop:
    .a16
    .i16
    ldx z:US_CAP_ROW
    lda f:cand_rows, x
    and #$00FF
    cmp #$00FF
    beq @rows_done
    inx                             ; the table is one byte per entry
    stx z:US_CAP_ROW
    pha                             ; the row number
    .repeat 6
        asl                         ; row * 32 words * 2 bytes = the row's
    .endrepeat                      ;   byte offset into the shadow
    sta z:US_CAP_ROWBASE
    pla
    .repeat 3
        asl                         ; row * 8 = the screen y
    .endrepeat
    sta z:US_CAP_SY
    stz z:US_CAP_SC
@colloop:
    .a16
    .i16
    ; ---- screen x for this block column -----------------------------------
    lda z:US_CAP_SC
    .repeat 3
        asl                         ; sc * 8
    .endrepeat
    sec
    sbc z:US_CAP_SUBX
    sta z:US_CAP_SX
    bmi @onscreen                   ; negative: off the LEFT edge, still visible
    cmp #(1 << 8)
    bcs @nextcol                    ; at or past x 256: fully off the right
@onscreen:
    .a16
    .i16
    ; ---- the tilemap word this block would cover --------------------------
    lda z:US_CAP_BASECOL
    clc
    adc z:US_CAP_SC
    and #MET_COL_MASK               ; wrap to the 32-column row
    asl                             ; * 2 (word table)
    clc
    adc z:US_CAP_ROWBASE
    tax
    lda a:ES_BG_SHADOW, x           ; what the PPU is displaying, read back
    and #((1 << 10) - 1)            ; the CHR index (low 10 bits of the word)
    cmp #MET_BG_PLAT
    bne @nextcol                    ; not a platform cell -> capture nothing
    ; ---- the declared bound, checked before the write ---------------------
    lda z:US_CAP_N
    cmp #ES_O_CAPTURE_SPRITES
    bcs @rows_done                  ; the claim is full: stop, never overrun
    ; ---- emit the 16x16 block where that BG tile rendered -----------------
    lda z:US_CAP_SX
    sta z:ES_MET_DRAW + MET_D_X
    lda z:US_CAP_SY
    sta z:ES_MET_DRAW + MET_D_Y
    stz z:ES_MET_DRAW + MET_D_SIZE  ; 16x16: OBSEL pair 3's SMALL half
    lda z:US_CAP_N
    clc
    adc #ES_O_CAPTURE
    asl
    asl                             ; slot * 4 = the shadow byte offset
    tax
    lda #(MET_T_BLOCK | (MET_PRIO << 8))
    jsr ::met_put
    lda z:US_CAP_N
    inc a
    sta z:US_CAP_N
@nextcol:
    .a16
    .i16
    lda z:US_CAP_SC
    clc
    adc #CAP_COL_STEP
    sta z:US_CAP_SC
    cmp #CAP_COL_END
    bcc @colloop
    bra @rowloop
@rows_done:
    .a16
    .i16
    rts

.endscope
