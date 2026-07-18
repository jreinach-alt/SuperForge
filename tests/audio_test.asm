; =============================================================================
; audio_test — run-gate for sf_audio (TAD bridge: music, SFX, pause/resume)
; =============================================================================
; The kit's first AUDIBLE ROM, and the worked example of the audio build
; shape (see sf_audio.inc + the Makefile's audio rules): links the TAD ca65
; API wrapper + the compiled 24-song set, boots the SPC700 driver, starts
; ode_to_joy, and lets the test drive the rest by input:
;   A      -> sf_sfx SFX::menu_select (center pan)
;   START  -> toggle sf_music_pause / sf_music_resume
;   SELECT -> sf_music_stop (silence; lets the test hear SFX in isolation)
;
; Debug mirrors:
;   $7E:E010  TAD_STATUS every frame ($00 loaded, $01 playing, $02 loading)
;   $7E:E012  latch: 1 once TAD_STATUS reached $01 (song reached PLAYING)
;   $7E:E014  pause toggle state (1 = paused)
;   $7E:E016  SFX trigger count
;
; Done-condition (emulator-verifiable, tests/test_audio.py):
;   - boots; the loader handshake completes (sf_audio_init returns; magic set)
;   - TAD_STATUS reaches PLAYING within ~120 frames (async load completes)
;   - a recorded WAV of the playback is NON-SILENT (the architectural proof:
;     API version <-> embedded loader/driver compatibility, end to end)
;   - pause drops the audio energy; resume restores it; SFX is audible over
;     a paused song
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_input.inc"         ; btnp (+ buttons.inc)
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "engine_state.inc"
.include "tad-audio.inc"        ; TAD ca65 API imports (-I lib/tad/.../ca65-api)
.include "tad_audio_enums.inc"  ; Song:: / SFX:: ids (-I assets/audio)
.include "sf_audio.inc"         ; the kit audio macros

PAUSED  = $32                   ; pause toggle state (DP)
SFXCNT  = $34                   ; SFX trigger count

.segment "CODE"

NMI:
.include "nmi_handler.asm"

NMI_STUB:
    rti

RESET:
    sf_coldstart
    sf_engine_init
    sf_audio_init               ; uploads SPC700 loader + driver (synchronous)

    rep #$30
    .a16
    .i16
    stz PAUSED
    stz SFXCNT
    ldx #$0000
    lda #$0000
    sta f:$7E0000 + $E012, x    ; playing latch
    sf_debug_magic

    sep #$20
    .a8
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

    sf_music #Song::ode_to_joy  ; async: streams over the following ticks

game_loop:
    sf_frame_begin
    sf_audio_tick               ; drives the transfer + commands every frame

    ; --- mirrors: status + playing latch ---
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda f:$7E0000 + $016A       ; TAD_STATUS (engine state, absolute)
    ldx #$0000
    sta f:$7E0000 + $E010, x
    cmp #$01                    ; reached PLAYING?
    bne no_latch
    lda #$01
    sta f:$7E0000 + $E012, x
no_latch:
    .a8
    rep #$30
    .a16
    .i16

    ; --- A: queue a sound effect ---
    btnp #BTN_A
    beq no_sfx
    sf_sfx #SFX::menu_select
    lda SFXCNT
    inc a
    sta SFXCNT
no_sfx:
    .a16

    ; --- START: toggle pause/resume ---
    btnp #BTN_START
    beq no_toggle
    lda PAUSED
    bne do_resume
    sf_music_pause
    lda #$0001
    sta PAUSED
    bra no_toggle
do_resume:
    .a16
    sf_music_resume
    stz PAUSED
no_toggle:
    .a16

    ; --- SELECT: stop the music (silent song) ---
    btnp #BTN_SELECT
    beq no_stop
    sf_music_stop
no_stop:
    .a16

    ; --- mirrors: pause state + sfx count ---
    ldx #$0000
    lda PAUSED
    sta f:$7E0000 + $E014, x
    lda SFXCNT
    sta f:$7E0000 + $E016, x

    sf_frame_end
    sf_debug_complete
    jmp game_loop

.include "ppu_init.inc"
.include "input_handler.asm"
.include "dma_scheduler.asm"
.include "sprite_engine.asm"
.include "tad_bridge.asm"
