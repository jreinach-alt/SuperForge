; =============================================================================
; scenes/town.asm — the Mode 1 interior the mosaic wipe carries her into
; =============================================================================
; The other half of the gallery row: step onto the one enterable house and a
; mosaic dissolve puts her inside a room; step onto its door and the same
; dissolve puts her back on the overworld at the spot she left.
;
; THIS SCENE HAS NO `enter`. That is the design, not an omission. scene_mgr's
; transition machine (fade out, blank, exit + enter, fade in) is never driven on
; this rail — `sm_request` is not called from anywhere — because the wipe is a
; mosaic rather than a fade and because `overworld::enter` would re-upload the
; 32 KB seed centred on SPAWN, throwing away the very position the return exists
; to preserve. What replaces `enter` is `resume`, called by main.asm's swap
; service on the frame after the dissolve reaches peak black, with forced blank
; genuinely on screen and NMI masked — the same two guarantees scene_mgr's
; phase-2 switch makes, arrived at by a different route. `sm_enter_tab` still
; names a routine for this scene because the table is indexed by scene id; that
; entry is `resume`, and nothing ever calls it through the table.
;
; WHAT IS INHERITED ACROSS THE WIPE, and it is most of the machine: the Mode 7
; image at VRAM $0000-$3FFF (untouched here — which is why m7x_town's claims are
; PINNED into upper VRAM), the avatar's OBJ CHR at $4000, her OBJ palette at
; CGRAM 128, and OBSEL. m7x_town's feature.toml carries the argument for why
; inheriting rather than claiming is the honest declaration.

.scope town

.include "engine_state_town.inc"    ; GENERATED — this scene's map
.include "m7x_world.inc"            ; GENERATED — the world's vocabulary. Included
                                    ;   AGAIN here rather than hoisted to file
                                    ;   scope: it is equates only, ca65 scopes
                                    ;   are independent, and hoisting would make
                                    ;   every M7X_* in the overworld a DEFERRED
                                    ;   parent lookup — which is not a constant
                                    ;   expression, and that scope feeds several
                                    ;   into `.repeat` counts.

; TM's layer bits ($212C), named for the same reason the overworld names them:
; so the two layers this scene composites are legible at the write site.
TM_BG1 = $01
TM_OBJ = $10

; --- the interior ----------------------------------------------------------
.include "m7x_town.asm"

