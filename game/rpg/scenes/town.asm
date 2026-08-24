; =============================================================================
; scenes/town.asm — the Mode 1 town, and the dialog box that debuts here
; =============================================================================
; A walled cobbled plaza on BG1, an avatar that walks the 32x32 grid one tile
; per press, a villager who talks, a save point that writes battery SRAM, and a
; south gate that wipes back out to the overworld at the tile you left.
;
; THIS IS WHERE `dialog` DEBUTS, and the scene is why the panel is on BG3 rather
; than anywhere else: BG3 does not exist in Mode 7, so the overworld has no
; layer to put a message window on — a Mode 7 rail that wants text has to draw
; it with sprites. Here bg_text owns BG3's layer registers and `dialog` owns
; the panel's own CHR page, palette, buffer and commit; that split is what lets
; both live on one layer, and dialog/feature.toml argues it.
;
; Collision reads the TILEMAP BLOB IN ROM — the same bytes the PPU draws, so
; what is drawn IS what blocks, with no shadow to keep synchronised.

.scope town

.include "engine_state_town.inc"        ; GENERATED — this scene's map
.include "rpg_town.asm"
.include "rpg_obj.asm"

; --- dialog's binding contract: seven symbols, no defaults ------------------
; A wide bottom window framing three text lines: col 2, row 18, 28 x 9 cells.
; DLG_BG3_CHR is what makes the reach assert real — it is the base this scene
; actually programs into BG34NBA, so the assert
; compares the panel's page against the register the PPU will use, not against
; an assumption. `::`-qualified where the symbol is the game's, because ca65
; defers an unqualified parent-scope lookup from inside a scope.
DLG_COL = 2
DLG_ROW = 18
DLG_W = 28
DLG_H = 9
DLG_BG3_CHR = ES_V_TEXT_CHR
DLG_MAP = ES_V_TEXT_MAP
DLG_TEXT_ATTR = ((ES_C_TEXT_PAL / 4) << 10) | (1 << 13)
.include "dialog.asm"

; The blank BG3 cell this scene clears to, and the panel restores to: tile 0 of
; the font page is SPACE, so the attr word alone IS the blank.
TEXT_BLANK_W = DLG_TEXT_ATTR

BGMODE_TOWN = 9                 ; Mode 1 with BG3 PRIORITY HIGH — the bit that
                                ;   lifts a priority-flagged BG3 tile above
                                ;   BG1/BG2/OBJ, which is what makes the panel
                                ;   opaque OVER the room rather than under it
TM_TOWN = ::TM_BG1 | ::TM_BG3 | ::TM_OBJ

; --- resume: the whole interior, from a wipe or from the dispatch table -----
; In/out: A16/I16, DB=0, forced blank + NMI masked. Clobbers A, X, Y.
resume:
    .a16
    .i16
    jsr rpgt_arm                    ; CHR + tilemap + palette + BG1 bases
    jsr arm_text                    ; BG3 bases + the font + a cleared map
    jsr dialog_init                 ; the panel is CLOSED and owes no commit.
                                    ;   Called HERE rather than in the boot
                                    ;   block because dlg_ctl is SCENE DP: the
                                    ;   NMI hook only commits while this scene
                                    ;   is current, and this scene is only
                                    ;   current after this routine has run — so
                                    ;   nothing reads either byte before it is
                                    ;   written. (The class of bug is a byte
                                    ;   read before the frame that gives it
                                    ;   meaning; the fix is the DP scope.)
    jsr dialog_upload               ; the nine-patch + the panel palette, from
                                    ;   dialog's OWN dlg_rom dependency — no
                                    ;   source arguments to get wrong
    jsr rpgo_arm                    ; OBJ CHR + palette + OBSEL
    inc a:::US_VISITS               ; a visit, counted before the save can stage
    jsr draw_actors
    sep #$20
    .a8
    lda #BGMODE_TOWN
    sta a:$2105
    lda #TM_TOWN
    sta a:$212C
    stz z:ES_SM_NMI + 2             ; HDMAEN shadow: no HDMA in this scene
    stz z:::RPG_TOWN_REP            ; throttle idle on entry, so the first
                                    ;   held step after a wipe is immediate, not
                                    ;   delayed by a leftover count from last visit
    stz z:::RPG_TOWN_FLARE          ; no flare in flight across a wipe
    rep #$20
    .a16
    rts

