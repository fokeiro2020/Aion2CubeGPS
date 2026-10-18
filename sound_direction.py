"""UI-only audio and screen-glow cursor geometry.

Stereo balance is *not* a 2D bearing or a distance. Sound marker is constrained
onto the horizontal axis. Glow uses image-space X/Y and never network state.
"""
from __future__ import annotations
import math


def clamp(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(minimum, min(maximum, val)) if math.isfinite(val) else 0.0


def stereo_marker(balance: float, center=(160., 167.), radius=87., margin=13.):
    """Direction indication from stereo balance: horizontal movement ONLY."""
    x, y = center
    return (float(x) + clamp(balance) * max(0., float(radius) - float(margin)), float(y))


def glow_marker(glow_xy, center=(160., 167.), radius=87., margin=13.):
    """Map normalized screen glow offsets to a bounded 2D crosshair."""
    x, y = float(center[0]), float(center[1])
    if glow_xy is None:
        return None
    dx = clamp(glow_xy[0]); dy = clamp(glow_xy[1])
    mag = math.hypot(dx,dy)
    if mag > 1.:
        dx /= mag
        dy /= mag
    rr=max(0.,float(radius)-float(margin))
    return (x + dx * rr, y + dy * rr)


def stereo_instruction(balance: float, detected: bool):
    if not detected: return 'LISTENING · ROTATE TO SEARCH'
    if balance < -.12: return 'LOUDER ON LEFT · TURN LEFT TO CHECK'
    if balance > .12: return 'LOUDER ON RIGHT · TURN RIGHT TO CHECK'
    return 'BALANCED · MOVE AND CHECK STRENGTH'


def relative_strength(pct: float, detected: bool):
    if not detected: return 'SEARCHING FOR CUBE HUM'
    if pct >= 85: return 'VERY STRONG'
    if pct >= 60: return 'STRONG'
    if pct >= 35: return 'MODERATE'
    return 'FAINT'