; =============================================================================
; THE SCENE
; =============================================================================
; --- resume: the blank-phase half of the wipe INTO the town -----------------
; In/out: A16/I16, DB=0. Called from main.asm's mxx_swap_service with forced
; blank on screen and NMI masked. Clobbers A, X, Y.
;
; ORDER IS LOAD-BEARING in one place: `town_spawn` before `town_draw`, because
; the draw reads the tile the spawn just wrote. Everything else here is
; independent.
resume:
    .a16
    .i16
    jsr town_arm                    ; CHR + palette + the computed room + BG1SC/NBA
    jsr town_spawn                  ; her tile and her facing
    jsr town_draw                   ; on screen for the FIRST frame of the IN ramp
                                    ;   — the dissolve brightens onto a complete
                                    ;   picture rather than fading her in late

    ; ---- the fixed camera, THROUGH m7_affine's owned API ------------------
    ; $210D/$210E are BG1HOFS/BG1VOFS in Mode 1 and M7HOFS/M7VOFS in Mode 7, but
    ; they are one register file and `m7_affine` owns it globally on this rail —
    ; its NMI commit writes both every armed frame, in every scene. So this
    ; scene does not contend for them (a second reg claim would be refused, and
    ; correctly): it asks for the pivot at (128,112), which is exactly the input
    ; for which m7a_set_center's two subtractions give HOFS = VOFS = 0. The
    ; matrix words the same commit writes are inert under Mode 1.
    ldx #128                        ; half of 256 active pixels
    ldy #112                        ; half of 224 active scanlines
    jsr ::m7a_set_center

    ; ---- the scene's base display -----------------------------------------
    ; BGMODE and TM are the `scene_writes` this scene owns on m7x_town's behalf
    ; (see that feature.toml's attribution note). BG1SC and BG12NBA are the
    ; feature's own and town_arm has already written them.
    sep #$20
    .a8
    lda #$01                        ; BGMODE 1: BG1 4bpp, and nothing else on
    sta a:$2105
    lda #(TM_BG1 | TM_OBJ)          ; TM: the room AND the avatar
    sta a:$212C
    rep #$20
    .a16
    rts

; --- tick: one town frame ---------------------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y.
;
; FROZEN WHILE A WIPE IS IN FLIGHT, in both directions. Entering, the room is
; being dissolved INTO and reading the pad would let a held press walk her
; before she can see; leaving, the step that armed the exit is the last one that
; counts. `mosaic_active` is the query the feature exists to answer, and the
; freeze is one of the three uses its header names.
tick:
    .a16
    .i16
    sep #$20
    .a8
    jsr ::mosaic_active             ; A = the state byte, Z set when idle
    cmp #::MOS_OUT                  ; 1 = dissolving AWAY, 2 = dissolving in
    rep #$20
    .a16
    beq @dissolving_out
    sep #$20
    .a8
    jsr ::mosaic_active
    rep #$20
    .a16
    beq @live
    rts                             ; the IN ramp: frozen, and she is already
                                    ;   drawn — the swap placed her before the
                                    ;   first bright frame
@dissolving_out:
    .a16
    .i16
    ; OBJ HAS NO HARDWARE MOSAIC. $2106 pixelates BG layers only, so an
    ; unparked sprite floats un-dissolved over a dissolving room. mosaic cannot
    ; do this itself (TM has one owner per scene and it is not mosaic), so it is
    ; a stated caller contract — and the OUT phase is the whole of it: on the
    ; way IN she is meant to be there.
    ;
    ; PARKED HERE AND NOT AT THE ARM SITE, which is where it started. The OAM
    ; shadow is DMA'd once a frame, so the last writer of a frame is the only
    ; one the screen ever sees: a park in `arm_exit` lands on the same frame as
    ; the draw that puts her IN the doorway, and she vanishes a frame before the
    ; dissolve rather than standing in the door as it starts. One frame later
    ; costs nothing and is the picture the transition is meant to show.
    jsr town_park
    rts
@live:
    .a16
    .i16
    jsr town_step                   ; A = 1 iff she is now standing on the door
    cmp #1
    beq @exit_armed
    jsr town_draw
    rts
@exit_armed:
    .a16
    .i16
    jsr arm_exit
    rts

; --- arm_exit: start the wipe back out to the overworld ---------------------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; She is standing IN the doorway when this fires, so the last frame before the
; dissolve shows her there — which is why the door is walkable rather than a
; trigger you bump into.
arm_exit:
    .a16
    .i16
    jsr town_draw                   ; she stands IN the doorway as the dissolve
                                    ;   starts; the tick's OUT branch parks her
                                    ;   from the next frame on
    ; The swap request is raised by the CALLBACK, at peak black — not here.
    ; See mxx_blank_to_overworld's header.
    sep #$20
    .a8
    lda #TM_BG1                     ; the affected-BG nibble for $2106: BG1 only
    ldx #.loword(::mxx_blank_to_overworld)  ; the swap callback — see its header
    jsr ::mosaic_arm
    rep #$20
    .a16
    rts

; --- exit: the scene_mgr contract, kept honest ------------------------------
; In/out: A16/I16, DB=0, forced blank + NMI masked (the scene_mgr exit
; contract). NOTHING REACHES HERE on this rail — the transition is the swap
; service, not `sm_request`, so `sm_exit_tab` is never indexed. It exists
; because the table is indexed by scene id and a missing entry would be a hole
; the day someone adds a title screen, and it does what every other scene's exit
; does: undo the display state this scene turned on, so a successor inherits a
; blank main screen rather than a Mode 1 room it never asked for.
exit:
    .a16
    .i16
    jsr town_park
    sep #$20
    .a8
    stz a:$212C                     ; TM: nothing on the main screen
    stz a:$2105                     ; BGMODE 0
    rep #$20
    .a16
    rts

.endscope
