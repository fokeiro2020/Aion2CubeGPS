"""Screen-only, color-cluster glow tracker.

No game memory or processes are accessed.  User-supplied cube screenshots are
kept as optional appearance references, but are never treated as proof that
an arbitrary match is a cube.  Camera position and apparent image size are
NOT game-world distance.
"""
import math
from pathlib import Path

import cv2
import numpy as np


def exclude_window(small_bgr, monitor, scale, window_rect, pad=12):
    """Black out this app's own screen pixels to stop feedback detection."""
    if window_rect is None:
        return small_bgr
    left, top, right, bottom = window_rect
    origin_x, origin_y = monitor["left"], monitor["top"]
    h, w = small_bgr.shape[:2]
    x0 = max(0, math.floor((left - pad - origin_x) / scale))
    y0 = max(0, math.floor((top - pad - origin_y) / scale))
    x1 = min(w, math.ceil((right + pad - origin_x) / scale))
    y1 = min(h, math.ceil((bottom + pad - origin_y) / scale))
    if x0 < x1 and y0 < y1:
        small_bgr[y0:y1, x0:x1] = 0
    return small_bgr


def load_references(folder):
    """Load optional user-provided close/distant cube screenshots."""
    refs = []
    for path in Path(folder).glob('cube_*.png'):
        im = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if im is not None and min(im.shape[:2]) >= 16:
            refs.append(im)
    return refs


def _reference_score(patch, references):
    """Low-weight appearance bonus. Never use template scores as proof.

    These are small, angle-dependent screenshots; their similarity is not
    reliable enough to reject a real cube with a different rotation.
    """
    if not references or min(patch.shape[:2]) < 8:
        return 0.0
    small = cv2.resize(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), (40, 40),
                       interpolation=cv2.INTER_AREA)
    best = 0.0
    for ref in references:
        gray = cv2.resize(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), (40, 40),
                          interpolation=cv2.INTER_AREA)
        for k in (0, 1, 2, 3):
            rotated = np.rot90(gray, k).copy()
            score = float(cv2.matchTemplate(small, rotated,
                                            cv2.TM_CCOEFF_NORMED)[0, 0])
            if np.isfinite(score):
                best = max(best, score)
    return max(0.0, best)


def detect_glow(small_bgr, target_rgb, tolerance, min_pixels=6,
                min_brightness=90, near=None, search_radius=None,
                references=()):
    """Return (screen_x, screen_y, apparent_size, matched_color_pixels).

    Prefer coherent, roughly cube-shaped COLOR COMPONENTS, not the single
    brightest matching pixel (v4's issue). If tracking an F8 sample or an
    existing object, stay nearby and refuse to jump across the game screen.
    Apparent size is *not* distance in meters.
    """
    if target_rgb is None:
        return None
    h, w = small_bgr.shape[:2]
    bgr = small_bgr.astype(np.int16, copy=False)
    tr, tg, tb = target_rgb
    diff = (np.abs(bgr[:, :, 2] - tr) + np.abs(bgr[:, :, 1] - tg)
            + np.abs(bgr[:, :, 0] - tb))
    brightness = bgr.mean(axis=2)
    mask = np.uint8((diff < tolerance * 3) & (brightness > min_brightness))
    if int(mask.sum()) < min_pixels:
        return None

    # Close tiny gaps between rune lines, but don't connect faraway objects.
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    n, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return None
    radius = search_radius if search_radius is not None else max(45, w * .20)
    candidates = []
    for label in range(1, n):
        x, y, cw, ch, area = [int(v) for v in stats[label]]
        if area < min_pixels or min(cw, ch) < 3:
            continue
        # Reject HUD bars, thin wires, and huge uniform overlays.
        ratio = cw / max(ch, 1)
        if not .38 <= ratio <= 2.65 or cw > w*.32 or ch > h*.50:
            continue
        cx, cy = centers[label]
        if near is not None:
            distance = math.hypot(cx-near[0], cy-near[1])
            if distance > radius:
                continue
        else:
            distance = 0
        # Original RGB pixels (not morphological fill) must be present.
        colored = int(np.count_nonzero((labels[y:y+ch, x:x+cw] == label) &
                     (diff[y:y+ch, x:x+cw] < tolerance*3)))
        if colored < min_pixels:
            continue
        aspect_weight = math.exp(-abs(math.log(max(ratio, 0.01))) * .35)
        size_weight = math.sqrt(area)
        # Prefer returning to the same apparent position, and make large
        # coherent color clusters strongly preferable to tiny background dots.
        motion_weight = 1 / (1 + distance/max(radius, 1)*1.5)
        score = size_weight * aspect_weight * motion_weight
        candidates.append((score, float(cx), float(cy), area, colored,
                           (x, y, cw, ch)))

    if not candidates:
        return None
    # Verify only the strongest few color clusters to keep the UI responsive.
    best = sorted(candidates, key=lambda e: e[0], reverse=True)[:5]
    if references:
        rescored = []
        for score, cx, cy, area, colored, (x, y, cw, ch) in best:
            pad = max(3, round(max(cw, ch)*.10))
            patch = small_bgr[max(0,y-pad):min(h,y+ch+pad),
                               max(0,x-pad):min(w,x+cw+pad)]
            similarity = _reference_score(patch, references)
            rescored.append((score*(1+.15*similarity), cx, cy, area, colored))
        _, cx, cy, area, color_count = max(rescored, key=lambda e:e[0])
    else:
        _, cx, cy, area, color_count, _ = best[0]
    # Scales naturally with the visible colored cluster; not a range estimate.
    apparent_size = min(1., math.sqrt(area)/30.)
    return cx, cy, apparent_size, color_count
