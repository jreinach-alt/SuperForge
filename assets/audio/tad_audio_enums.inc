;; Song and Sound Effect ca65 enums for example-project.terrificaudio.
;;
;; Automatically generated using `tad-compiler ca65-enums` or `tad-compiler ca65-export`.
;;
;; This file MUST BE recreated if song list or sound effect export order changes.
;;


LAST_SONG_ID = 24
N_SOUND_EFFECTS = 19

;; Song enum.
;; Input argument for `Tad_LoadSong`
.enum Song
  BLANK = 0 ; blank (silent) song
  gimo_297 = 1
  ode_to_joy = 2
  chords = 3
  chords_transpose = 4
  broken_chord = 5
  quantize_with_temp_gain = 6
  early_release = 7
  echo = 8
  samples = 9
  play_pitch = 10
  portamento = 11
  continuous_portamento = 12
  vibrato = 13
  tremolo = 14
  volume_slide = 15
  pan = 16
  panbrello = 17
  pan_slide = 18
  play_noise = 19
  multi_channel_noise = 20
  detune = 21
  pitch_modulation = 22
  fir = 23
  bc_asm_in_mml = 24
.endenum


;; Sound Effects enum.
;; Input argument for `Tad_QueueSoundEffect` and `Tad_QueuePannedSoundEffect`
.enum SFX
  ; high-priority sound effects
  player_hurt_low_health = 0
  ; normal-priority sound effects
  menu_cursor = 1
  menu_select = 2
  menu_incorrect = 3
  player_hurt = 4
  jump = 5
  vibrato_alarm = 6
  play_samples_bytecode = 7
  spawn_item = 8
  collect_coin = 9
  robot_notices_player = 10
  robot_ascend = 11
  robot_fires_laser = 12
  fire_arrow = 13
  noise = 14
  sfx_calling_subroutine_asm = 15
  sfx_calling_subroutine_mml = 16
  ; low-priority sound effects
  low_priority_beep = 17
  low_priority_long = 18
.endenum
