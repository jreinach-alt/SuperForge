; =============================================================================
; stomper.inc — the rail's geometry, physics tuning and state vocabulary
; =============================================================================
; Top-level (included by main.asm before the scene) because stomper_obj.asm
; and the play scene both read from it. Pure equates: no code, no claims,
; nothing the allocator owns. Every number is written as the algebra it is
; rather than as a bare constant — `no_literals` refuses the bare hex forms,
; and the shift forms say what each number IS.

; --- $4218 bit POSITIONS (shifts, not hex — the no_literals idiom) -----------
JOY_A     = 1 << 7
JOY_RIGHT = 1 << 8
JOY_LEFT  = 1 << 9

; --- the player -------------------------------------------------------------
ST_SPEED   = 2                   ; move step, px/frame
ST_SPAWN_X = 200                 ; spawn / knockback x
ST_SPAWN_Y = 200                 ; spawn / knockback y (box top; feet on the
                                 ;   ground row 26 top at 208)

; --- physics (8.8 derivations) ----------------------------------------------
; The same three numbers `jumper` ships — gravity, terminal fall, take-off —
; with the stomp bounce added below.
ST_GRAVITY  = 1 << 6                       ; 0.25 px/f^2
ST_MAX_FALL = 4 << 8                       ; 4 px/f terminal fall — also the
                                           ;   no-tunnel bound the 8x8 probe
                                           ;   covers, and what makes the
                                           ;   5-px stomp window catch every
                                           ;   falling first-touch
ST_JUMP_VEL = (4 << 8) + (1 << 7)          ; 4.5 px/f take-off (~38 px apex)
ST_JUMP_NEG = (0 - ST_JUMP_VEL) & $FFFF    ; ...as the two's-complement word
                                           ;   an `lda #` immediate can hold
                                           ;   (m7_dungeon's FP_NEAR shape)

; --- the stomp ---------------------------------------------------------------
ST_BOUNCE_VEL = 3 << 8                     ; stomp bounce: 3 px/f up (~17 px)
ST_BOUNCE_NEG = (0 - ST_BOUNCE_VEL) & $FFFF
ST_STOMP_DEPTH = 5               ; how deep (px) the player's bottom may be
                                 ;   inside the enemy's top and still count
                                 ;   as a stomp; deeper classifies as hurt

; --- the enemies -------------------------------------------------------------
ST_PATROL_SPEED = 1              ; px/frame
ST_E1_X0  = 120                  ; enemy 1 spawn x (ground beat)
ST_E1_Y   = 200                  ; enemy 1 y: stands on the ground row
ST_E2_X0  = 48                   ; enemy 2 spawn x (platform beat)
ST_E2_Y   = 152                  ; enemy 2 y: stands on the platform row
                                 ; (both spawn heading RIGHT, edir = 1; the
                                 ;  beats emerge from the level geometry rather
                                 ;  than from a declared span: E1 paces 88..152
                                 ;  between the low walls, E2 32..64 on the
                                 ;  platform)

; --- BG3 text geometry -------------------------------------------------------
; "FOES" at pixel (8,8) = row 1 col 1; the 5-digit counter at pixel (48,8) =
; col 6 (cells 6..10, live units cell at col 10); "CLEAR" at pixel (104,104)
; = row 13 col 13 (cells 13..17).
ST_HUD_ROW   = 1
ST_LABEL_C   = 1
ST_DIGITS_C  = 6
ST_CLEAR_ROW = 13
ST_CLEAR_C   = 13
ST_CLEAR_LEN = 5                 ; five letters; bg_text's queue holds ONE run
                                 ;   of up to 4 cells per frame, so the win
                                 ;   print pumps one cell per frame

; --- scene ids (game.toml manifest order) ------------------------------------
SCENE_PLAY = 0                   ; the only one
