"""Deterministic world-space radar geometry (independent of camera orientation).

Coordinate orientation matches the source mini-radar: world +Y -> right,
world +X -> up. Distances use 100 coordinate units / meter.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RadarProjection:
    screen_x: float
    screen_y: float
    flat_m: float
    height_m: float
    distance_3d_m: float
    off_scale: bool


def project_cube(player_xyz, cube_xyz, *, center=(140.0, 140.0), radius_px=128.0,
                 range_m=150.0, margin_px=16.0) -> RadarProjection:
    if range_m <= 0 or radius_px <= margin_px:
        raise ValueError('Radar range and pixel radius must be positive')
    px,py,pz=map(float,player_xyz)
    x,y,z=map(float,cube_xyz)
    dx=(x-px)/100.0
    dy=(y-py)/100.0
    dz=(z-pz)/100.0
    flat=math.hypot(dx,dy)
    dist3=math.hypot(flat,dz)
    # Identical world X/Y axis convention to Pure2DRadarApp._draw_radar:
    # source screen_off_x = cdy * scale; screen_off_y = -cdx * scale.
    scale=(radius_px-margin_px)/range_m
    sx=dy*scale
    sy=-dx*scale
    magnitude=math.hypot(sx,sy)
    max_radius=radius_px-margin_px
    off_scale=magnitude>max_radius
    if off_scale:
        sx*=max_radius/magnitude
        sy*=max_radius/magnitude
    return RadarProjection(center[0]+sx,center[1]+sy,flat,dz,dist3,off_scale)
