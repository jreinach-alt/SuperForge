; =============================================================================
; sh2_swarm.asm — the rail's world model: two players and 22 AI followers
; =============================================================================
; The third job on this rail, and the reason it is its own file:
; `m7_persp_project` owns the projection MATHS, `sh2_obj` owns everything the
; PPU sees, and this owns WHERE THE ENTITIES ARE. It reads no PPU register and
; writes no OAM byte; `sh2_obj` reads the table this maintains and draws it.
;
; THE PLAYERS ARE ENTITIES 0 AND 1 AND THEIR POSITIONS ARE THE CAMERAS'.
; `swm_players` copies both camera positions into those two records every
; frame, so each player's marker renders in the OTHER band — in its own band
; the point projects to v = 0, at the pivot row, and the projector's `v >= 0`
; cull drops it by construction. No special case, and that is the point of
; putting the players in the same table as the followers.
;
; THE AI IS WORLD-SPACE ONLY. It never reads the matrix, the poses or the
; cameras, so it is rotation-invariant by construction: a follower walks the
; same path whichever way the two cameras happen to be looking, which is what
; makes "the cast moves" separable from "the cameras move" in the tests.
;
; THE MODEL. Per follower per frame:
;
;  target = way[(i - 2) & 7][wp]
;  reached (Chebyshev < 24 on BOTH wrapped axes)
;  -> wp = (wp + 1) & 3, and a ONE-FRAME PAUSE (no move this frame)
;  else steer: cross = (fwd >> 3) x (delta >> 3)
;  cross < 0 -> h += US_TSH; cross > 0 -> h -= US_TSH
;  cross = 0 and dot < 0 -> h += US_TSH (the 180-degree tie-break)
;  then move at HALF the camera speed: move256[h] >> 1 through the same 8.8
;  per-axis accumulators the camera drive uses.
;
; THE TWO REGION WORDS ARE THE SCENE'S, and both are read here for the same
; reason the cameras read them: a follower's turn and step are the SAME motion
; the cameras make, at half the speed, out of the same table. `US_MOVE_ARM`
; picks which arm of `sh2_move256` this console reads and `US_TSH` is the pose
; step sh2_cam published for the frame. Neither is camera state, so the
; rotation-invariance above is untouched — on NTSC they are 0 and 1, and this
; file's arithmetic is what it was to the bit.
;
; WHY EVERYTHING IS SHIFTED RIGHT BY THREE. The steering cross product is two
; signed 8x8 HARDWARE multiplies (`mpp_mul8`), and an 8x8 multiply needs both
; operands inside a byte after the sign/magnitude split. A wrapped residue is
; s10 (|.| <= 512) and a move256 velocity is 8.8 with magnitude 512, so >>3
; brings both to |.| <= 64 — products <= 4096, and the cross of two of them
; still fits s16 with no 32-bit accumulator. The shift is what makes the
; hardware multiplier legal here, not a precision choice.
;
; WHY `mpp_mul8` AND NOT OUR OWN $4202 WRITES. `ALU` is one whole resource with
; one owner and `m7_persp_project` holds the claim; a second claim is refused
; and undeclared writes are refused by `no_literals`' reg-ownership pass. The
; owner publishes the primitive; see its header.
;
; WHERE IT RUNS: the scene TICK, during active display, immediately before the
; projection that reads its output — never the VBlank hook. Measured, what
; happens when a job this size runs from the hook is this: the post-hook
; MVN of the channel shadow lands in active display and rewrites every
; channel's running HDMA state, and the floor speckles with every byte reading
; back correct. Twenty-four entities plus their AI is six times the work that
; broke it.

; --- the entity record, and the table, from the claims ----------------------
SWM_ENT_BYTES = 8
SWM_E_X   = 0                           ; u16 world x
SWM_E_Y   = 2                           ; u16 world y
SWM_E_HWP = 4                           ; wp << 8 | heading
SWM_E_FRC = 6                           ; fracy << 8 | fracx

SWM_MAX = ES_SWM_ENTS_SIZE / SWM_ENT_BYTES
.assert SWM_MAX * SWM_ENT_BYTES = ES_SWM_ENTS_SIZE, error, "sh2_swarm: the entity claim is not a whole number of records"
.assert ES_R_SH2_ENTS_SIZE = ES_SWM_ENTS_SIZE, error, "sh2_swarm: the seed blob does not fill the entity table — swm_arm copies it wholesale, so a short blob would leave records nobody wrote (rule 5)"