; --- arm_text: BG3's bases, the 96-glyph font, and a cleared tilemap --------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; The two base encodings are the ALLOCATOR's (`_SC_BASE` / `_NBA`), never a
; hand-narrated VRAM address — AGENTS.md's rule, and the reason the panel's
; reach assert can trust DLG_BG3_CHR.
arm_text:
    .a16
    .i16
    sep #$20
    .a8
    lda #ES_V_TEXT_MAP_SC_BASE
    sta a:$2109                     ; BG3SC: 32x32 at bg_text's tilemap claim
    lda #ES_V_TEXT_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 chr = text_chr's page
    stz a:$2111
    stz a:$2111                     ; BG3HOFS (write-twice)
    stz a:$2112
    stz a:$2112                     ; BG3VOFS
    ; ---- the BG3 text palette, CPU-side ----------------------------------
    ; bg_text CLAIMS these four words (text_pal, pinned at 28 by the hardware
    ; contract) but uploads nothing into them — text_upload_font moves CHR only.
    ; Nothing else in the composition writes CGRAM 28..31 either, so without
    ; this the glyphs render in POWER-ON GARBAGE. The emulator found it: the
    ; tilemap read back perfectly ('W','E','L','C','O','M','E' at row 19) while
    ; the panel showed coloured blocks, which is exactly the shape of a correct
    ; tilemap over an unwritten palette. Rule 5: every byte the feature reads is
    ; a byte something wrote.
    lda #ES_C_TEXT_PAL
    sta a:$2121                     ; CGADD = bg_text's claim base
    stz a:$2122
    stz a:$2122                     ; 0: transparent (no glyph pixel uses it)
    lda #255
    sta a:$2122
    lda #127
    sta a:$2122                     ; 1: white  ($7FFF)
    lda #255
    sta a:$2122
    lda #127
    sta a:$2122                     ; 2: white
    lda #255
    sta a:$2122
    lda #127
    sta a:$2122                     ; 3: white
    lda #ES_R_FONT_BIN_BANK
    rep #$20
    .a16
    ldx #ES_V_TEXT_CHR
    ldy #ES_R_FONT_BIN_ADDR
    jsr ::text_upload_font
    ldx #ES_V_TEXT_MAP
    ldy #ES_V_TEXT_MAP_WORDS
    lda #TEXT_BLANK_W
    jsr ::text_clear_map
    rts

; --- tick: one town frame ---------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; FROZEN WHILE A WIPE IS IN FLIGHT, in both directions, and the actors are
; PARKED on the OUT phase: OBJ has no hardware mosaic, so an unparked sprite
; floats un-dissolved over a dissolving room. mosaic cannot do that itself (TM
; has one owner per scene and it is rpg_town), so it is the caller's, which is
; what mosaic's feature.toml states.
tick:
    .a16
    .i16
    sep #$20
    .a8
    jsr ::mosaic_active
    cmp #::MOS_OUT
    rep #$20
    .a16
    beq @dissolving_out
    sep #$20
    .a8
    jsr ::mosaic_active
    rep #$20
    .a16
    beq @live
    rts
@dissolving_out:
    .a16
    .i16
    jsr rpgo_park
    rts
@live:
    .a16
    .i16
    jsr handle_a
    jsr dialog_is_open
    bne @drawn                      ; A REAL DIALOG BLOCKS THE WALK. This is the
                                    ;   freeze, and it is the query the panel
                                    ;   exists to answer.
    jsr read_step
