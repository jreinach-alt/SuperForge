; =============================================================================
; m7x_town.asm — the Mode 1 town interior: one room, computed, walked
; =============================================================================
; A single-screen 32x32 room: a plank floor framed by stone walls, a 2x2 table,
; and an exit door in the bottom wall. The camera is FIXED and the SPRITE
; moves, which is the exact inverse of the overworld's model — there she is
; pinned at the affine pivot and the floor is what moves.
;
; THE ROOM IS COMPUTED, NOT STORED, and that is the feature's one real idea.
; `town_classify` answers "what is at (tx,ty)" and its answer IS the BG1 tile
; id — FLOOR 0, WALL 1, DOOR 2, TABLE 3 — so the same routine both DRAWS the
; room (town_build_map walks 32x32 and writes each class straight into the
; tilemap) and BLOCKS the walk (town_step tests the destination's class). There
; is no tilemap blob and no collision table, therefore nothing that can drift
; from what is on screen. It is the same economy m7x_rom records for the
; overworld ("the tilemap is the SINGLE SOURCE OF TRUTH for terrain"), one
; level further in: here even the tilemap is derived.
;
; The room rectangle, the door and table positions, the spawn, the classify
; ordering and the edge-triggered walk are all constants of this scene. Every
; address is an emitted symbol, because `no_literals` refuses anything else,
; and the tile ids come from the generator's own m7x_world.inc rather than
; being transcribed.
;
; WHAT THIS FEATURE DOES NOT UPLOAD, deliberately: the avatar's OBJ CHR and its
; OBJ palette. M7x_obj put them at VRAM $4000 / CGRAM 128 when the overworld
; entered, and the mosaic wipe is not a scene reload — it leaves them standing,
; which is the same property that lets the Mode 7 image survive at $0000-$3FFF.
; See this directory's feature.toml for why they are inherited rather than
; claimed.

; --- the room, in tiles -----------------------------------------------------
; A 32x32 tilemap on a 256x224 screen shows 32x28 of it; the room rectangle is
; inside that, so the bottom four rows are never seen and are wall by the
; outside-the-rectangle rule.
TOWN_ROOM_X0 = 2
TOWN_ROOM_X1 = 29
TOWN_ROOM_Y0 = 1
TOWN_ROOM_Y1 = 26

; The exit door: a gap IN the bottom wall. Stepping onto it is what arms the
; wipe back to the overworld, which is why classify tests it FIRST — it sits on
; the wall rectangle's border and the border rule would otherwise claim it.
TOWN_DOOR_TX = 15
TOWN_DOOR_TY = 26

; A 2x2 table in the upper room. Blocked, and blocked by the same class test
; the walls use — there is no second kind of obstacle.
TOWN_TABLE_X0 = 13
TOWN_TABLE_X1 = 14
TOWN_TABLE_Y0 = 10
TOWN_TABLE_Y1 = 11

; Where she arrives: a few tiles above the door, facing away from it, so the
; first thing on screen is the room rather than the way out.
TOWN_SPAWN_TX = 15
TOWN_SPAWN_TY = 22

; --- the classes, which ARE the tile ids ------------------------------------
; Bound to the generator's emitted ids rather than restated, and ASSERTED so a
; re-authored tileset that reorders them stops the build here instead of
; drawing a room made of the wrong four textures.
TOWN_CLS_FLOOR = M7X_TOWN_TILE_FLOOR
TOWN_CLS_WALL  = M7X_TOWN_TILE_WALL
TOWN_CLS_DOOR  = M7X_TOWN_TILE_DOOR
TOWN_CLS_TABLE = M7X_TOWN_TILE_TABLE
.assert TOWN_CLS_FLOOR = 0, error, "m7x_town: the floor class must be tile id 0 — a BG1 tilemap word of 0 is the cell this room fills with, and CGRAM word 0 is the floor base that also serves as the backdrop"
.assert (TOWN_CLS_WALL | TOWN_CLS_DOOR | TOWN_CLS_TABLE) < ES_V_TOWN_CHR_WORDS / 16, error, "m7x_town: a class id is outside the uploaded tile set"

; --- the tilemap the room is drawn into -------------------------------------
TOWN_MAP_W = 32
TOWN_MAP_H = 32
.assert TOWN_MAP_W * TOWN_MAP_H = ES_V_TOWN_MAP_WORDS, error, "m7x_town: the room's 32x32 sweep disagrees with the tilemap claim's size"

; --- the classifier's call frame (the town_cell claim) ----------------------
TOWN_CTX = ES_TOWN_CELL + 0
TOWN_CTY = ES_TOWN_CELL + 2

; --- the avatar -------------------------------------------------------------
; The SAME three authored facings the overworld walks — the sheet is inherited,
; not re-uploaded — so the tile ids come from the generator's constants and
; LEFT is SIDE H-flipped through the attribute bit, exactly as m7x_obj does it.
; Those constants are duplicated here rather than reached for across the scene
; boundary: m7x_obj lives inside the `overworld` scope and is not composed in
; this scene at all, so there is nothing to share with.
TOWN_OBJ_PRIO  = $20                ; priority 2, m7x_obj's byte
TOWN_OBJ_PAL   = $00                ; OBJ palette 0, at CGRAM 128
TOWN_OBJ_HFLIP = $40
TOWN_OBJ_LARGE = 2                  ; hi-table size bit: OBSEL pair 0's large = 16x16
TOWN_TILE_PX   = 8                  ; the room's grid, and the sprite's step

; The facing codes, m7x_obj's — one sheet, two scenes, one vocabulary.
TOWN_FACE_DOWN  = 0
TOWN_FACE_UP    = 1
TOWN_FACE_LEFT  = 2
TOWN_FACE_RIGHT = 3

; The hi table is the last 32 bytes of the OAM shadow, after the 128 four-byte
; low entries. Derived from the claim's own size, so a re-sized shadow moves
; it.
TOWN_HI_BASE = ES_OAM_SHADOW + ES_OAM_SHADOW_SIZE - 32
TOWN_HI_BYTE = TOWN_HI_BASE + (ES_O_TOWN_AVATAR / 4)
TOWN_PARK_Y  = $F0                  ; below the screen — where the pad slots live

; --- the pad ----------------------------------------------------------------
; D-PAD ONLY, read on the EDGE (ES_INP_PRESS) rather than at level: one press
; is one tile. That is the deliberate difference from the overworld, where a
; held direction walks — indoors a room is 27 tiles across and a level read
; would cross it in half a second.
;
; Bit POSITIONS, not hex: `no_literals` reads a bare $0200 as an address,
; because it is one.
TOWN_JOY_RIGHT = 1 << 8
TOWN_JOY_LEFT  = 1 << 9
TOWN_JOY_DOWN  = 1 << 10
TOWN_JOY_UP    = 1 << 11

; =============================================================================
; ARMING — once, when the wipe's swap brings the interior in
; =============================================================================
; CONTRACT town_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the interior's CHR, tilemap and palette uploaded and its
;             registers written
;   clobbers: A, X, Y, N, Z, and the classifier's call frame
;   assumes:  FORCED BLANK must already be on screen and the NMI must be
;             masked — this is a mid-scene swap, not a scene enter, so the
;             caller establishes both
;   tail:     rts
;
; --- town_arm: the whole interior ------------------------------------------
; masked — the caller (game/mode7_explore/scenes/town.asm, through main.asm's
; swap service) guarantees both, and the guarantee is load-bearing twice over:
; the 1,024 CPU-side tilemap writes below take far longer than one frame, and
; an NMI landing inside them would set VMADD for the OAM/affine commits and
; drop the rest of the sweep at whatever addresses followed.
;
town_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "town_arm"
    jsr town_upload_chr             ; 4 tiles -> VRAM word $5000
    jsr town_upload_pal             ; 16 words -> CGRAM 0..15 (over the world's)
    jsr town_build_map              ; 32x32 classes -> VRAM word $5800
    ; ---- the layer configuration this feature owns ------------------------
    ; The encodings are the ALLOCATOR's, emitted from the two pinned vram
    ; claims. Narrating $58 and $05 here would be narrating the claim a second
    ; time, and the second copy is the one that goes stale.
    sep #$20
    .a8
    lda #ES_V_TOWN_MAP_SC_BASE
    sta a:$2107                     ; BG1SC: 32x32 map at the claimed base
    lda #ES_V_TOWN_CHR_NBA
    sta a:$210B                     ; BG12NBA: BG1 chr base in the low nibble
    rep #$20
    .a16
    rts

; --- town_upload_chr: the four interior tiles -------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; A CPU loop, not a DMA: 128 bytes is 64 word stores, and a dma_init claim plus
; its channel programming costs more to set up than the transfer saves. The
; same call this feature's siblings make for their palettes.
town_upload_chr:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the $2119 write
    rep #$20
    .a16
    lda #ES_V_TOWN_CHR
    sta a:$2116                     ; VMADD = the claim's base word
    ldx #0
@lp:
    .a16
    .i16
    lda f:m7x_town_chr_bin, x
    sta a:$2118                     ; a 16-bit store drives VMDATAL then VMDATAH
    inx
    inx
    cpx #ES_R_M7X_TOWN_CHR_SIZE
    bcc @lp
    rts

; --- town_upload_pal: the interior palette ----------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; THIS IS THE ONE THING THE VISIT DESTROYS. CGRAM 0..11 is the overworld's
; twelve-colour Mode 7 palette (m7x_floor pins it at 0 because an 8bpp Mode 7
; pixel value is an ABSOLUTE CGRAM index); sixteen words of interior land on
; top of it. The return re-stages it — see m7x_floor's floor_restage — and a
; return that forgot would put the world back in the town's browns.
;
; CGADD auto-increments and this build takes low byte then high byte per word,
; so the loop is a byte walk over the blob.
town_upload_pal:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_C_TOWN_PAL
    sta a:$2121                     ; CGADD = the claim's base word (0)
    rep #$20
    .a16
    ldx #0
@lp:
    .a16
    .i16
    lda f:m7x_town_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_M7X_TOWN_PAL_SIZE
    bcc @lp
    rts

; --- town_build_map: draw the room straight into VRAM -----------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y and the classifier's call frame.
;
; 32x32 cells, each one `town_classify` and one word store. The class IS the
; tilemap word: palette 0, priority 0, no flip, so the whole word is the tile
; id and there is nothing to OR in. Under forced blank with NMI masked
; (town_arm's contract) this is free to take as long as it takes — measured
; against nothing, because it happens once per visit inside a black frame.
;
; No staging buffer and no DMA: a WRAM buffer would be 2 KB of claim to hold
; bytes that are computed once and never read again.
town_build_map:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_TOWN_MAP
    sta a:$2116                     ; VMADD = the claim's base word
    stz z:TOWN_CTY
@rows:
    .a16
    .i16
    stz z:TOWN_CTX
@cols:
    .a16
    .i16
    jsr town_classify               ; A = the class, which IS the tile id
    sta a:$2118                     ; tilemap word; VMADD++
    lda z:TOWN_CTX
    inc
    sta z:TOWN_CTX
    cmp #TOWN_MAP_W
    bcc @cols
    lda z:TOWN_CTY
    inc
    sta z:TOWN_CTY
    cmp #TOWN_MAP_H
    bcc @rows
    rts

; =============================================================================
; THE ROOM ITSELF
; =============================================================================
; --- town_classify: what is at (TOWN_CTX, TOWN_CTY)? ------------------------
; In: A16/I16, DB=0. The cell in the call frame. Out: A16/I16. A = the class,
; 0..3, which is also the BG1 tile id. Clobbers A.
;
; THE ORDER OF THE FOUR TESTS IS THE ROOM'S DEFINITION, and each one is where
; it is for a reason:
;
;  1. THE DOOR FIRST. It sits IN the bottom wall — on the rectangle's border —
;  so the border rule below would claim it and the room would have no exit.
;  2. Outside the rectangle -> wall. This is what makes the four rows the
;  screen never shows, and the two columns beyond it, solid rather than
;  undefined: every one of the 1,024 cells gets an answer.
;  3. On the rectangle's border -> wall. The frame.
;  4. Inside the 2x2 table box -> table. Everything else is floor.
town_classify:
    .a16
    .i16
    lda z:TOWN_CTX
    cmp #TOWN_DOOR_TX
    bne @not_door
    lda z:TOWN_CTY
    cmp #TOWN_DOOR_TY
    bne @not_door
    lda #TOWN_CLS_DOOR
    rts
@not_door:
    .a16
    .i16
    ; ---- outside the room rectangle -> wall ------------------------------
    ; Unsigned compares throughout, which also covers the underflow arm: a
    ; coordinate that went below zero wrapped to $FFxx, which is above the max.
    lda z:TOWN_CTX
    cmp #TOWN_ROOM_X0
    bcc @wall
    cmp #(TOWN_ROOM_X1 + 1)
    bcs @wall
    lda z:TOWN_CTY
    cmp #TOWN_ROOM_Y0
    bcc @wall
    cmp #(TOWN_ROOM_Y1 + 1)
    bcs @wall
    ; ---- on the rectangle's border -> wall -------------------------------
    lda z:TOWN_CTX
    cmp #TOWN_ROOM_X0
    beq @wall
    cmp #TOWN_ROOM_X1
    beq @wall
    lda z:TOWN_CTY
    cmp #TOWN_ROOM_Y0
    beq @wall
    cmp #TOWN_ROOM_Y1
    beq @wall
    ; ---- the 2x2 table -> table (blocked) --------------------------------
    lda z:TOWN_CTX
    cmp #TOWN_TABLE_X0
    bcc @floor
    cmp #(TOWN_TABLE_X1 + 1)
    bcs @floor
    lda z:TOWN_CTY
    cmp #TOWN_TABLE_Y0
    bcc @floor
    cmp #(TOWN_TABLE_Y1 + 1)
    bcs @floor
    lda #TOWN_CLS_TABLE
    rts
@floor:
    .a16
    .i16
    lda #TOWN_CLS_FLOOR
    rts
@wall:
    .a16
    .i16
    lda #TOWN_CLS_WALL
    rts

; =============================================================================
; THE FRAME
; =============================================================================
; CONTRACT town_spawn
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the walker placed at the interior's spawn tile
;   clobbers: A, N, Z
;   assumes:  town_arm has already run
;   tail:     rts
;
; --- town_spawn: seed the avatar --------------------------------------------
;
; Power-on DP is random and these three words carry no `[init] zero` (rule 5):
; this IS their write-before-read contract, and it runs inside the swap, before
; the first town frame reads any of them.
town_spawn:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "town_spawn"
    lda #TOWN_SPAWN_TX
    sta z:US_TOWN_TX
    lda #TOWN_SPAWN_TY
    sta z:US_TOWN_TY
    lda #TOWN_FACE_UP
    sta z:US_TOWN_FACING
    rts

; --- town_step: one grid step per D-pad PRESS -------------------------------
; CONTRACT town_step
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one grid step attempted. A = 1 if she left the building, 0
;             otherwise
;   clobbers: A, X, Y, N, Z, V, and the call frame
;   assumes:  once per frame from the scene tick, during active display,
;             while the interior is up
;   tail:     rts
;
; is now standing ON THE DOOR, else 0.
;
; PRIORITY L, R, U, D with NO fall-through, which is the other deliberate
; difference from the overworld. There a blocked axis falls through so a held
; diagonal slides along a wall; here input is edge-triggered and a press is one
; discrete step, so a blocked press is simply refused — falling through would
; turn one press into a move in a direction the player did not press.
;
; The facing is latched BEFORE the move is tested, so she turns to face a wall
; she cannot walk into. Same feedback, same reason, as the overworld's.
town_step:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "town_step"
    lda z:ES_INP_PRESS
    bit #TOWN_JOY_LEFT
    beq @chk_right
    lda #TOWN_FACE_LEFT
    sta z:US_TOWN_FACING
    ldx #$FFFF
    ldy #0
    bra @try
@chk_right:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #TOWN_JOY_RIGHT
    beq @chk_up
    lda #TOWN_FACE_RIGHT
    sta z:US_TOWN_FACING
    ldx #1
    ldy #0
    bra @try
@chk_up:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #TOWN_JOY_UP
    beq @chk_down
    lda #TOWN_FACE_UP
    sta z:US_TOWN_FACING
    ldx #0
    ldy #$FFFF
    bra @try
@chk_down:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #TOWN_JOY_DOWN
    beq @none
    lda #TOWN_FACE_DOWN
    sta z:US_TOWN_FACING
    ldx #0
    ldy #1
@try:
    .a16
    .i16
    jsr town_try_step
    rts
@none:
    .a16
    .i16
    lda #0
    rts

; --- town_try_step: move by (X=dx, Y=dy) if the destination lets her --------
; In: A16/I16, DB=0. X, Y = signed tile deltas, each -1 / 0 / +1. Out: A16/I16.
; A = 1 if the committed cell is the DOOR, else 0. Clobbers A, X, Y and the
; call frame.
;
; WALL and TABLE refuse; FLOOR and DOOR commit. The door is walkable ON PURPOSE
; — she steps onto it and the wipe takes her out from there, so the frame the
; dissolve starts on has her standing in the doorway rather than beside it.
town_try_step:
    .a16
    .i16
    txa
    clc
    adc z:US_TOWN_TX
    sta z:TOWN_CTX
    tya
    clc
    adc z:US_TOWN_TY
    sta z:TOWN_CTY
    jsr town_classify
    cmp #TOWN_CLS_WALL
    beq @blocked
    cmp #TOWN_CLS_TABLE
    beq @blocked
    ; ---- walkable: commit ------------------------------------------------
    lda z:TOWN_CTX
    sta z:US_TOWN_TX
    lda z:TOWN_CTY
    sta z:US_TOWN_TY
    cmp #TOWN_DOOR_TY               ; the call frame still holds the cell, so
    bne @not_exit                   ;   re-ask it cheaply: door == (DOOR_TX,
    lda z:TOWN_CTX                  ;   DOOR_TY) and nothing else classifies
    cmp #TOWN_DOOR_TX               ;   DOOR (classify tests it first)
    bne @not_exit
    lda #1
    rts
@not_exit:
    .a16
    .i16
    lda #0
    rts
@blocked:
    .a16
    .i16
    lda #0
    rts

; --- town_draw: the avatar at her tile --------------------------------------
; CONTRACT town_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the interior's cast staged into the OAM shadow
;   clobbers: A, X, N, Z, C
;   assumes:  once per frame from the scene tick, during active display
;   tail:     rts
;
; The camera is fixed at scroll 0, so screen position is tile * 8 and there is
; no projection to do. One OAM entry into the oam_sprites shadow; hardware OAM
; belongs to that feature's declared VBlank DMA.
;
; THE HI TABLE IS REBUILT WHOLE, NEVER PATCHED — m7x_obj's rule, and the reason
; this feature claims the other three slots of the quad. X9 is clear by
; construction: the room is 30 tiles wide inside its walls, so the largest
; screen x is 232.
;
; WIDTH-RISK: A16/I16 throughout except the hi-table byte, bracketed by `sep
; #$20` / `rep #$20`. I-width is never touched.
town_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "town_draw"
    ; ---- facing -> (tile, attr), through the word LUT ---------------------
    ; Masked to 0..3 before `tax`, so I16's transfer of the full 16-bit C
    ; register cannot carry a stray high byte into X.
    lda z:US_TOWN_FACING
    and #3
    asl
    tax
    lda f:town_tile_lut, x
    sta a:ES_OAM_SHADOW + (ES_O_TOWN_AVATAR * 4) + 2   ; bytes 2,3: tile + attr
    ; ---- the entry's x and y, in one store --------------------------------
    lda z:US_TOWN_TY
    .repeat 3
        asl                         ; tile -> px (TOWN_TILE_PX = 8)
    .endrepeat
    xba
    and #$FF00                      ; byte 1 = y
    sta z:TOWN_CTY                  ; the call frame, borrowed as a temp
    lda z:US_TOWN_TX
    .repeat 3
        asl
    .endrepeat
    and #$00FF                      ; byte 0 = x
    ora z:TOWN_CTY
    sta a:ES_OAM_SHADOW + (ES_O_TOWN_AVATAR * 4) + 0
    sep #$20
    .a8
    lda #TOWN_OBJ_LARGE
    sta a:TOWN_HI_BYTE              ; size = 16x16; X9 and the pad slots zero
    rep #$20
    .a16
    rts

; --- town_park: every slot this feature owns, off the bottom of the screen ---
; CONTRACT town_park
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the interior's slots parked off screen
;   clobbers: A, X, N, Z, C
;   assumes:  the exit path, before the overworld is restaged
;   tail:     rts
;
; OBJ HAS NO HARDWARE MOSAIC. $2106 pixelates BG layers only, so an unparked
; sprite floats un-dissolved over a dissolving room and the wipe reads as
; broken. Dropping OBJ from TM is the obvious fix, but TM has one owner per
; scene and mosaic cannot be it (that feature.toml's COMPOSITION ANSWER 2), so
; the consumer parks the OAM — which is also the form that works
; on the HDMA-TM scenes where the TM drop is defeated per scanline anyway.
; Called at the moment the exit wipe is armed, and again by the scene's own
; park.
town_park:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "town_park"
    ldx #(ES_O_TOWN_AVATAR * 4)
@loop:
    .a16
    .i16
    lda #(TOWN_PARK_Y << 8)
    sta a:ES_OAM_SHADOW + 0, x      ; x = 0, y = parked
    stz a:ES_OAM_SHADOW + 2, x      ; tile 0, attr 0
    inx
    inx
    inx
    inx
    cpx #((ES_O_TOWN_HI_PAD + ES_O_TOWN_HI_PAD_SPRITES) * 4)
    bcc @loop
    sep #$20
    .a8
    stz a:TOWN_HI_BYTE              ; small + X9 clear, as oam_park_all left it
    rep #$20
    .a16
    rts

; --- facing -> tile | (attr << 8) -------------------------------------------
; One word per facing, in the exact shape the OAM entry's bytes 2 and 3 want.
; The tile ids are the generator's, and LEFT reuses the SIDE profile's CHR with
; the H-flip bit set — the same three-facing sheet the overworld walks, still
; in VRAM because the wipe is not a scene reload.
town_tile_lut:
    .word M7X_AVATAR_TILE_DOWN | ((TOWN_OBJ_PRIO | TOWN_OBJ_PAL) << 8)
    .word M7X_AVATAR_TILE_UP   | ((TOWN_OBJ_PRIO | TOWN_OBJ_PAL) << 8)
    .word M7X_AVATAR_TILE_SIDE | ((TOWN_OBJ_PRIO | TOWN_OBJ_PAL | TOWN_OBJ_HFLIP) << 8)
    .word M7X_AVATAR_TILE_SIDE | ((TOWN_OBJ_PRIO | TOWN_OBJ_PAL) << 8)
