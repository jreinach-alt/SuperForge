;; Song and Sound Effect ca65 enums for slice_b.terrificaudio.
;;
;; Automatically generated using `tad-compiler ca65-enums` or `tad-compiler ca65-export`.
;;
;; This file MUST BE recreated if song list or sound effect export order changes.
;;


LAST_SONG_ID = 6
N_SOUND_EFFECTS = 16

;; Song enum.
;; Input argument for `Tad_LoadSong`
.enum Song
  BLANK = 0 ; blank (silent) song
  slice_b_song = 1
  drive_song = 2
  circuit_song = 3
  far_ridge_song = 4
  foundry_song = 5
  shallow_water_song = 6
.endenum


;; Sound Effects enum.
;; Input argument for `Tad_QueueSoundEffect` and `Tad_QueuePannedSoundEffect`
.enum SFX
  ; high-priority sound effects
  room_a_ambience = 0
  room_b_ambience = 1
  beam_end = 2
  beam_fire = 3
  ; normal-priority sound effects
  explosion = 4
  hit = 5
  laser = 6
  jump = 7
  pickup = 8
  chime = 9
  select = 10
  thud = 11
  wave_break = 12
  ; low-priority sound effects
  footstep = 13
  skid = 14
  wind = 15
.endenum