; The two players, then the followers. Entity 0 is camera 1's marker and 1 is
; camera 2's; every entity from SWM_PLAYERS up is an AI follower.
SWM_PLAYERS = 2
SWM_N_SHIP  = 24                        ; the shipping live count — the
                                        ; measured margin is in feature.toml

; --- the AI's world model, from its claim -----------------------------------
SWM_LOOPS      = 8
SWM_WAYPOINTS  = 4
SWM_WAY_BYTES  = 4                      ; (x, y) as two u16 words
SWM_WAY_STRIDE = SWM_WAYPOINTS * SWM_WAY_BYTES
.assert ES_R_SH2_WAY_SIZE = SWM_LOOPS * SWM_WAY_STRIDE, error, "sh2_swarm: the waypoint blob is not 8 loops x 4 targets"

; The Chebyshev radius that counts as ARRIVED, in world px.
SWM_REACH = 24

; --- the geometry, as shifts ------------------------------------------------
; Same form and same reason as m7_persp_project's: `no_literals` reads a bare
; 1024 as a WRAM-claim address and cannot tell it from a hand-narrated one, and
; the shift is the honest statement anyway — the plane wraps on a power of two
; because the PPU's Mode 7 sampler does.
SWM_WORLD_LOG2 = 10
SWM_WORLD_PX   = 1 << SWM_WORLD_LOG2
SWM_WRAP       = SWM_WORLD_PX - 1
SWM_HALF       = SWM_WORLD_PX / 2       ; the residue's sign boundary
SWM_SIGNBITS   = ~SWM_WRAP & $FFFF      ; the s16 extension of a 10-bit residue
SWM_NEAR_HI    = SWM_WORLD_PX - SWM_REACH + 1
.assert SWM_WORLD_PX = MPP_WORLD_PX, error, "sh2_swarm: the AI's wrap period is not the projector's — one of the two is walking a different plane"

; Byte masks, as shifts for the same reason.
SWM_BYTE   = (1 << 8) - 1
SWM_HIBYTE = SWM_BYTE << 8
SWM_SIGN8  = 1 << 7
SWM_HEADS  = 1 << 8
SWM_HMASK  = SWM_HEADS - 1
SWM_WPMASK = ((SWM_WAYPOINTS - 1) << 8) | SWM_BYTE

; --- the state, inside the claims -------------------------------------------
SWM_N    = ES_SWM_CTL_LONG + 0          ; the live count (poked by the sweep)
SWM_BEAT = ES_SWM_CTL_LONG + 2          ; the main loop's own frame counter

SWM_ENT = ES_SWM + 0
SWM_CNT = ES_SWM + 2
SWM_TX  = ES_SWM + 4
SWM_TY  = ES_SWM + 6
SWM_DX  = ES_SWM + 8
SWM_DY  = ES_SWM + 10
SWM_FX  = ES_SWM + 12
SWM_FY  = ES_SWM + 14
SWM_T0  = ES_SWM + 16
SWM_T1  = ES_SWM + 18

; =============================================================================
; SWM_ASR3 — an arithmetic >>3 of the accumulator
; =============================================================================
; `cmp #$8000` puts the value's sign bit in the carry and `ror a` shifts it
; back in, which is an arithmetic shift right on the 65816 (there is no ASR
; opcode).
;
; WIDTH-RISK: contains NO sep/rep, so it cannot leak a width into the caller on
; either axis. A16 in, A16 out; clobbers only the carry.
.macro SWM_ASR3
    cmp #$8000
    ror a
    cmp #$8000
    ror a
    cmp #$8000
    ror a
.endmacro

; =============================================================================
; swm_arm — seed the whole table and the control block (scene enter)
; =============================================================================
; In/out: A16/I16, DB=0, forced blank + NMI masked (the scene_mgr enter
; contract). Clobbers A, X.
;
; ALL SWM_MAX RECORDS, not the SWM_N_SHIP the build ticks. Power-on WRAM is
; random and this claim declares no zero-fill, so this copy IS the
; write-before-read contract (rule 5) — and the cadence sweep pokes the count
; UPWARD, so a record the shipping build never reads is one the sweep does.
;
; WIDTH-RISK: A16/I16 in and out, no sep/rep anywhere in the body.
swm_arm:
    .a16
    .i16
    ldx #0
