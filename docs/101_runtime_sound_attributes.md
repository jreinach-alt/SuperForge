# 101 — Changing a sound attribute while it plays

**The vendored audio driver could not do this, and now it can.** This
document is what the capability is, how to use it, what it costs, and the
four things it still cannot do.

## The hole

Terrific Audio Driver's S-CPU interface is eleven IO commands. Every one of
them is **global** (pause, main volume, the two global volumes, stop effects)
or **per-song** (music-channel mask, song timer). Sound effects are queued by
*id and pan* — `Tad_QueuePannedSoundEffect` takes nothing else.

So there was no way to make a sound respond to game state *while it played*.
Not an engine note that tracks speed, not a doppler on a passing object, not
a siren, not a tape-stop. Everything had to be pre-baked into a song or an
effect and then triggered.

That was not a version lag. Upstream at **v0.4.2 — 96 commits past our pin —
still has `TAD_IO_VERSION = 20`, `N_COMMANDS = 11` and the same eleven
commands.** Checked before forking, precisely so the cost of forking was
weighed against a free alternative that did not exist.

## What was actually missing was the doorway, not the room

The driver **already** carries this, in its per-channel state:

```
; i16 VxPITCH offset added to every play_note or portamento instruction
channelSoA_detune_l : [u8 : N_CHANNELS]
channelSoA_detune_h : [u8 : N_CHANNELS]
```

It is already applied on every note, it already persists across notes and
subroutine calls, and it is already exercised by song bytecode
(`set_detune`, MML `D<-16383..+16383>`). It simply had no IO command.

**Measured before the fork was written**, because "the docs say it works" is
not evidence: adding `D+600` to a drone channel in MML moved that voice's
`VxPITCH` from **1203 to exactly 1803** and held it. The mechanism was real;
only the access was missing.

## The command

`SET_CHANNEL_DETUNE` = IO command **22**, in the first free slot. The command
field is four bits — sixteen slots, of which upstream used eleven — so 24,
26, 28 and 30 remain.

```
parameter0:  cccccnnn      nnn   = channel index (0..7)
                           ccccc = detune bits 8..12
parameter1:  detune bits 0..7
```

The detune is **13-bit two's complement, −4096..+4095** in `VxPITCH` units,
sign-extended into the i16 the channel already stores. Packed this way
because the protocol carries exactly two parameter bytes and the channel index
must travel *with* the value: one command, one driver tick, no latched
selection state to get out of step.

From a scene, in A16 — build the parameter with a masked result so `tax`
transfers a defined 16-bit value rather than whatever the high byte held
(the A8/I16 `tax` trap this repo documents at length):

```asm
    lda z:US_SOME_STATE
    and #$000F                      ; 0..15 -> detune bits 8..11, sign clear
    asl a
    asl a
    asl a                           ; into the ccccc field
    ora #$0001                      ; channel 1
    tax                             ; X = parameter 0
    ldy #$0000                      ; Y = parameter 1 (detune low byte)
    sep #$20
    .a8
    lda #TadCommand::SET_CHANNEL_DETUNE
    jsr Tad_QueueCommand
    rep #$20
    .a16
```

**Measured on the shipped patch**, driven once a frame from a scene tick: a
fixed +600 moved the drone 1203 → 1803 (exactly the requested offset), and
feeding the scene's own accumulator in swept it 1203 → 4275 → 2227.

## What it costs

**One command per frame, total, across the whole game.** `Tad_QueueCommand`
holds ONE command and returns carry clear if the queue is full, so a rail
bending two channels alternates and each updates at 30 Hz. This is the real
budget constraint on the feature, and it is the protocol's, not ours.

**A forked driver**, which is a standing maintenance cost rather than a
one-off: upstream updates become merges, and the Zlib licence obliges us to
mark the alteration (`vendor/tad/README.md`, `docs/92` §5.5, the patch
header, and the code itself). The fork is one patch touching three upstream
files.

**`TAD_IO_VERSION` 20 → 21**, which is what makes it carryable: the generated
`tad_audio_data.asm` link-asserts against `tad-audio.s`, and the Rust
compiler crate asserts on it twice. A patched driver with an unpatched API
refuses to link *by name* — observed doing exactly that during the port —
rather than producing a subtly wrong ROM.

## The channel field reaches the music channels only

Three bits addresses 0..7, which is exactly `N_MUSIC_CHANNELS` — every music
channel A..H. The driver's channel array is `N_CHANNELS = 10`: the two SFX
channels are 8 and 9 and **cannot be addressed by this command**.

That is a deliberate trade, not an oversight. Widening the field to four bits
would reach them at the cost of halving the detune range to ±2048, and
bending a sound effect mid-flight is the niche case — an effect is a one-shot
measured in tens of ticks, while the thing game state wants to drive is a
sustained voice. If a rail ever needs it, the fourth bit is available and the
range is the price.

## Five things this does NOT give you

1. **It is not `play_pitch`.** Detune is applied to `play_note` and
   portamento only, matching the bytecode instruction's documented behaviour.
   A channel scored with `P` play-pitch commands ignores it.
2. **It is not volume, pan, or timbre.** Those have their own per-channel
   state in the driver and would each need their own command. The four free
   slots are there; this one was cut first because pitch is what game state
   most often wants to drive.
3. **It does not survive a song load.** Loading a song resets detune, so a
   rail that bends pitch must re-issue after any `Tad_LoadSong`.
4. **It cannot reach an SFX channel** — see above; three bits, music
   channels only.
5. **It does not make an engine note by itself.** A continuously-pitched
   voice still has to be scored — a sustained looped note on a music channel
   — and this bends it. What the command removes is the impossibility, not
   the composition.
