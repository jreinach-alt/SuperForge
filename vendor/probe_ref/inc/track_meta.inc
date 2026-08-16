; track_meta.inc -- the streaming workd track metadata (4096x4096 pixel space)
; Start position in PIXEL coordinates (0-4095) for direct use with posx+2/posy+2
track_start_x:     .word $07C0  ; pixel 1984 (tile 248)
track_start_y:     .word $0C80  ; pixel 3200 (tile 400)
track_start_angle: .byte 192         ; facing east (90° clockwise from north)

track_waypoint_count: .byte 13
track_waypoints:
    .word $03C0, $0BE0  ; waypoint 0: tile (120,380)   — road center
    .word $0640, $0C80  ; waypoint 1: tile (200,400)   — road center
    .word $0BE0, $0C80  ; waypoint 2: tile (380,400)   — road center
    .word $0D20, $0B40  ; waypoint 3: tile (420,360)   — road center
    .word $0D80, $08C0  ; waypoint 4: tile (432,280)   — road center
    .word $0C80, $0640  ; waypoint 5: tile (400,200)   — road center
    .word $0BE0, $0460  ; waypoint 6: tile (380,140)   — road center
    .word $0A00, $0380  ; waypoint 7: tile (320,112)   — road center
    .word $0640, $0320  ; waypoint 8: tile (200,100)   — road center
    .word $0460, $03C0  ; waypoint 9: tile (140,120)   — road center
    .word $0320, $05A0  ; waypoint 10: tile (100,180)   — road center
    .word $02C0, $0820  ; waypoint 11: tile (88,260)   — road center
    .word $0320, $0AA0  ; waypoint 12: tile (100,340)   — road center