@drawn:
    .a16
    .i16
    ; Age the save-torch flare (the NMI reads this count to swap the tile).
    ; Unconditional — it must run while the save dialog is open too.
    sep #$20
    .a8
    lda z:::RPG_TOWN_FLARE
    beq @no_flare
    dec z:::RPG_TOWN_FLARE
@no_flare:
    .a8
    .i16
    rep #$20
    .a16
    jsr draw_actors
    rts

; --- handle_a: the one interaction button -----------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; Read on the PRESS EDGE, never the level. On a level read the same held button
; that opened the panel closes it the very next frame; and because this edge
; also drives the page flow, a level read would flip through every page of a
; message in three frames.
handle_a:
    .a16
    .i16
    lda z:ES_INP_PRESS
    bit #::JOY_A
    bne @pressed
    rts
@pressed:
    .a16
    .i16
    jsr dialog_is_open
    beq @closed
    jsr dialog_advance              ; page 2, page 3, then it closes itself —
                                    ;   the "text flow", and the close is not a
                                    ;   separate caller decision
    rts
@closed:
    .a16
    .i16
    ldx #::TOWN_NPC_TX
    ldy #::TOWN_NPC_TY
    jsr adj_to
    bne @talk
    ldx #::TOWN_SAVE_TX
    ldy #::TOWN_SAVE_TY
    jsr adj_to
    bne @save
    ; ---- A DOES NOT TAKE THE GATE -------------------------------------------
    ; The exit lives on the walk-commit path (try_step), so stepping ONTO the
    ; gate wipes out — which is what the NPC's "WALK ONTO IT" says and what the
    ; entry mechanic does. A is dialog + save only; nothing to do here when
    ; adjacent to neither.
@nothing:
    .a16
    .i16
    rts
@talk:
    .a16
    .i16
    lda #.loword(npc_pages)
    ldx #NPC_PAGE_COUNT
    jsr dialog_open
    rts
@save:
    .a16
    .i16
    jsr ::rpg_do_save               ; header + payload + CRC-16 into slot 0
    lda #.loword(saved_pages)
    ldx #1
    jsr dialog_open
    ; Flare the save torch, so the save has a confirmation the player can see
    ; without reading the box. Arm the countdown; town_flare_commit swaps the
    ; lit tile in each VBlank while it runs and restores the normal tile as it
    ; expires. tick ages the count.
    sep #$20
    .a8
    lda #TOWN_FLARE_FRAMES
    sta z:::RPG_TOWN_FLARE
    rep #$20
    .a16
    rts

; --- adj_to: is the player a 4-neighbour of town cell (X=tx, Y=ty)? ---------
; Out: A16 = 1 (Z clear) if adjacent, 0 (Z set) otherwise. Manhattan distance
; exactly 1 on the grid. In/out: A16/I16, DB=0. Clobbers A.
adj_to:
    .a16
    .i16
    txa
    sec
    sbc z:::RPG_TOWN_TX
    bpl @dx_pos
    eor #65535
    inc a                           ; |dx|
@dx_pos:
    .a16
    .i16
    sta z:::RPG_T0
    tya
    sec
    sbc z:::RPG_TOWN_TY
    bpl @dy_pos
    eor #65535
    inc a                           ; |dy|
@dy_pos:
    .a16
    .i16
    clc
    adc z:::RPG_T0
    cmp #1
    beq @yes
    lda #0
    rts
@yes:
    .a16
    .i16
    lda #1
    rts