@copy:
    .a16
    .i16
    lda f:sh2_ents_bin, x
    sta f:ES_SWM_ENTS_LONG, x
    inx
    inx
    cpx #ES_R_SH2_ENTS_SIZE
    bcc @copy
    lda #SWM_N_SHIP
    sta f:SWM_N
    lda #0
    sta f:SWM_BEAT
    rts

; =============================================================================
; swm_beat — the main loop's own frame counter
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; HALF OF THE CADENCE GATE, and the half nothing else provides. Scene_mgr's
; ES_SM_FRAME counts VBLANKS — sm_nmi_core increments it on EVERY NMI, armed or
; not — so it advances at the PPU's rate whatever the CPU is doing. This one
; advances once per pass through the scene tick. Both must therefore step +1
; per stepped frame, and a tick that overruns its frame makes this one fall
; behind while the other keeps going.
;
; It is called LAST in the tick on purpose: a beat incremented first would
; count a frame the tick had not finished.
swm_beat:
    .a16
    .i16
    lda f:SWM_BEAT
    inc a
    sta f:SWM_BEAT
    rts

; =============================================================================
; swm_players — entities 0 and 1 follow the two cameras
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; Each player's marker renders in the OTHER band only: in its own band the
; point is exactly the camera position, so the camera-frame v is 0 and the
; projector's `v >= 0` cull drops it before any multiply. That self-cull is why
; there is no per-band special case anywhere in sh2_obj.
;
; The headings in records 0/1 are never read — a player's marker is a position,
; not a direction — so they keep whatever the seed blob gave them.
swm_players:
    .a16
    .i16
    lda z:SH2_POS1X
    sta f:ES_SWM_ENTS_LONG + 0 * SWM_ENT_BYTES + SWM_E_X
    lda z:SH2_POS1Y
    sta f:ES_SWM_ENTS_LONG + 0 * SWM_ENT_BYTES + SWM_E_Y
    lda z:SH2_POS2X
    sta f:ES_SWM_ENTS_LONG + 1 * SWM_ENT_BYTES + SWM_E_X
    lda z:SH2_POS2Y
    sta f:ES_SWM_ENTS_LONG + 1 * SWM_ENT_BYTES + SWM_E_Y
    rts

; =============================================================================
; swm_ai — one frame of every follower
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A, X, Y, this feature's scratch and
; m7_persp_project's MPP_ACC/MPP_TMPM (through mpp_mul8).
;
; Entities below SWM_PLAYERS are not touched — they are the cameras' and
; swm_players owns them.
;
; WIDTH-RISK: A16/I16 throughout. There is no sep/rep in this routine at all;
; the only 8-bit window on the path is inside mpp_mul8, which is balanced and
; documents its own contract. Every multi-path label is annotated.
swm_ai:
    .a16
    .i16
    lda f:SWM_N
    cmp #(SWM_PLAYERS + 1)
    bcs @go
    rts                                 ; N <= the players: nothing to steer
@go:
    .a16
    .i16
    sec
    sbc #SWM_PLAYERS
    sta z:SWM_CNT
    lda #(SWM_PLAYERS * SWM_ENT_BYTES)
    sta z:SWM_ENT
@loop:
    .a16
    .i16
    ; ---- the target: way[(i - players) & 7][wp] ---------------------------
    lda z:SWM_ENT
    lsr a
    lsr a
    lsr a                               ; -> the entity index i
    sec
    sbc #SWM_PLAYERS
    and #(SWM_LOOPS - 1)                ; -> the loop id
    .assert SWM_WAY_STRIDE = 1 << 4, error, "sh2_swarm: the loop stride is no longer a shift — the four asl below would be wrong"
    asl a
    asl a
    asl a
    asl a                               ; loop * SWM_WAY_STRIDE
    sta z:SWM_T0
    ldx z:SWM_ENT
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    xba
    and #(SWM_WAYPOINTS - 1)            ; -> wp
    asl a
    asl a                               ; wp * SWM_WAY_BYTES
    clc
    adc z:SWM_T0
    tax
    lda f:sh2_way_bin, x
    sta z:SWM_TX
    lda f:sh2_way_bin + 2, x
    sta z:SWM_TY

    ; ---- the wrapped residues to it ---------------------------------------
    ldx z:SWM_ENT
    lda z:SWM_TX
    sec
    sbc f:ES_SWM_ENTS_LONG + SWM_E_X, x
    and #SWM_WRAP
    sta z:SWM_DX
    lda z:SWM_TY
    sec
    sbc f:ES_SWM_ENTS_LONG + SWM_E_Y, x
    and #SWM_WRAP
    sta z:SWM_DY

    ; ---- arrived? Chebyshev < SWM_REACH on BOTH axes -----------------------
    ; The residue is unsigned, so "within 24" is two windows: [0, 24) is a
    ; small positive delta and (1024-24, 1024) a small negative one.
    lda z:SWM_DX
    cmp #SWM_REACH
    bcc @nearx
    cmp #SWM_NEAR_HI
    bcs @nearx
    bra @steer
