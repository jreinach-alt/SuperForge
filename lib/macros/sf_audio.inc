; =============================================================================
; sf_audio.inc — music + sound effects over the TAD bridge (macro library)
; =============================================================================
; The kit's audio front door, wrapping the engine's Terrific Audio Driver
; bridge (engine/tad_bridge.asm -> TAD's ca65 API -> the SPC700 driver).
; Song/SFX IDs come from the compiled set's enums: assets/audio/
; tad_audio_enums.inc (`Song::ode_to_joy`, `SFX::menu_select`, ...).
;
; AUDIO ROMS ARE A DIFFERENT BUILD SHAPE — three things change vs a silent
; ROM (the Makefile's audio rule + tests/audio_test.asm are the worked
; example):
;   1. Link with infrastructure/rom_template/lorom_tad.cfg (96KB, 3 banks:
;      the compiled song set is 27KB in AUDIO_DATA0). The KIT'S config
;      places TAD's 18 BSS bytes at $1DE0-$1DFF — the tail of the
;      game-array region, reserved from here on (see lib/macros/README.md).
;      TAD's two ZP bytes live at $FE-$FF.
;   2. Assemble + link TWO extra objects: engine/tad_audio_wrapper.asm
;      (the TAD ca65 API, needs -I lib/tad/audio-driver/ca65-api) and
;      assets/audio/tad_audio_data.asm (the loader+driver+songs blob).
;   3. The main ROM includes, in order: "tad-audio.inc" (API imports, needs
;      the same -I path), this file, and "tad_bridge.asm" at the bottom
;      with the other engine includes.
;
; Boot order: sf_coldstart -> sf_engine_init -> sf_audio_init (BEFORE NMI
; is enabled — the S-SMP must still be in its IPL state; sf_audio_init
; uploads the loader + driver synchronously, a few ms). Then call
; sf_audio_tick ONCE PER FRAME in the game loop (it drives the async song
; transfer and the command queue; without it nothing ever reaches the
; SPC700). Song loading is asynchronous: after sf_music, the song streams
; over ~10-60 frames (TAD_STATUS $02=loading, then $01=playing).
;
; TAD_STATUS mirror (engine state, absolute $016A): $00 loaded/paused,
; $01 playing, $02 loading, $FF error — poll it for "is the music going".
; CAVEAT: after sf_music_stop the SILENT song plays, so the status settles
; back at $01 — don't poll it for "did the stop land"; the WAV is silent.
;
; Requires (linked): engine/tad_bridge.asm + the two extra objects above.
; =============================================================================

.ifndef SF_AUDIO_INC
SF_AUDIO_INC = 1

; -----------------------------------------------------------------------------
; sf_audio_init — upload the SPC700 loader + driver; call once at boot.
; -----------------------------------------------------------------------------
; MUST run before NMI enable, after sf_coldstart/sf_engine_init (interrupts
; still disabled, S-SMP in IPL). Synchronous (spins until the driver is up).
; Leaves silence playing. Clobbers A, X, Y.
; WIDTH-RISK: enters any width; tad_bridge_init requires A8/I16; exits A16/I16.
.macro sf_audio_init
    sep #$20
    .a8
    rep #$10
    .i16
    jsr tad_bridge_init
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_audio_tick — drive the audio engine; call once per frame.
; -----------------------------------------------------------------------------
; Pumps TAD's command queue + the async song transfer and refreshes the
; TAD_STATUS mirror. Put it in the game loop (anywhere between
; sf_frame_begin and sf_frame_end). Skipping frames stalls song loading
; and delays commands — don't gate it on game state. Clobbers A, X, Y.
; WIDTH-RISK: enters any width; tad_bridge_process requires A8/I16; exits
; A16/I16.
.macro sf_audio_tick
    sep #$20
    .a8
    rep #$10
    .i16
    jsr tad_bridge_process
    rep #$30
    .a16
    .i16
.endmacro

; -----------------------------------------------------------------------------
; sf_music song — start a song (asynchronous load).
; -----------------------------------------------------------------------------
;   song  verbatim operand (`#Song::ode_to_joy`, or a DP word). Loading
;         streams over the following sf_audio_ticks; the previous song
;         stops immediately.
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; tad_music is A16-in/A16-out.
.macro sf_music sf_song
    rep #$30
    .a16
    .i16
    lda sf_song
    jsr tad_music
.endmacro

; -----------------------------------------------------------------------------
; sf_music_stop — stop the music (loads the silent song).
; -----------------------------------------------------------------------------
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; tad_music is A16-in/A16-out.
.macro sf_music_stop
    rep #$30
    .a16
    .i16
    lda #$FFFF
    jsr tad_music
.endmacro

; -----------------------------------------------------------------------------
; sf_sfx id [, pan] — queue a sound effect.
; -----------------------------------------------------------------------------
;   id   verbatim (`#SFX::menu_select`, or a DP word)
;   pan  optional verbatim, 0=left 64=center 128=right (default center)
; SFX play over the music; TAD assigns channels. DELIVERY rides
; sf_audio_tick: an SFX queued right before a long main-thread stall (a
; scene init's sf_level_load, ~1800 msets) sits silent until the next
; tick — tick once right after queueing if the timing matters.
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; tad_sfx is A16-in/A16-out.
.macro sf_sfx sf_id, sf_pan
    rep #$30
    .a16
    .i16
.ifblank sf_pan
    ldx #64                     ; center
.else
    ldx sf_pan
.endif
    lda sf_id
    jsr tad_sfx
.endmacro

; -----------------------------------------------------------------------------
; sf_music_vol volume — set music volume (0-127; clamped).
; -----------------------------------------------------------------------------
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; tad_music_vol toggles A8 internally and
; exits A16.
.macro sf_music_vol sf_vol
    rep #$30
    .a16
    .i16
    lda sf_vol
    jsr tad_music_vol
.endmacro

; -----------------------------------------------------------------------------
; sf_music_pause / sf_music_resume — pause and resume the current song.
; -----------------------------------------------------------------------------
; NOTE: the bridge sends TadCommand::PAUSE, which pauses the WHOLE driver —
; queued SFX stay queued and silent until resume (measured on the WAV gate;
; duck with sf_music_vol instead if you need SFX during a "pause" menu).
; Clobbers A, X, Y.
; WIDTH-RISK: asserts A16/I16 entry; the bridge fns toggle A8 internally and
; exit A16.
.macro sf_music_pause
    rep #$30
    .a16
    .i16
    jsr tad_music_pause
.endmacro

; WIDTH-RISK: asserts A16/I16 entry; exits A16 (same contract as pause).
.macro sf_music_resume
    rep #$30
    .a16
    .i16
    jsr tad_music_resume
.endmacro

.endif ; SF_AUDIO_INC
