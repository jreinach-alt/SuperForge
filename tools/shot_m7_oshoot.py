"""Render the m7_oshoot rail to PNGs (owner-validation renders, not a test).

Usage:  python3 tools/shot_m7_oshoot.py [outdir]

Boots build/m7_oshoot.sfc and photographs six ABSOLUTE frames: the settled
arena, the floor turned 45 degrees off the boot heading, a volley of bolts
climbing the screen, a crowded field of chasers closing in, and — added with the
2026-08-08 contact-strobe fix — THE HIT CUE, in both of its phases. No
assertions — this exists so a human (or the maintainer) can LOOK at the ROM the
suite just called green.

THE HIT CUE PAIR IS THE POINT OF THE LAST TWO. The rail used to answer a contact
by snapping the whole screen to near-black and pacing it back up, which reads
in play as the scene constantly flipping to black and fading in. The cue is now
an invulnerability blink on the hero's own sprite, so the two frames differ ONLY
in whether the 16x16 hero is drawn — the floor, the chasers and the brightness
are identical between them. Photographing both is what lets that be checked by
looking rather than by trusting this sentence.

LOCKSTEP, so the renders are a pure function of (rom md5, seed, input script):
`Machine(rom).advance(n, pad1=...)` parks on an exact emulated frame, so two runs
of this tool photograph the same instants and a visual diff between them means
something. No wall-clock anywhere.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "m7_oshoot.sfc"
SETTLE = 40             # past the fade-in, before the first wave beat
SPRITE_RAM = MemoryType.SnesSpriteRam
MO_PARK_Y = 0xF0        # where mo_park_slot puts a slot that is not drawn —
                        #   the hero's own y during the blink's dark phase


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        m.screenshot(str(out / "m7_oshoot_arena.png"))
        print("arena  ->", out / "m7_oshoot_arena.png")

        # 45 degrees off the boot heading. NOT 90: the arena is a square pillar
        # lattice over a square checker, so a quarter turn maps it almost onto
        # itself and the render would read as unchanged.
        m.advance(24, pad1={"up": True, "left": True})
        m.screenshot(str(out / "m7_oshoot_turned.png"))
        print("turned ->", out / "m7_oshoot_turned.png")

        # A volley, walking so the chasers cannot close and eat one.
        hold = {"right": True}
        fire = {"right": True, "a": True}
        for _ in range(4):
            m.advance(2, pad1=fire)
            m.advance(4, pad1=hold)
        m.screenshot(str(out / "m7_oshoot_firing.png"))
        print("firing ->", out / "m7_oshoot_firing.png")

        # A populated field, WALKED CLEAR OF. Standing still is the wrong drive
        # for this frame: the chasers converge on a stationary hero, the first
        # to touch him knocks him back to the arena centre and the rest follow,
        # so the picture ends up with one chaser and a hero who has teleported.
        # Measured on the render this produces, with the generator's own _is_red
        # band predicate: 180 idle frames then 20 of RIGHT puts THREE on screen
        # at once — connected components at (210,40), (128,73) and (124,124),
        # stable at every minimum-blob size from 1 px to 10 px — spread across
        # the floor, which is what the wave ring looks like when it is working.
        m.advance(180 - SETTLE - 24 - 24)
        m.advance(20, pad1={"right": True})
        m.screenshot(str(out / "m7_oshoot_swarm.png"))
        print("swarm  ->", out / "m7_oshoot_swarm.png")

    # ---- THE HIT CUE, both phases -----------------------------------------
    # A second Machine rather than more frames on the first: these two want a
    # drive of their own (walk into the pillar until a chaser catches you) and
    # a clean absolute frame count, not whatever the four shots above left the
    # core parked on.
    #
    # The blink PHASE is found by reading the hero's OAM slot rather than by
    # counting frames to it. Both are deterministic, but a slot read says what
    # it is looking for — MO_PARK_Y at slot 0 means "not drawn this frame" — so
    # a retune of the grace window or the blink period moves these renders with
    # the rail instead of silently photographing the wrong instant.
    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        m.advance(200, pad1={"right": True})     # hard against the pillar face;
                                                 #   the first contact lands here
        # THE PAIR IS TAKEN AFTER THE TELEPORT, ON PURPOSE. The contact frame is
        # itself a blink-off frame, but it is also the frame the knockback moves
        # the whole world on — so pairing it with the next lit frame would show
        # the hero appearing AND the arena jumping, and the two changes could not
        # be told apart by looking. Skipping to the second off-phase of the same
        # grace window gives a pair a few frames apart with no teleport between
        # them and a hero pinned against the pillar: the floor is still, the
        # chasers have crept half a pixel, and the ONLY thing that changes is
        # whether the hero is drawn. That is the claim, so that is the picture.
        # ...and the pair is walked to with the pad RELEASED. The rail is
        # stand-and-shoot — an idle hero keeps his facing and the world does not
        # move — so letting go freezes the floor for the two captures. Holding a
        # direction instead would slide the arena a few pixels between them and
        # ~37% of the frame would differ, which buries the one change the pair
        # exists to show. (The hero CAN walk away during his grace now; that is
        # the point of the chase fix, and it is exactly what makes it the wrong
        # drive for this picture.)
        def phase_is(off, pad, budget=120):
            """Advance to the next frame whose hero slot is/is not parked."""
            for _ in range(budget):
                y = m.read_bytes(SPRITE_RAM, 0, 4)[1]
                if (y == MO_PARK_Y) == off:
                    return True
                m.advance(1, pad1=pad)
            return False

        GO, STAND = {"right": True}, {}
        ok = (phase_is(True, GO)        # the contact frame — the cue's first off
              and phase_is(False, STAND)    # ...the lit run that follows it
              and phase_is(True, STAND))    # ...and the NEXT off run, past the
                                            #    teleport, with the world still
        if not ok:
            raise SystemExit("no hit cue in the window — the drive never got "
                             "caught, so there is nothing to photograph")
        m.screenshot(str(out / "m7_oshoot_hit_cue_blink_off.png"))
        print("cue/off ->", out / "m7_oshoot_hit_cue_blink_off.png")
        if not phase_is(False, STAND):
            raise SystemExit("the hero never came back after the blink")
        m.screenshot(str(out / "m7_oshoot_hit_cue_blink_on.png"))
        print("cue/on  ->", out / "m7_oshoot_hit_cue_blink_on.png")

    # ---- THE RESTORED CONTROLS ----------------------------------
    # FOUR FRAMES OF ONE CONTINUOUS TURN, and they are the point of this work.
    # The rail used to SNAP the heading to one of eight compass points, and the
    # resulting 45-degree jolt is unreadable in play. The
    # heading now steps 3 of 256 units per held frame, so these four frames are
    # 21 units apart (~30 degrees) and show a floor that is sweeping rather than
    # jumping. Deliberately NOT taken at multiples of 32: every one of these is
    # an orientation the deleted table could not produce, so a reader can see
    # that the in-between angles exist at all.
    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        for i, name in enumerate(("a", "b", "c", "d")):
            if i:
                m.advance(7, pad1={"left": True})       # 7 x 3 = 21 units
            p = out / f"m7_oshoot_turn_sweep_{name}.png"
            m.screenshot(str(p))
            print(f"sweep{i} ->", p)

    # ---- A KILL, AND THE SCORE THAT MOVED ---------------------------------
    # The first wave beat puts its chaser at ring offset 0 — straight up the
    # world, which at the boot heading is straight up the SCREEN — so the boot
    # facing already aims at it and one press of A is the whole drive.
    #
    # TWO FRAMES, because the claim is a CHANGE: the readout before the shot and
    # the death flash with the readout moved. A kill used to be a chaser
    # vanishing between two frames with nothing else on screen altering, which
    # is indistinguishable from it wandering off; it now stops where the bolt
    # found it and flashes in the score's own colour while the digits tick.
    with Machine(str(ROM)) as m:
        m.advance(SETTLE)
        m.advance(60)                                   # past the first beat
        m.screenshot(str(out / "m7_oshoot_score_before.png"))
        print("score/0 ->", out / "m7_oshoot_score_before.png")
        m.advance(2, pad1={"a": True})                  # one bolt, on A's edge
        # Walk to the flash by READING for it rather than counting frames to it,
        # for the reason the hit-cue pair does: a retune of the bolt speed or the
        # death window then moves this render with the rail instead of silently
        # photographing an empty floor. The enemy slots are OAM 1..6 and byte 3
        # of an entry is its attribute; $36 is priority 3 | OBJ palette 3, the
        # score band, which ONLY a dying chaser and the HUD digits ever carry.
        ATTR_SCORE = 0x36
        found = False
        for _ in range(90):
            m.advance(1)
            oam = m.read_bytes(SPRITE_RAM, 0, 32)
            if any(oam[s * 4 + 3] == ATTR_SCORE for s in range(1, 7)):
                found = True
                break
        if not found:
            raise SystemExit("the shot never connected — nothing to photograph")
        m.screenshot(str(out / "m7_oshoot_kill_flash.png"))
        print("kill    ->", out / "m7_oshoot_kill_flash.png")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/mo_shots"))