@nearx:
    .a16
    .i16
    lda z:SWM_DY
    cmp #SWM_REACH
    bcc @reach
    cmp #SWM_NEAR_HI
    bcs @reach
    bra @steer
@reach:
    .a16
    .i16
    ; wp = (wp + 1) & 3, the heading byte kept, and NO move this frame — the
    ; one-frame pause is what stops a follower jittering back and forth
    ; across a waypoint it has just claimed.
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    clc
    adc #SWM_HEADS                      ; +1 in the high byte
    and #SWM_WPMASK
    sta f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    jmp @next

@steer:
    .a16
    .i16
    ; ---- the residues, sign-extended and arithmetic >>3 --------------------
    lda z:SWM_DX
    cmp #SWM_HALF
    bcc :+
    ora #SWM_SIGNBITS                   ; s16 from the 10-bit residue
:
    SWM_ASR3
    sta z:SWM_DX
    lda z:SWM_DY
    cmp #SWM_HALF
    bcc :+
    ora #SWM_SIGNBITS
:
    SWM_ASR3
    sta z:SWM_DY

    ; ---- the forward vector, >>3 the same way ------------------------------
    ldx z:SWM_ENT
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    and #SWM_HMASK
    asl a
    asl a
    ora z:US_MOVE_ARM                   ; h * 4 inside this console's move arm
    tax
    lda f:SH2_MOVE_LONG + 0, x
    SWM_ASR3
    sta z:SWM_FX
    lda f:SH2_MOVE_LONG + 2, x
    SWM_ASR3
    sta z:SWM_FY

    ; ---- cross = fx*dy - fy*dx --------------------------------------------
    ; Both operands are now bounded by 64, so each product is one signed 8x8
    ; through the ALU's owner and the difference of two of them fits s16.
    lda z:SWM_FX
    ldx z:SWM_DY
    jsr mpp_mul8
    sta z:SWM_T1
    lda z:SWM_FY
    ldx z:SWM_DX
    jsr mpp_mul8
    sta z:SWM_T0
    lda z:SWM_T1
    sec
    sbc z:SWM_T0                        ; A = cross
    beq @tie
    cmp #$8000
    bcs @hplus                          ; cross < 0 -> turn one pose left
    bra @hminus                         ; cross > 0 -> ...right

@tie:
    .a16
    .i16
    ; cross == 0 is either "already facing it" or "facing exactly away", and
    ; only the dot tells them apart. Without this the 180-degree case is a
    ; stable fixed point and the follower walks away from its target forever.
    lda z:SWM_FX
    ldx z:SWM_DX
    jsr mpp_mul8
    sta z:SWM_T1
    lda z:SWM_FY
    ldx z:SWM_DY
    jsr mpp_mul8
    clc
    adc z:SWM_T1                        ; A = dot
    cmp #$8000
    bcc @move                           ; dot >= 0: the heading is fine