; --- read_step: HOLD-TO-WALK with an auto-repeat throttle --------------------
; A HELD direction walks tile-by-tile; a single tap moves exactly one tile. This
; is the OVERWORLD's model fitted to the town's structure — a tile JUMP with a
; repeat throttle, NOT a per-frame pixel slide, because the town avatar renders
; only at tile*8 (draw_actors) and has no sub-tile pixel state a slide could
; drive. The throttle is cleared the instant no direction is held, so a tap is
; NEVER throttled (single tap = one tile). Reads ES_INP_CUR (the HELD level),
; never ES_INP_PRESS. An open dialog still freezes the walk — tick gates this
; call on dialog_is_open, so the timebase below does not advance either and the
; walk resumes where it was rather than a fifth of a tile along.
;
; THE THROTTLE IS A RATE, AND IT IS THE SAME RATE THE OVERWORLD SPENDS IN
; PIXELS. It counts TOWN_STEP_UNITS down to the next commit at the whole units
; TS_STEP publishes for a base of one per frame — one on NTSC, so the tile
; still commits every eight frames exactly, and 1.2018 on PAL, so it commits in
; the same real time. The overshoot is CARRIED into the next tile rather than
; dropped, which is the same reason tick_scale carries a fraction at all: a
; throttle that re-quantised every tile would lose about 2% of the walk.
; game.toml's region note has the measurement.
;
; THE TWO SCENES DO NOT WALK AT THE SAME TILES PER SECOND, and they did not
; before this either — the note above once said they did. A town tile is 8
; frames; an overworld tile is 9, because its slide is preceded by a frame that
; only decides. What the timebase holds is each scene's OWN rate across the two
; machines, which is the property that was asked for.
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
TOWN_STEP_UNITS = ::TILE_PX             ; one tile's worth of throttle units
; TICK: ok — this throttle counts the region's published UNITS, not frames.
;   The frame is what TS_STEP converts out of; how many frames a tile takes
;   here is the output, and it is 8 on NTSC and ~6.65 on PAL by measurement.
read_step:
    .a16
    .i16
    TS_STEP z:US_TS_ACC, TS_ONE         ; one unit per NTSC frame. No zero
    sta z:US_TS_STEP                    ;   guard here and none is owed: this
                                        ;   path does not loop, so a published
                                        ;   zero would cost one frame of walk
                                        ;   rather than hang — and at this base
                                        ;   it cannot happen anyway.
    lda z:ES_INP_CUR
    and #(::JOY_LEFT | ::JOY_RIGHT | ::JOY_UP | ::JOY_DOWN)
    bne @held
    ; nothing held: clear the throttle so the NEXT press steps at once (a tap
    ; is one tile, never throttled)
    sep #$20
    .a8
    stz z:::RPG_TOWN_REP
    rep #$20
    .a16
    rts
@held:
    .a16                                ; arrives A16 (from the `and`/`bne`)
    .i16
    sep #$20
    .a8
    lda z:::RPG_TOWN_REP
    beq @fresh                          ; nothing was held last frame: step now
    sec
    sbc z:US_TS_STEP                    ; A8 reads the published step's LOW
                                        ;   byte, and at this base it is 1 or 2
    bcc @commit                         ; below zero: the tile is due
    beq @commit                         ; landed exactly on it
    sta z:::RPG_TOWN_REP                ; still throttled
    rep #$20
    .a16
    rts
