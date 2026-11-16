"""pixelate_actor.py — Blender DATA frames -> indexed 16x16-class actor sprites.

Ported from SUPERFORGE GT (jreinach-alt/sf-gt @ 82add51,
art/fgt/cars/pixelate.py; first-party, zlib) and generalised from one car role
table to the per-family ROLE TABLES in roles.toml. Spec: docs/dungeons/13.

Input: a supersampled RGB frame written by the renderer, whose channels are
DATA, not colour:  R = sunlight (0..255), G = material id, B = ambient
occlusion / open sky. Output: an index image in the family's palette layout.

How a sprite pixel is decided (no colour matching anywhere — the sf-gt rule):
  1. COVER. A sprite pixel spans ss x ss raw samples. Under `cover` of them on
     the model -> empty (or drop shadow, if the shadow material fills it).
  2. ROLE. The samples vote by material, weighted by the role's `vote`, so a
     2-sample eye beats 30 samples of cloak only where it should.
  3. STEP. The winning material's samples are averaged for brightness and that
     picks the step on the role's ramp (or the role's fixed index).
  4. CLEAN-UP. A lone ramp step that disagrees with >= 3 agreeing neighbours
     folds into them (sf-gt's despeckle), within one ramp only.
  5. OUTLINE + SHADOW. Empty pixels 4-adjacent to the model and shadow pixels
     become the outline index — unless the family turns the ring off.
  6. FIT. A model or shadow pixel outside the box is an ERROR, never a crop.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MAT_NONE, MAT_SHADOW = 0, 1
SUN, SKY = 1.02, 0.22          # sf-gt's brightness mix: sunlight + a share of open sky


@dataclass
class Family:
    name: str
    roles: list
    outline: int
    shadow: int
    cover: float
    ring: bool = True


def load_family(name: str, path: Path | None = None) -> Family:
    d = tomllib.loads((path or HERE / "roles.toml").read_text())["family"][name]
    seen = {}
    for r in d["role"]:
        if r["material"] in (MAT_NONE, MAT_SHADOW) or r["material"] in seen:
            raise ValueError(f"{name}: material {r['material']} reserved or duplicated")
        seen[r["material"]] = r["name"]
        if r["kind"] == "ramp" and len(r["thresholds"]) != r["hi"] - r["lo"]:
            raise ValueError(f"{name}.{r['name']}: need {r['hi'] - r['lo']} thresholds")
    return Family(name, d["role"], d["outline"], d["shadow"], d["cover"], d.get("ring", True))


def _blocks(a: np.ndarray, ss: int) -> np.ndarray:
    h, w = a.shape[0] // ss, a.shape[1] // ss
    if (h * ss, w * ss) != a.shape[:2]:
        raise ValueError(f"raw frame {a.shape[:2]} is not a multiple of ss={ss}")
    return a.reshape(h, ss, w, ss).transpose(0, 2, 1, 3).reshape(h, w, ss * ss)


def quantise(raw: np.ndarray, ss: int, fam: Family):
    """raw HxWx3 uint8 -> (index image, model mask, shadow mask) at sprite size."""
    shade = _blocks(SUN * raw[..., 0] / 255.0 + SKY * raw[..., 2] / 255.0, ss)
    ids = _blocks(raw[..., 1], ss)
    n = ss * ss
    mats = [r["material"] for r in fam.roles]
    counts = np.stack([(ids == m).sum(-1) for m in mats], -1)
    cov = counts.sum(-1) / n
    win_i = (counts * np.array([r["vote"] for r in fam.roles])).argmax(-1)
    win = np.array(mats)[win_i]
    model = cov >= fam.cover
    wmask = ids == win[..., None]
    lum = (shade * wmask).sum(-1) / np.maximum(wmask.sum(-1), 1)
    out = np.zeros(win.shape, np.uint8)
    for i, r in enumerate(fam.roles):
        sel = win_i == i
        if r["kind"] == "ramp":
            out[sel] = (r["lo"] + np.digitize(lum[sel], r["thresholds"])).astype(np.uint8)
        else:
            out[sel] = r["index"]
    out[~model] = 0
    shadow = ~model & ((cov + (ids == MAT_SHADOW).sum(-1) / n) >= 0.5)
    return out, model, shadow


def _nb4(a: np.ndarray) -> np.ndarray:
    p = np.pad(a, 1, mode="edge")
    return np.stack([p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]], 0)


def despeckle(img: np.ndarray, fam: Family) -> np.ndarray:
    """sf-gt step 3: fold a lone ramp step into >= 3 agreeing neighbours."""
    out = img.copy()
    nb = _nb4(img)
    for r in fam.roles:
        if r["kind"] != "ramp":
            continue
        lo, hi = r["lo"], r["hi"]
        inr = (img >= lo) & (img <= hi)
        for v in range(lo, hi + 1):
            agree = (nb == v).sum(0)
            fix = inr & (img != v) & (agree >= 3) & ~(nb == img).any(0)
            out[fix] = v
    return out


def finish(img, model, shadow, fam: Family) -> np.ndarray:
    out = despeckle(img, fam)
    out[shadow & ~model] = fam.shadow
    if fam.ring:
        out[_nb4(model).any(0) & ~model] = fam.outline
    return out


def fit(img: np.ndarray, solid: np.ndarray, margin: int, box_w: int, box_h: int,
        label: str) -> np.ndarray:
    """Cut the box out of the rendered canvas. Solid (model/shadow) pixels
    outside it are an error; outline-only spill is dropped (sf-gt crop())."""
    inner = img[margin:margin + box_h, margin:margin + box_w]
    spill = solid.copy()
    spill[margin:margin + box_h, margin:margin + box_w] = False
    if spill.any():
        ys, xs = np.nonzero(spill)
        raise ValueError(f"{label}: {len(ys)} model px outside the {box_w}x{box_h} box "
                         f"(x {xs.min() - margin}..{xs.max() - margin}, "
                         f"y {ys.min() - margin}..{ys.max() - margin})")
    return inner


def pixelate(raw: np.ndarray, ss: int, fam: Family, margin: int, box: tuple,
             label: str) -> np.ndarray:
    img, model, shadow = quantise(raw, ss, fam)
    img = finish(img, model, shadow, fam)
    return fit(img, model | shadow, margin, box[0], box[1], label)


def foot_row(sprite: np.ndarray, outline: int) -> int:
    """Lowest row holding a non-outline, non-empty pixel: where the model
    meets the ground. 13 §5 uses it to check the anchor never drifts."""
    rows = np.nonzero(((sprite != 0) & (sprite != outline)).any(1))[0]
    if not len(rows):
        raise ValueError("empty sprite")
    return int(rows.max())


def shimmer(a: np.ndarray, b: np.ndarray) -> int:
    """Pixels that differ between two frames — the 'boiling' metric (13 §5)."""
    return int((a != b).sum())