; THE CORRECTION IS US_TSH, not a bare +/-1, and it is the same published word
; the two cameras turn by (sh2_cam's cam_advance computes it once per frame).
; A follower's turn and a follower's step are one motion: scaling the step and
; not the turn would walk the same path at a different radius, which is the
; inconsistency the whole region pair exists to avoid. On NTSC the word is 1 and
; these are the `inc a` / `dec a` they replaced, to the bit.
@hplus:
    .a16
    .i16
    ldx z:SWM_ENT
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    tay
    clc
    adc z:US_TSH
    and #SWM_HMASK
    sta z:SWM_T0
    tya
    and #SWM_HIBYTE                     ; keep wp
    ora z:SWM_T0
    sta f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    bra @move
@hminus:
    .a16
    .i16
    ldx z:SWM_ENT
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    tay
    sec
    sbc z:US_TSH
    and #SWM_HMASK                      ; a negative step wraps under the mask
    sta z:SWM_T0
    tya
    and #SWM_HIBYTE
    ora z:SWM_T0
    sta f:ES_SWM_ENTS_LONG + SWM_E_HWP, x

@move:
    .a16
    .i16
    ; ---- forward at HALF the camera speed, along the POST-turn heading -----
    ; Half, so a follower cannot outpace the camera that is chasing it; the same
    ; move256 LUT and the same 8.8 accumulator shape as the drive.
    ldx z:SWM_ENT
    lda f:ES_SWM_ENTS_LONG + SWM_E_HWP, x
    and #SWM_HMASK
    asl a
    asl a
    ora z:US_MOVE_ARM                   ; ...the same arm the steer read
    tax
    lda f:SH2_MOVE_LONG + 0, x
    cmp #$8000
    ror a                               ; arithmetic >>1
    sta z:SWM_FX
    lda f:SH2_MOVE_LONG + 2, x
    cmp #$8000
    ror a
    sta z:SWM_FY
    ldx z:SWM_ENT

    ; x axis — its fraction is the LOW byte of the record's +6 word. The
    ; accumulator is sh2_cam's SH2_DRIVE_AXIS exactly: add the 8.8 velocity to
    ; the kept fraction, take the HIGH byte after the add as this frame's
    ; SIGNED integer delta, move by it and keep the low byte. Written out per
    ; axis rather than macro'd because the two differ only in which byte of one
    ; word the fraction lives in, and a macro parameterised on `xba` would hide
    ; that rather than express it.
    lda f:ES_SWM_ENTS_LONG + SWM_E_FRC, x
    and #SWM_BYTE                       ; fracx
    clc
    adc z:SWM_FX
    sta z:SWM_T0                        ; the 16-bit accumulator
    xba
    and #SWM_BYTE
    cmp #SWM_SIGN8
    bcc :+
    ora #SWM_HIBYTE                     ; sign-extend the s8 delta
:
    clc
    adc f:ES_SWM_ENTS_LONG + SWM_E_X, x
    and #SWM_WRAP                       ; the world's own period
    sta f:ES_SWM_ENTS_LONG + SWM_E_X, x
    lda f:ES_SWM_ENTS_LONG + SWM_E_FRC, x
    and #SWM_HIBYTE                     ; ...keeping fracy untouched
    sta z:SWM_T1
    lda z:SWM_T0
    and #SWM_BYTE
    ora z:SWM_T1
    sta f:ES_SWM_ENTS_LONG + SWM_E_FRC, x

    ; y axis — its fraction is the HIGH byte of the same word.
    lda f:ES_SWM_ENTS_LONG + SWM_E_FRC, x
    xba
    and #SWM_BYTE                       ; fracy
    clc
    adc z:SWM_FY
    sta z:SWM_T0
    xba
    and #SWM_BYTE
    cmp #SWM_SIGN8
    bcc :+
    ora #SWM_HIBYTE
:
    clc
    adc f:ES_SWM_ENTS_LONG + SWM_E_Y, x
    and #SWM_WRAP
    sta f:ES_SWM_ENTS_LONG + SWM_E_Y, x
    lda z:SWM_T0
    and #SWM_BYTE
    xba                                 ; the kept fraction back into the high
    sta z:SWM_T1                        ;   byte...
    lda f:ES_SWM_ENTS_LONG + SWM_E_FRC, x
    and #SWM_BYTE                       ; ...over fracx, which is untouched
    ora z:SWM_T1
    sta f:ES_SWM_ENTS_LONG + SWM_E_FRC, x

@next:
    .a16
    .i16
    lda z:SWM_ENT
    clc
    adc #SWM_ENT_BYTES
    sta z:SWM_ENT
    dec z:SWM_CNT
    beq @done
    jmp @loop                           ; out of bra range: the body is ~300 B
@done:
    .a16
    .i16
    rts