@commit:
    .a8                                 ; arrives A8 (both branches follow the
    .i16                                ;   sep #$20 above)
    clc
    adc #TOWN_STEP_UNITS                ; A is the overshoot, at or below zero
    sta z:::RPG_TOWN_REP                ;   in two's complement — adding the
                                        ;   tile CARRIES it instead of dropping
                                        ;   it, so the walk cannot round short
    bra @move
@fresh:
    .a8                                 ; arrives A8 (beq after the sep #$20)
    .i16
    lda #TOWN_STEP_UNITS
    sta z:::RPG_TOWN_REP
@move:
    .a8                                 ; arrives A8 (fall-through and `bra`)
    .i16
    rep #$20
    .a16
    lda z:ES_INP_CUR                    ; decode the axis, cardinal + priority
    bit #::JOY_LEFT
    beq @not_left
    ldx #65535
    ldy #0
    jmp try_step
@not_left:
    .a16
    .i16
    bit #::JOY_RIGHT
    beq @not_right
    ldx #1
    ldy #0
    jmp try_step
@not_right:
    .a16
    .i16
    bit #::JOY_UP
    beq @not_up
    ldx #0
    ldy #65535
    jmp try_step
@not_up:
    .a16
    .i16
    bit #::JOY_DOWN
    beq @none
    ldx #0
    ldy #1
    jmp try_step
@none:
    .a16
    .i16
    rts

; --- try_step: commit one tile if the destination walks ---------------------
; In: X = signed tile dx, Y = signed tile dy. In/out: A16/I16, DB=0.
; Clobbers A, X, Y.
try_step:
    .a16
    .i16
    txa
    clc
    adc z:::RPG_TOWN_TX             ; destination tile x
    pha
    tya
    clc
    adc z:::RPG_TOWN_TY             ; destination tile y
    pha
    tay
    plx                             ; ...and back, so both are also in X/Y for
    phx                             ;    the probe below (X=ty for a moment)
    ply
    plx                             ; X = dest tx, Y = dest ty
    phx
    phy
    jsr rpgt_blocks                 ; A = 1 blocked, 0 walkable
    ply                             ; THE DESTINATION COMES BACK OFF THE STACK,
    plx                             ;   not out of RPG_T0: rpgt_blocks uses that
                                    ;   very byte pair as its own index scratch.
                                    ;   An earlier form parked the destination
                                    ;   there and read it back after the call —
                                    ;   the emulator showed town_tx = 640, which
                                    ;   is ty * 32, i.e. the probe's own
                                    ;   intermediate. rpg_town's header calls the
                                    ;   slot "transient, consumed inside one
                                    ;   call"; this is what crossing that means.
    cmp #0
    bne @blocked
    sty z:::RPG_TOWN_TY
    stx z:::RPG_TOWN_TX
    ; ---- stepping ONTO the south gate wipes out to the overworld ------------
    ; The gate (TOWN_EXIT_TX/TY) is a WALKABLE door tile, so the avatar steps
    ; onto it and the exit arms HERE — matching the entry mechanic (overworld
    ; try_step arms the wipe at its F_TOWN gate) and the villager's own
    ; instruction, "WALK ONTO IT WHEN YOU ARE READY" (npc_l6-8). The A-press
    ; exit path is gone; A is dialog + save only. X = dest tx, Y = dest ty here;
    ; arm_exit clobbers A, X but we are at the tail (rts follows either arm).
    cpx #::TOWN_EXIT_TX
    bne @blocked
    cpy #::TOWN_EXIT_TY
    bne @blocked
    jsr arm_exit
@blocked:
    .a16
    .i16
    rts

; --- arm_exit: start the wipe back out to the overworld ---------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
arm_exit:
    .a16
    .i16
    sep #$20
    .a8
    lda #::TM_BG1                   ; the affected-BG nibble for $2106
    ldx #.loword(::rpg_blank_to_overworld)
    jsr ::mosaic_arm
    rep #$20
    .a16
    rts

; --- draw_actors: the avatar at its tile, the villager at hers --------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
; The camera is fixed and the room fills the screen, so screen px = tile x 8.
; A 16x16 sprite is drawn from its top-left, which is the tile's own corner.
draw_actors:
    .a16
    .i16
    lda z:::RPG_TOWN_TX
    asl
    asl
    asl
    pha
    lda z:::RPG_TOWN_TY
    asl
    asl
    asl
    tax
    pla
    ldy #0
    jsr rpgo_place
    lda #(::TOWN_NPC_TX * 8)
    ldx #(::TOWN_NPC_TY * 8)
    ldy #1
    jsr rpgo_place
    lda z:::RPG_TOWN_TX
    asl
    asl
    asl
    ldx #(::TOWN_NPC_TX * 8)
    jsr rpgo_hi                     ; the quad's byte, rebuilt whole from both
    rts                             ;   actors' own X

; --- town_flare_commit: the save-torch flare, one VBlank tile swap ----------
; Called from sm_nmi_hook (main.asm), gated on the town scene. While the
; flare countdown runs it swaps the LIT torch tile into the save-torch cell
; (TOWN_SAVE_TX/TY) and on the last frame writes the NORMAL torch back, so the
; cell restores itself; idle (RPG_TOWN_FLARE == 0) it touches no VRAM. Programs
; its OWN VMAIN + VMADD, which is what makes the hook order free (AGENTS.md).
; The write is ONE BG1 tilemap word (tile id low, attr 0 high) — the same shape
; gen_rpg_assets.py emits for every town cell.
;
; WIDTH-RISK: entered A8/I16 from sm_nmi_hook and MUST exit A8/I16, DB
; unchanged. Reached ONLY through the hook's function call — no same-file
; arrival exists — so these markers ARE the width contract.
TOWN_FLARE_FRAMES = 12                          ; ~0.2 s on NTSC: brief but
                                                ;   visible
                                                ; TICK: ok — a DURATION, not a
                                                ;   rate, and the one number
                                                ;   on this rail the timebase
                                                ;   deliberately leaves alone.
                                                ;   docs/98 §2 keeps a
                                                ;   countdown integer and
                                                ;   DISCLOSES it: the PAL
                                                ;   flare is the same 12
                                                ;   frames and so runs 0.24 s.
                                                ;   It confirms a save; it
                                                ;   paces nothing.
TOWN_SAVE_MAP_WORD = ES_V_TOWN_MAP + (::TOWN_SAVE_TY * 32) + ::TOWN_SAVE_TX
.a8
.i16
town_flare_commit:
    lda z:::RPG_TOWN_FLARE
    beq @done                                   ; idle -> touch no VRAM
    lda #$80
    sta a:$2115                                 ; VMAIN: word step after $2119
    ldx #TOWN_SAVE_MAP_WORD
    stx a:$2116                                 ; VMADD = the save-torch cell
    lda z:::RPG_TOWN_FLARE
    cmp #1
    beq @restore                                ; last frame -> normal, then idle
    lda #TT_TORCH_LIT
    bra @write
@restore:
    .a8
    .i16
    lda #TT_TORCH
@write:
    .a8
    .i16
    sta a:$2118                                 ; VMDATAL = tile id
    stz a:$2119                                 ; VMDATAH = 0 (palette 0, prio 0)
@done:
    .a8
    .i16
    rts

; --- exit: the scene_mgr contract, kept honest ------------------------------
; NOTHING REACHES HERE on this rail — the transition is rpg_swap_service.
exit:
    .a16
    .i16
    jsr rpgo_park
    jsr dialog_close
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

; =============================================================================
; The messages. Three word pointers per page, in page order — dialog's page
; table format. Clean-room original text, uppercase ASCII the 96-glyph font
; renders, each line short enough for the panel's 26-cell interior.
; =============================================================================
NPC_PAGE_COUNT = 3

npc_pages:
    .word npc_l0, npc_l1, npc_l2
    .word npc_l3, npc_l4, npc_l5
    .word npc_l6, npc_l7, npc_l8
npc_l0: .byte "WELCOME TO STONEHOLLOW,", 0
npc_l1: .byte "TRAVELLER. THE ROAD NORTH", 0
npc_l2: .byte "IS LONG AND THE LAKE DEEP.", 0
npc_l3: .byte "THE TORCH IN THE COURTYARD", 0
npc_l4: .byte "REMEMBERS WHERE YOU STOOD.", 0
npc_l5: .byte "STAND BY IT AND PRESS A.", 0
npc_l6: .byte "THE SOUTH GATE OPENS ONTO", 0
npc_l7: .byte "THE WORLD AGAIN. WALK ONTO", 0
npc_l8: .byte "IT WHEN YOU ARE READY.", 0

saved_pages:
    .word saved_l0, saved_l1, saved_l2
saved_l0: .byte "THE TORCH FLARES ONCE.", 0
saved_l1: .byte "YOUR JOURNEY IS RECORDED.", 0
saved_l2: .byte 0

.endscope
