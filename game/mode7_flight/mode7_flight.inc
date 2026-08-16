; =============================================================================
; mode7_flight.inc — the rail's vocabulary: the spawn, and nothing else
; =============================================================================
; Constants only — no addresses. Every address in this rail comes from the
; allocator's emitted map; `allocator/no_literals.py` refuses anything else.
;
; It is SHORT because this rail's numbers live where they are used: the band and
; the factor model are m7f_cam.asm's, the throttle and altitude constants are
; m7f_logic.asm's, and the sprite placement is m7f_obj.asm's. What is left is
; the one thing the SCENE decides — where the flight starts.

; --- the spawn --------------------------------------------------------------
; SPAWN_X = 872, SPAWN_Y = 512 on a 1024 px plane: over a detailed
; continent/coast cluster rather than open ocean, so the boot frame shows
; terrain with structure in it. tools/gen_m7f_assets.py asserts the cell is
; land.
M7F_SPAWN_X = 872
M7F_SPAWN_Y = 512

; Heading 0 and the mid-altitude spawn — index 40 (m7f_cam's M7F_ALT_SPAWN).
; Starting mid-climb rather
; than on the floor is what lets a cold-read see the ground both recede AND
; approach without first flying to an end stop.
M7F_SPAWN_HEAD = 0
