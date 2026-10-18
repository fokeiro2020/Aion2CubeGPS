"""Rotation-aware screen tracker, trained from user-provided cube recordings.

Offline reference masks describe the cube's multiple rotating silhouettes; they
contain no gameplay account data. Never reads game memory or changes the game.
Returns screen direction and relative apparent size -- NOT world coordinates.
"""
from pathlib import Path
import math
import cv2
import numpy as np

CUBE_HUE_MAX = 18
REFERENCE_SIZE = 40


def warm_mask(bgr):
    """Warm, saturated red/orange glow; explicitly exclude purple foliage."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return (cv2.inRange(hsv, (0, 92, 100), (CUBE_HUE_MAX, 255, 255)) |
            cv2.inRange(hsv, (173, 92, 100), (179, 255, 255)))


def appearance_image(bgr):
    """Brightness of red-orange runes, ignoring unrelated green/purple colors."""
    b, g, r = cv2.split(bgr.astype(np.float32))
    red_excess = np.clip(r - np.maximum(b, g) * 0.65, 0, 255)
    return red_excess * (warm_mask(bgr).astype(np.float32) / 255.0)


def normalized_patch(bgr, rect, size=REFERENCE_SIZE):
    """Center a cube candidate, preserving the shape under rotation."""
    x, y, w, h = rect
    H, W = bgr.shape[:2]
    side = max(w, h) * 1.30
    cx, cy = x + w/2., y + h/2.
    x0 = max(0, int(cx-side/2)); y0 = max(0, int(cy-side/2))
    x1 = min(W, int(cx+side/2)); y1 = min(H, int(cy+side/2))
    if x1 <= x0 or y1 <= y0:
        return None
    heat = appearance_image(bgr[y0:y1, x0:x1])
    return cv2.resize(heat, (size,size), interpolation=cv2.INTER_AREA)


def load_rotation_patterns(folder):
    """Read compact one-channel reference patterns from user-recorded clips."""
    refs = []
    for p in sorted(Path(folder).glob('*.png')):
        ref = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if ref is not None and ref.shape == (REFERENCE_SIZE, REFERENCE_SIZE):
            refs.append(ref.astype(np.float32))
    return refs


def suppress_hud(mask, anchor=None):
    """Prevent UI sprites, minimap, skill icons and status bars being cubes.

    When anchored via F8, a cue near an edge is still possible. Only the
    center view is scanned without a manually set anchor.
    """
    h, w = mask.shape
    # Captures include bottom action bar and right quest/minimap widget.
    # Mask these UI areas regardless of anchor: they are not cube objects.
    mask[:int(h * .060), :] = 0
    mask[int(h * .88):, :] = 0
    mask[:, int(w * .85):] = 0
    return mask


def _candidate_rects(bgr, anchor):
    h, w = bgr.shape[:2]
    mask = warm_mask(bgr)
    suppress_hud(mask, anchor)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
    n, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    result = []
    max_radius = max(65, w * .18)
    for i in range(1, n):
        x, y, rw, rh, area = map(int, stats[i])
        ratio = rw/max(1,rh)
        if (area < 14 or min(rw,rh) < 7 or not .42 < ratio < 2.1 or
                rw > w*.20 or rh > h*.26):
            continue
        cx, cy = centers[i]
        if anchor is not None:
            distance = math.hypot(cx-anchor[0],cy-anchor[1])
            if distance > max_radius:
                continue
        else:
            distance = 0.0
        # Avoid tiny UI dots, with or without reference similarity.
        if area < 50 and anchor is None:
            continue
        result.append(((x,y,rw,rh), area, distance))
    return result


def find_cube(bgr, refs, anchor=None, min_confidence=None):
    """Find most cube-like cluster in the frame.

    Returns (cx, cy, apparent_size, matched_warm_pixels, confidence) or None.
    The center is the red-orange silhouette, not the brightest face.
    
    A strong appearance match is required to avoid similarly colored UI.
    The reference set is learned from multiple rotation poses; should be
    recalibrated for substantially different cube skins/lighting.
    """
    if not refs:
        return None
    h, w = bgr.shape[:2]
    threshold = (.64 if anchor is not None else .69) if min_confidence is None else min_confidence
    candidates = []
    for rect, area, distance in _candidate_rects(bgr,anchor):
        patch = normalized_patch(bgr, rect)
        if patch is None or patch.max() < 25:
            continue
        patch_u8 = np.uint8(np.clip(patch, 0, 255))
        sims = [float(cv2.matchTemplate(patch_u8, r.astype(np.uint8),
                        cv2.TM_CCOEFF_NORMED)[0,0]) for r in refs]
        similarity = max([a for a in sims if np.isfinite(a)], default=0.)
        if similarity < threshold:
            continue
        x,y,rw,rh=rect
        # Favor a coherent cube; F8 anchor prevents jumping to other sprites.
        size_score = .04 * min(math.sqrt(area)/30, 1.)
        motion_penalty = (distance / max(65,w*.18))*0.12 if anchor is not None else 0
        score = similarity + size_score - motion_penalty
        candidates.append((score, similarity, x+rw/2., y+rh/2., area, rw, rh))
    if not candidates:
        return None
    best=max(candidates,key=lambda z:z[0]);_,similarity,cx,cy,area,rw,rh=best
    return cx,cy,min(1.,math.sqrt(area)/35),area,similarity
