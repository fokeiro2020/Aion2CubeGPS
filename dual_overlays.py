"""Two independent translucent PySide6 HUDs, sharing one detection engine.

World data is displayed ONLY by NetworkHud. The audio HUD never switches modes
when a cube is detected over Npcap; its percentage is not a distance in meters.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QBrush, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from radar_geometry import project_cube
from sound_direction import stereo_marker, glow_marker, stereo_instruction, relative_strength

CYAN = '#49e6f3'
RED = '#ff536d'
MINT = '#32efbf'
GOLD = '#ffd06a'
WHITE = '#e9f4ff'
MUTED = '#92a9c1'


def rgba(h, alpha=255):
    c = QColor(h)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def strength_label(percent, detected):
    """A relative signal classification, NOT a measurement in meters."""
    if not detected:
        return 'SEARCHING FOR AUDIO CUE'
    if percent >= 85:
        return 'VERY STRONG SIGNAL'
    if percent >= 60:
        return 'STRONG SIGNAL'
    if percent >= 35:
        return 'MODERATE SIGNAL'
    return 'FAINT SIGNAL'


class GlassOverlay(QWidget):
    BASE_WIDTH = 320
    BASE_HEIGHT = 330

    def __init__(self, engine, on_hide, window_title):
        super().__init__(None)
        self.engine = engine
        self.on_hide = on_hide
        self.alpha = 88
        self.scale_pct = 100
        self.click_through = False
        self._drag = None
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowTitle(window_title)
        self.setFixedSize(self.BASE_WIDTH, self.BASE_HEIGHT)

    def set_opacity_level(self, percent):
        self.alpha = max(45, min(100, int(percent)))
        self.update()

    def set_scale(self, percent):
        self.scale_pct = max(70, min(150, int(percent)))
        self.setFixedSize(round(self.BASE_WIDTH * self.scale_pct / 100),
                          round(self.BASE_HEIGHT * self.scale_pct / 100))
        self.update()

    def set_clickthrough(self, enabled):
        self.click_through = bool(enabled)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self.click_through)
        if self.isVisible():
            self.show()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scaled_x = event.position().x() * self.BASE_WIDTH / max(1, self.width())
            scaled_y = event.position().y() * self.BASE_HEIGHT / max(1, self.height())
            if scaled_x >= self.BASE_WIDTH - 39 and scaled_y <= 48:
                self.on_hide()
                return
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag = None
        super().mouseReleaseEvent(event)

    def begin(self, painter):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(self.width() / self.BASE_WIDTH, self.height() / self.BASE_HEIGHT)
        a = round(240 * self.alpha / 100)
        painter.setPen(QPen(rgba('#497b94', min(230, a)), 1.15))
        painter.setBrush(rgba('#0a1323', a))
        painter.drawRoundedRect(QRectF(3, 3, self.BASE_WIDTH - 6, self.BASE_HEIGHT - 6), 21, 21)
        gradient = QLinearGradient(0, 4, 0, 65)
        gradient.setColorAt(0, rgba('#176078', round(a * .65)))
        gradient.setColorAt(1, rgba('#174055', 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(QRectF(6, 6, self.BASE_WIDTH - 12, 64), 19, 19)
        painter.setPen(rgba('#b7cee2'))
        painter.setFont(QFont('Segoe UI', 13, QFont.Weight.Bold))
        painter.drawText(self.BASE_WIDTH - 31, 32, '×')

    @staticmethod
    def spot(p, x, y, hex_color, radius=7):
        halo = QRadialGradient(x, y, radius * 3.5)
        halo.setColorAt(0, rgba(hex_color, 125))
        halo.setColorAt(1, rgba(hex_color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(halo))
        r = radius * 3.5
        p.drawEllipse(QRectF(x-r, y-r, 2*r, 2*r))
        p.setPen(QPen(rgba('#eaffff'), 1.3))
        p.setBrush(rgba(hex_color))
        p.drawEllipse(QRectF(x-radius, y-radius, radius*2, radius*2))


class NetworkHud(GlassOverlay):
    BASE_HEIGHT = 340

    def __init__(self, engine, on_hide):
        super().__init__(engine, on_hide, 'Cube Finder — Network Radar')

    def paintEvent(self, event):
        p = QPainter(self)
        self.begin(p)
        e = self.engine
        p.setPen(rgba(CYAN))
        p.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        p.drawText(21, 28, '◈  NETWORK RADAR')
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        p.setPen(rgba(RED if e.netcubes else MUTED))
        p.drawText(21, 52, f'{len(e.netcubes)} CUBE(S) · '+('CAPTURE ACTIVE' if e.network_enabled else 'CAPTURE OFF'))

        cx, cy, rad = 160, 167, 91
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pct in (1, .66, .33):
            rr = rad * pct
            p.setPen(QPen(rgba(CYAN, 96 if pct == 1 else 42), 1))
            p.drawEllipse(QRectF(cx-rr, cy-rr, rr*2, rr*2))
        p.setPen(QPen(rgba(CYAN, 40), 1))
        p.drawLine(cx-rad, cy, cx+rad, cy)
        p.drawLine(cx, cy-rad, cx, cy+rad)
        p.setPen(rgba(MUTED))
        p.setFont(QFont('Segoe UI', 7))
        p.drawText(cx-7, cy-rad-9, '+X')
        p.drawText(cx-7, cy+rad+17, '-X')
        p.drawText(cx-rad-24, cy+4, '-Y')
        p.drawText(cx+rad+5, cy+4, '+Y')
        if e.player_pos is not None:
            self.spot(p, cx, cy, MINT, 5)
            for c in e.netcubes.values():
                projected = project_cube(e.player_pos, c['xyz'], center=(cx, cy), radius_px=rad, range_m=150, margin_px=8)
                self.spot(p, projected.screen_x, projected.screen_y, RED, 6.5)
        elif e.netcubes:
            p.setPen(rgba(GOLD))
            p.setFont(QFont('Segoe UI', 8))
            p.drawText(QRectF(55, 145, 210, 35), Qt.AlignmentFlag.AlignCenter, 'WAITING FOR PLAYER POSITION')
        else:
            self.spot(p, cx, cy, '#546d86', 3.5)
        nearest = e.nearest_cube()
        p.setPen(rgba(MUTED))
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        p.drawText(19, 291, '3D DISTANCE  ·  TRUE WORLD COORDINATES')
        p.setPen(rgba(WHITE))
        p.setFont(QFont('Segoe UI', 17, QFont.Weight.Bold))
        if nearest and nearest['distance3d'] is not None:
            p.drawText(20, 321, f"{nearest['distance3d']:.1f} m")
            p.setPen(rgba(GOLD))
            p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
            p.drawText(190, 319, f"{nearest['height']:+.1f} m high")
        else:
            p.drawText(20, 321, '— m')
        if e.position_time and not e.demo and time.time() - e.position_time > 5:
            p.setPen(rgba(GOLD))
            p.setFont(QFont('Segoe UI', 8))
            p.drawText(198, 294, 'STALE POSITION')
        p.end()


class SoundHud(GlassOverlay):
    """Independent audio direction guide + screen-glow aiming aid.

    Cyan cursor uses speaker L/R balance and is limited to ONE horizontal axis.
    Gold cursor, if shown, is measured from screen pixels (not microphone audio).
    Neither marker is a world-space locator or a distance in meters.
    """
    BASE_HEIGHT = 472

    def __init__(self, engine, on_hide):
        super().__init__(engine, on_hide, 'Cube Finder — Sound Direction Radar')

    def paintEvent(self, event):
        p = QPainter(self)
        self.begin(p)
        e = self.engine
        detected = bool(e.sound_detected and e.sound_enabled)
        pct = round(max(0, min(100, e.proximity * 100))) if detected else 0
        trend = e.sound_trend() if detected else 'none'
        signal_color = (RED if pct >= 85 else GOLD if pct >= 60 else MINT) if detected else '#71839d'

        p.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        p.setPen(rgba(CYAN))
        p.drawText(21, 27, '◈  SOUND DIRECTION RADAR')
        p.setFont(QFont('Segoe UI', 9, QFont.Weight.Bold))
        p.setPen(rgba(signal_color))
        p.drawText(21, 51, relative_strength(pct, detected) if e.sound_enabled else 'AUDIO DETECTOR OFF')

        # Round directional display; unlike a coordinate map, stereo gives us
        # ONLY left/right audio balance. No artificial Y/depth estimate.
        cx, cy, radius = 160, 169, 86
        p.setBrush(Qt.BrushStyle.NoBrush)
        for fraction in (1.0, .68, .35):
            r = radius * fraction
            p.setPen(QPen(rgba(CYAN, 112 if fraction == 1. else 50), 1.25,
                          Qt.PenStyle.DashLine if fraction == .68 else Qt.PenStyle.SolidLine))
            p.drawEllipse(QRectF(cx-r, cy-r, 2*r, 2*r))
        p.setPen(QPen(rgba(CYAN, 58), 1))
        p.drawLine(cx-radius,cy,cx+radius,cy)
        p.drawLine(cx,cy-radius,cx,cy+radius)
        for angle in range(0,360,30):
            a=math.radians(angle)
            out=radius+3
            inside=radius-(9 if angle % 90 == 0 else 4)
            p.setPen(QPen(rgba(CYAN, 105 if angle % 90 == 0 else 60), 1))
            p.drawLine(round(cx+inside*math.cos(a)),round(cy+inside*math.sin(a)),
                       round(cx+out*math.cos(a)),round(cy+out*math.sin(a)))
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        p.setPen(rgba(MUTED))
        p.drawText(QRectF(114, 67, 92, 18), Qt.AlignmentFlag.AlignCenter, 'SCREEN UP')
        p.drawText(QRectF(109, 267, 102, 18), Qt.AlignmentFlag.AlignCenter, 'SCREEN DOWN')
        p.drawText(QRectF(11, 158, 58, 20), Qt.AlignmentFlag.AlignCenter, 'LEFT')
        p.drawText(QRectF(251, 158, 58, 20), Qt.AlignmentFlag.AlignCenter, 'RIGHT')
        self.spot(p, cx, cy, '#526c8d', 3.2)

        # Cyan marker: real-time L/R balance from the 1680-Hz audio detector.
        # It never moves vertically because stereo alone has no elevation data.
        if detected:
            ax, ay=stereo_marker(e.balance, (cx,cy), radius)
            p.setPen(QPen(rgba(CYAN, 115), 1.4, Qt.PenStyle.DashLine))
            p.drawLine(cx,cy,round(ax),round(ay))
            pulse=(math.sin(time.monotonic() * math.tau * (.8 + 2.1*pct/100)) + 1.)/2.
            wave=9 + 12*pulse
            p.setPen(QPen(rgba(CYAN, 40 + 105*pulse), 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(ax-wave, ay-wave, 2*wave, 2*wave))
            self.spot(p, ax, ay, CYAN, 6.8)

        # Gold marker is OPTIONAL vision-based screen aiming, not audio.
        if e.glow_enabled and e.glow is not None:
            gp=glow_marker(e.glow[:2], (cx,cy), radius)
            if gp:
                gx,gy=gp
                p.setPen(QPen(rgba(GOLD, 125), 1.1, Qt.PenStyle.DotLine))
                p.drawLine(cx,cy,round(gx),round(gy))
                self.spot(p,gx,gy,GOLD,5.9)

        # Keep labels explicit so the two sources are not confused.
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        p.setPen(rgba(CYAN))
        p.drawText(19, 296, '●  CYAN: STEREO LEFT / RIGHT')
        p.setPen(rgba(GOLD))
        p.drawText(19, 313, '●  GOLD: VISUAL GLOW (IF VISIBLE)')

        p.setPen(rgba(signal_color))
        p.setFont(QFont('Segoe UI', 29, QFont.Weight.Bold))
        p.drawText(20, 349, f'{pct}%')
        p.setPen(rgba(MUTED))
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        p.drawText(150, 337, 'RELATIVE AUDIO STRENGTH')
        p.drawText(150, 352, 'NOT METERS')

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rgba('#243449'))
        p.drawRoundedRect(QRectF(20, 366, 280, 11), 5, 5)
        if detected and pct > 0:
            grad = QLinearGradient(20, 0, 300, 0)
            grad.setColorAt(0, rgba(MINT)); grad.setColorAt(.65, rgba(GOLD)); grad.setColorAt(1, rgba(RED))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(20, 366, 280*pct/100, 11), 5, 5)

        if trend == 'warmer':
            trend_text, trend_tint = '▲  WARMER · SIGNAL RISING', MINT
        elif trend == 'colder':
            trend_text, trend_tint = '▼  COLDER · SIGNAL FALLING', RED
        elif trend == 'steady':
            trend_text, trend_tint = '●  STEADY · MOVE TO VERIFY', GOLD
        else:
            trend_text, trend_tint = '●  LISTENING FOR CUBE HUM', MUTED
        p.setPen(rgba(trend_tint))
        p.setFont(QFont('Segoe UI', 10, QFont.Weight.Bold))
        p.drawText(20, 407, trend_text)

        p.setPen(rgba(CYAN if detected else MUTED))
        p.setFont(QFont('Segoe UI', 8, QFont.Weight.Bold))
        p.drawText(20, 434, stereo_instruction(e.balance, detected))
        p.setPen(rgba(MUTED, 190))
        p.setFont(QFont('Segoe UI', 8))
        p.drawText(20, 454, 'TURN CAMERA, THEN MOVE TOWARD STRONGER HUM')
        p.end()
