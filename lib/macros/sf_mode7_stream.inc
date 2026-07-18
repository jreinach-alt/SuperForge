; =============================================================================
; sf_mode7_stream.inc — Mode 7 2-axis (row + column) tilemap-streaming front door
; =============================================================================
; Clean-room kit macro surface over engine/mode7_stream.asm + the NMI VBlank
; dispatch in engine/mode7_stream_nmi.inc (hooked into nmi_handler.asm under
; the MODE7_STREAM_NMI define). Lets a game walk a Mode 7 camera through a world
; LARGER than the 128x128 Mode 7 VRAM window: regions stream into the VRAM
; window seamlessly as the camera moves, with no pop-in / tearing / black bands,
; forward, backward, and idle.
;
; This is the proven overhead-racing streaming substrate, made reusable: a FLAT
; multi-bank ROM tilemap (1 byte/tile), a per-frame main-thread tick that diffs
; the camera tile position and stages the leading-edge row(s)/column(s) at the
; VRAM-WRAPPED position, and an NMI dispatcher that DMAs them into the Mode 7
; tilemap low bytes (the CHR high bytes — uploaded once at boot — never stream).
;
; --- Build wiring (the including ROM MUST do all three) ---------------------
;   1. Assemble with  -D MODE7_STREAM_NMI  so nmi_handler.asm pulls the
;      streaming VBlank DMA dispatch (engine/mode7_stream_nmi.inc).
;   2. Link with a config that gives the flat tilemap its own banks
;      (infrastructure/rom_template/lorom_stream.cfg, "; LDCFG: lorom_stream.cfg").
;   3. Include + link engine/mode7_stream.asm (the tick/init routines), and
;      provide the world constants (world_stream.inc: WORLD_T_TILES,
;      WORLD_WRAP_MASK, WORLD_ROWS_PER_BANK, WORLD_FLAT_BANK_BASE, ...) plus the
;      flat tilemap banks linked at $bb:8000 (bb = WORLD_FLAT_BANK_BASE+(row>>7))
;      and the 32KB interleaved seed uploaded once via sf_mode7_load_map.
;
; --- Typical boot + loop shape -----------------------------------------------
;   ; under coldstart forced blank:
;   sf_mode7_load_map world_seed, #$8000      ; seed the initial 128x128 window
;   ...upload world_palette to CGRAM...
;   sf_mode7_on / perspective / focus / cam   ; Mode 7 PPU setup
;   sf_mode7_stream_init #WORLD_SPAWN_TX, #WORLD_SPAWN_TY
;   ; per frame, after moving the camera:
;   sf_mode7_stream_set_cam cam_px, cam_py    ; update streaming cam tile pos
;   sf_mode7_stream_tick                      ; stage leading rows/cols
;   sf_mode7_cam cam_px, cam_py, angle        ; commit Mode 7 camera
;   sf_mode7_tick                             ; rebuild the perspective HDMA
; =============================================================================

; -----------------------------------------------------------------------------
; sf_mode7_stream_init tx, ty — arm streaming for spawn tile (tx, ty).
; -----------------------------------------------------------------------------
;   tx, ty   world spawn TILE coordinates (0..WORLD_T_TILES-1), verbatim 16-bit
;            immediates (e.g. #WORLD_SPAWN_TX) or absolute addresses. Sets the
;            camera/last tile position so the first tick streams from the seed
;            window's edges. Call ONCE after the seed upload + sf_mode7_on,
;            during boot.
; Clobbers A, X, Y. Asserts A16/I16 entry; exits A16/I16.
; WIDTH-RISK: forces A16/I16 with `rep #$30` then JSRs the engine routine, which
; restores A16/I16 before returning. No A8 span leaks to the caller.
.macro sf_mode7_stream_init sf_tx, sf_ty
    rep #$30
    .a16
    .i16
    ldx sf_tx
    ldy sf_ty
    jsr mode7_stream_init
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_stream_set_cam px, py — update the streaming camera tile position
; from world PIXEL coordinates (the tick converts px>>3 -> tile, wrapped).
; -----------------------------------------------------------------------------
;   px, py   world camera PIXEL coordinates (16-bit), verbatim operands. These
;            are the SAME values you pass to sf_mode7_cam; call this BEFORE
;            sf_mode7_stream_tick each frame.
; Clobbers A. Asserts A16/I16 entry; exits A16/I16.
; WIDTH-RISK: forces A16/I16 with `rep #$30` then JSRs the engine routine, which
; restores A16/I16 before returning. No A8 span leaks to the caller.
.macro sf_mode7_stream_set_cam sf_px, sf_py
    rep #$30
    .a16
    .i16
    ldx sf_px
    ldy sf_py
    jsr mode7_stream_set_cam
.endmacro

; -----------------------------------------------------------------------------
; sf_mode7_stream_tick — per-frame main-thread streaming service. Diffs the
; camera tile position vs the last-streamed position and stages any newly
; entered rows/columns into the WRAM buffers (the NMI DMAs them next VBlank).
; -----------------------------------------------------------------------------
; Put it in your game loop AFTER sf_mode7_stream_set_cam and BEFORE the next
; sf_frame_begin (so the NMI that frame drains the freshly-staged buffers).
; Cheap when the camera is idle (a compare + early-out). Clobbers A, X, Y and
; the streaming DP scratch. Asserts A16/I16 entry; exits A16/I16.
; WIDTH-RISK: forces A16/I16 with `rep #$30` then JSRs the engine routine, which
; manages its own A8/A16 spans internally and restores A16/I16 before returning.
; No A8 span leaks to the caller.
.macro sf_mode7_stream_tick
    rep #$30
    .a16
    .i16
    jsr mode7_stream_tick
.endmacro
