"""Closed-loop breaker WIN bot (shared by test_breaker.py's win gate).

The breaker is a deterministic billiard with fully-known rules
(templates/breaker/main.asm): each frame moves the ball per-axis with
two leading-edge probes, bricks break-and-reflect on probe hit, and the
paddle's 4 english zones pick the outgoing VX from where the ball's
centre struck. This bot mirrors those rules EXACTLY in a bot-side
simulation, evaluates the full flight for each of the 4 english choices
(2-ply lookahead when no first-ply choice breaks a brick), and drives
the chosen catch offset with frame-stepped input. The aiming is honest:
the bot only reads machine state and chooses paddle input — the game
ROM's rules are untouched.

Reads: WRAM ball/paddle state (steering), VRAM BG1 tilemap (live brick
map), the $7E:E01x debug mirrors (game-state dispatch).
"""
import time

from infrastructure.test_harness.mesen_runner import MemoryType

WR = MemoryType.SnesWorkRam
VR = MemoryType.SnesVideoRam
BG1_MAP = 0xB000
BRICK_TILES = (2, 3, 4, 5)
ZONES = {-2: 2, -1: 8, 1: 14, 2: 21}    # outgoing VX -> dx (bx+4-px) at catch
DBG_BRICKS = 0xE014
DBG_STATE = 0xE016


# ---------------------------------------------------------------------------
# exact mirror of the ROM's collision rules (move_ball_x/y + probe_point)
# ---------------------------------------------------------------------------

def _blocked(x, y, bricks):
    """probe_point: 1 = wall, 2 = live brick, 0 = clear."""
    cx, cy = x >> 3, y >> 3
    if cy == 2:                          # top wall row
        return 1
    if (cx == 0 or cx == 31) and 3 <= cy <= 27:
        return 1                         # side walls
    if (cy, cx) in bricks:
        return 2
    return 0


def sim_flight(bx, by, vx, vy, bricks, max_frames=4000):
    """Simulate until the next catch opportunity (falling, BY >= 194).

    Returns (bricks_broken, frames, bx_at_catch, bricks_after). Operates
    on a copy of the brick set.
    """
    b = set(bricks)
    broken = 0
    for t in range(1, max_frames + 1):
        nx = bx + vx                     # move_ball_x
        lead = nx + 7 if vx > 0 else nx
        hit = False
        for py in (by + 1, by + 6):
            h = _blocked(lead, py, b)
            if h == 2:
                b.discard((py >> 3, lead >> 3))
                broken += 1
                hit = True
            elif h == 1:
                hit = True
        if hit:
            vx = -vx
        else:
            bx = nx
        ny = by + vy                     # move_ball_y
        lead = ny + 7 if vy > 0 else ny
        hit = False
        for px in (bx + 1, bx + 6):
            h = _blocked(px, lead, b)
            if h == 2:
                b.discard((lead >> 3, px >> 3))
                broken += 1
                hit = True
            elif h == 1:
                hit = True
        if hit:
            vy = -vy
        else:
            by = ny
        if vy > 0 and by >= 194:
            return broken, t, bx, b
    return broken, max_frames, bx, b


def choose_english(bx_catch, bricks):
    """Outgoing VX maximizing brick yield (2-ply when first ply is dry)."""
    best, best_key = 1, None
    for v in (-2, -1, 1, 2):
        n1, t1, bx1, b1 = sim_flight(bx_catch, 192, v, -2, bricks)
        if n1 > 0:
            key = (-n1 / t1, t1)
        else:
            best2, t2best = 0, 4000
            for v2 in (-2, -1, 1, 2):
                n2, t2, _, _ = sim_flight(bx1, 192, v2, -2, b1)
                if (n2 / max(t2, 1)) > (best2 / max(t2best, 1)):
                    best2, t2best = n2, t2
            key = (0, t1 + t2best - best2 * 100)
        if best_key is None or key < best_key:
            best, best_key = v, key
    return best


# ---------------------------------------------------------------------------
# the driver
# ---------------------------------------------------------------------------

def _u16(b, i):
    return b[i] | (b[i + 1] << 8)


def _s16(b, i):
    v = _u16(b, i)
    return v - 0x10000 if v >= 0x8000 else v


class WinBot:
    """Frame-stepped closed-loop driver to a full 180-brick clear."""

    def __init__(self, runner):
        self.r = runner
        self.frames = 0

    def ball_state(self):
        b = self.r.read_bytes(WR, 0x32, 10)     # PX BX BY VX VY (DP $32..)
        return (_u16(b, 0), _u16(b, 2), _u16(b, 4), _s16(b, 6), _s16(b, 8))

    def step(self, n=1, **btn):
        self.r.frame_step(n, **btn)
        self.frames += n

    def read_bricks_vram(self):
        cells = set()
        for row in range(5, 11):
            raw = self.r.read_bytes(VR, BG1_MAP + row * 64, 64)
            for c in range(1, 31):
                if raw[c * 2] in BRICK_TILES:
                    cells.add((row, c))
        return cells

    def steer_to(self, target_px, frames_avail):
        """Drive the paddle to target_px while the descent plays out."""
        remaining = frames_avail
        while remaining > 0:
            px = _u16(self.r.read_bytes(WR, 0x32, 2), 0)
            d = target_px - px
            if abs(d) > 2:
                btn = dict(right=True) if d > 0 else dict(left=True)
                n = min(remaining, max(1, min(16, abs(d) // 3)))
            else:
                btn = {}
                n = min(remaining, 16)
            self.step(n, **btn)
            remaining -= n

    def run(self, frame_cap=40000, wall_cap=400.0):
        """Drive WAIT -> launch -> rally until STATE == 3 (win).

        Returns True on win. Raises on game over (a lost ball means the
        catch model broke). The caller owns debug_break/debug_resume.
        """
        r = self.r
        t0 = time.time()
        while self.frames < frame_cap and time.time() - t0 < wall_cap:
            gstate = r.read_u16(WR, DBG_STATE)
            if gstate == 3:
                return True
            if gstate == 2:
                raise AssertionError(
                    f"bot lost all balls at frame {self.frames} — "
                    "paddle catch model broke"
                )
            if gstate == 0:                  # WAIT: launch
                self.step(1, a=True)
                self.step(1)
                continue
            px, bx, by, vx, vy = self.ball_state()
            if vy > 0 and by >= 100:
                # falling below the band: plan the catch. VRAM is safe to
                # read here — the last possible brick break was >= 50
                # frames ago (the ball has to fall from the band), so the
                # tilemap DMA has long committed.
                bricks = self.read_bricks_vram()
                x, y, v, t = bx, by, vx, 0   # walls-only descent
                while y < 194:
                    nx = x + v
                    lead = nx + 7 if v > 0 else nx
                    if lead >= 248 or lead < 8:
                        v = -v
                    else:
                        x = nx
                    y += 2
                    t += 1
                zone_vx = choose_english(x, bricks)
                tgt = min(max(x + 4 - ZONES[zone_vx], 8), 224)
                if t > 3:
                    self.steer_to(tgt, t - 3)
                for _ in range(12):          # walk the catch itself
                    self.step(1)
                    _, _, _, _, vy2 = self.ball_state()
                    if vy2 < 0:
                        break
                continue
            # rising / in the band: batch big, shadow the ball loosely
            tgt = min(max(bx - 8, 8), 224)
            d = tgt - px
            btn = {}
            if d > 3:
                btn = dict(right=True)
            elif d < -3:
                btn = dict(left=True)
            self.step(12, **btn)
        return False
