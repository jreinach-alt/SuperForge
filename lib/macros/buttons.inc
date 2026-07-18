; =============================================================================
; buttons.inc — controller button-ID constants (macro library, rung A2)
; =============================================================================
; Symbolic button IDs for the btn / btnp macros, so authors write
; `btn #BTN_RIGHT` instead of `btn #1`. Values match engine/input_handler.asm's
; button_bitmask_table (L95-107) — the engine maps each ID to its SNES joypad
; bitmask. Do not renumber without updating that table.
; =============================================================================

.ifndef SF_BUTTONS_INC
SF_BUTTONS_INC = 1

BTN_LEFT    = 0
BTN_RIGHT   = 1
BTN_UP      = 2
BTN_DOWN    = 3
BTN_A       = 4         ; SNES A
BTN_B       = 5         ; SNES B
BTN_L       = 6         ; L shoulder
BTN_R       = 7         ; R shoulder
BTN_START   = 8
BTN_SELECT  = 9
BTN_X       = 10        ; SNES X
BTN_Y       = 11        ; SNES Y

.endif ; SF_BUTTONS_INC
