"""Aion 2 Cube Finder v17 — network HUD + independent sound radar.

Detection state lives in modern_engine; the user-confirmed network parser is
preserved in working_aion_radar.py and is never modified by this interface.
"""
from __future__ import annotations
import math
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import Qt, QTimer, QRectF, QPoint, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QLinearGradient, QRadialGradient, QIcon
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QCheckBox, QSlider, QComboBox,
    QLineEdit, QTextEdit, QFileDialog, QSizePolicy, QScrollArea
)
from modern_engine import DetectionEngine, resource_path
from radar_geometry import project_cube
from ui_config import load as load_ui, save as save_ui
from dual_overlays import NetworkHud, SoundHud

BG = '#080d18'
PANEL = '#10192b'
SURFACE = '#141e31'
LINE = '#243451'
WHITE = '#e7f0ff'
MUTED = '#8393ae'
CYAN = '#3de3ed'
MINT = '#31edbf'
RED = '#ff526e'
GOLD = '#ffcb6b'

QSS = '''
QWidget { color: #dce9fb; font-family: "Segoe UI"; font-size: 12px; }
QMainWindow, QWidget#appRoot {background:#080e19;}
QFrame#card, QFrame#sideCard { background:#111b2d; border:1px solid #25334a; border-radius:18px; }
QFrame#sidebar {background:#0b1322; border-right:1px solid #1f2c40;}
QLabel#muted {color:#8b9cb6;}
QLabel#section {color:#ecf4ff; font-weight:700; font-size:17px;}
QLabel#metric {color:#f1f6ff; font-size:29px; font-weight:800;}
QLabel#eyebrow {color:#7790aa; font-size:10px; font-weight:700; letter-spacing:2px;}
QLabel#status {font-size:12px; font-weight:750; color:#70f0dd; background:#133a40; border:1px solid #256a75; border-radius:9px; padding:7px 11px;}
QPushButton {padding:10px 14px; background:#202c43; border:1px solid #30415c; border-radius:10px; font-weight:600;}
QPushButton:hover {background:#293a56; border-color:#477292;}
QPushButton:pressed {background:#1c5768;}
QPushButton#primary {background:#144a54; border:1px solid #2a9eac; color:#a2fbff;}
QPushButton#primary:hover {background:#176777;}
QPushButton#sideButton {text-align:left; border:none; background:transparent; color:#9cacbd; padding:13px 16px; font-size:13px;}
QPushButton#sideButton:checked {background:#173340; color:#77f2e9; border-left:3px solid #39d8d9; border-radius:6px;}
QPushButton#sideButton:hover {background:#1a2a3d;}
QPushButton#danger {background:#482936; border-color:#7e3b51; color:#ffadb9;}
QLineEdit, QComboBox, QTextEdit {background:#0b1424; border:1px solid #35455e; border-radius:10px; padding:9px; selection-background-color:#1b7b90;}
QComboBox QAbstractItemView {background:#172236; color:#e3edff; selection-background-color:#235b71;}
QCheckBox {spacing:10px; color:#e0e9f9;}
QCheckBox::indicator {width:17px; height:17px;}
QSlider::groove:horizontal {height:6px; border-radius:3px; background:#25354f;}
QSlider::handle:horizontal {background:#4ce2e8; width:16px; margin:-5px 0; border-radius:8px;}
QSlider::sub-page:horizontal {background:#23798e; border-radius:3px;}
QScrollArea {border:0; background:transparent;}
'''


def color(code,alpha=None):
    c=QColor(code)
    if alpha is not None:c.setAlpha(alpha)
    return c


def label(text='', size=12, bold=False, tint=WHITE, parent=None):
    x=QLabel(text,parent)
    font=QFont('Segoe UI',size)
    font.setBold(bold)
    x.setFont(font)
    x.setStyleSheet(f'color:{tint}; background:transparent;')
    return x


def card(layout=None):
    f=QFrame();f.setObjectName('card')
    if layout is not None:
        f.setLayout(layout)
    return f


def btn(text, callback, primary=False):
    b=QPushButton(text)
    if primary:b.setObjectName('primary')
    b.clicked.connect(callback)
    return b


def small_metric(name,value,accent=WHITE):
    v=QVBoxLayout();v.setContentsMargins(15,13,15,13);v.setSpacing(7)
    v.addWidget(label(name.upper(),10,True,MUTED))
    value_label=label(value,22,True,accent);v.addWidget(value_label)
    frame=card(v)
    return frame,value_label


class RadarCanvas(QWidget):
    """Qt anti-aliased radar. World and screen axes never silently conflated."""
    def __init__(self,engine,mode='Auto',parent=None):
        super().__init__(parent)
        self.engine=engine
        self.mode=mode
        self.setMinimumSize(240,240)
        self.phase=0
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)

    def effective_mode(self):
        if self.mode=='World':return 'World'
        if self.mode=='Screen':return 'Screen'
        if self.engine.player_pos is not None and self.engine.netcubes:return 'World'
        return 'Screen'

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing,True)
        w,h=float(self.width()),float(self.height())
        cx,cy=w/2,h/2
        r=min(w,h)*.405
        mode=self.effective_mode()
        # Ambient colored haze, center dark enough to be readable
        haze=QRadialGradient(cx,cy,r*1.12)
        haze.setColorAt(0.,color('#1b4053',80));haze.setColorAt(.65,color('#12344b',30));haze.setColorAt(1.,color('#0d1624',0))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QBrush(haze));p.drawEllipse(QRectF(cx-r*1.12,cy-r*1.12,r*2.24,r*2.24))
        for pct,alpha in [(1.,104),(.75,55),(.5,75),(.25,46)]:
            p.setPen(QPen(color(CYAN,alpha),1.1,Qt.PenStyle.DashLine if pct in (.75,.25) else Qt.PenStyle.SolidLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            d=2*r*pct;p.drawEllipse(QRectF(cx-d/2,cy-d/2,d,d))
        p.setPen(QPen(color(CYAN,47),1))
        p.drawLine(int(cx-r),int(cy),int(cx+r),int(cy))
        p.drawLine(int(cx),int(cy-r),int(cx),int(cy+r))
        for a in range(0,360,15):
            rad=math.radians(a)
            outer=r+3;inner=r-(9 if a%45==0 else 4)
            p.setPen(QPen(color(CYAN,130 if a%45==0 else 62),1))
            p.drawLine(int(cx+math.cos(rad)*inner),int(cy+math.sin(rad)*inner),
                       int(cx+math.cos(rad)*outer),int(cy+math.sin(rad)*outer))
        # Rotating subtle scan line, decorative only
        angle=time.monotonic()*0.3
        p.setPen(QPen(color(CYAN,42),1.5))
        p.drawLine(int(cx),int(cy),int(cx+r*.95*math.cos(angle)),int(cy+r*.95*math.sin(angle)))
        axes=('+X','-X','-Y','+Y') if mode=='World' else ('UP','DOWN','LEFT','RIGHT')
        p.setFont(QFont('Segoe UI',8,QFont.Weight.Bold))
        p.setPen(color('#8097b4'))
        for rect, text in [ (QRectF(cx-22,cy-r-31,44,20),axes[0]),
                           (QRectF(cx-22,cy+r+10,44,18),axes[1]),
                           (QRectF(cx-r-47,cy-11,43,20),axes[2]),
                           (QRectF(cx+r+4,cy-11,44,20),axes[3]) ]:
            p.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)
        e=self.engine
        if mode=='World' and e.player_pos is not None:
            for cube in e.netcubes.values():
                pr=project_cube(e.player_pos,cube['xyz'],center=(cx,cy),radius_px=r,range_m=150,margin_px=8)
                x,y=pr.screen_x,pr.screen_y
                p.setPen(QPen(color(RED,105),1.5,Qt.PenStyle.DashLine))
                p.drawLine(int(cx),int(cy),int(x),int(y))
                self._dot(p,x,y,RED,7.4,outline=True)
                if pr.off_scale:
                    p.setPen(color(RED));p.setFont(QFont('Segoe UI',8))
                    p.drawText(QRectF(x-20,y-22,40,14),Qt.AlignmentFlag.AlignCenter,'>150m')
            self._dot(p,cx,cy,MINT,6.5,outline=True)
        elif mode=='Screen':
            self._dot(p,cx,cy,CYAN,3.6)
            if e.glow is not None and e.glow_enabled:
                x=cx+e.glow[0]*r;y=cy+e.glow[1]*r
                self._dot(p,x,y,GOLD,7.5,outline=True)
            elif e.sound_detected:
                self._dot(p,cx+e.balance*r,cy,CYAN,7,outline=True)
        else:
            self._dot(p,cx,cy,'#53637a',4)
        p.setPen(color(MUTED,210));p.setFont(QFont('Segoe UI',8))
        p.drawText(QRectF(0,h-22,w,18),Qt.AlignmentFlag.AlignCenter,
                   'WORLD X/Y · 150m' if mode=='World' else 'SCREEN AIM · not distance')
        p.end()

    def _dot(self,p,x,y,c,r=7,outline=False):
        halo=QRadialGradient(x,y,r*3.2)
        halo.setColorAt(0,color(c,80));halo.setColorAt(1,color(c,0))
        p.setBrush(QBrush(halo));p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x-r*3.2,y-r*3.2,r*6.4,r*6.4))
        p.setPen(QPen(color('#e6ffff') if outline else color(c),1.5))
        p.setBrush(color(c));p.drawEllipse(QRectF(x-r,y-r,r*2,r*2))
        p.setBrush(Qt.BrushStyle.NoBrush)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config=load_ui()
        self.engine=DetectionEngine()
        self.engine.sensitivity=self.config['sound_sensitivity']
        self.engine.backend=self.config['network_backend']
        self.engine.network_alert_enabled=self.config['network_alert_enabled']
        self.engine.sound_enabled=self.config['sound_detection_enabled']
        self.engine.glow_enabled=self.config['glow_detection_enabled']
        self.setWindowTitle('Aion 2  •  Cube Finder v17 — Sound Radar')
        icon=resource_path('assets','cube_finder.ico')
        if icon.exists():self.setWindowIcon(QIcon(str(icon)))
        self.resize(1080,722)
        self.setMinimumSize(920,650)
        self.setStyleSheet(QSS)
        self.pages=[];self.nav=[]
        self._build()
        self.hud=NetworkHud(self.engine,lambda:self.set_hud(False))
        self.sound_hud=SoundHud(self.engine,lambda:self.set_sound_hud(False))
        self.hud.set_opacity_level(self.config['hud_opacity'])
        self.hud.set_scale(self.config['hud_scale'])
        if isinstance(self.config['hud_x'],int) and isinstance(self.config['hud_y'],int):
            self.hud.move(self.config['hud_x'],self.config['hud_y'])
        else:
            desktop=QApplication.primaryScreen().availableGeometry()
            self.hud.move(desktop.right()-self.hud.width()-45,desktop.top()+65)
        self.hud.set_clickthrough(bool(self.config['hud_clickthrough']))
        self.sound_hud.set_opacity_level(self.config['audio_hud_opacity'])
        self.sound_hud.set_scale(self.config['audio_hud_scale'])
        if isinstance(self.config['audio_hud_x'],int) and isinstance(self.config['audio_hud_y'],int):
            self.sound_hud.move(self.config['audio_hud_x'],self.config['audio_hud_y'])
        else:
            desktop=QApplication.primaryScreen().availableGeometry()
            self.sound_hud.move(desktop.left()+50,desktop.bottom()-self.sound_hud.height()-110)
        self._ensure_hud_visible(self.sound_hud)
        self.sound_hud.set_clickthrough(bool(self.config['audio_hud_clickthrough']))
        self._set_ui_values()
        self._set_page(0)
        self._last_scan=0.
        self.timer=QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(95)
        if self.config['hud_visible']:self.hud.show()
        if self.config['audio_hud_visible']:self.sound_hud.show()

    @staticmethod
    def _ensure_hud_visible(hud):
        """Keep previous saved HUD positions usable after v17's sound HUD grows."""
        pos=hud.pos()
        screen=QApplication.screenAt(pos)
        if screen is None:
            screen=QApplication.primaryScreen()
        if screen is None:
            return
        rect=screen.availableGeometry()
        padding=12
        left=rect.left()+padding
        top=rect.top()+padding
        right=max(left,rect.right()-padding-hud.width()+1)
        bottom=max(top,rect.bottom()-padding-hud.height()+1)
        newx=max(left,min(right,hud.x()))
        newy=max(top,min(bottom,hud.y()))
        if newx!=hud.x() or newy!=hud.y():
            hud.move(newx,newy)

    def _build(self):
        root=QWidget();root.setObjectName('appRoot')
        layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName('sidebar');sidebar.setFixedWidth(210)
        menu=QVBoxLayout(sidebar);menu.setContentsMargins(17,23,17,21);menu.setSpacing(8)
        menu.addWidget(label('◈  CUBE FINDER',15,True,CYAN))
        menu.addWidget(label('DUAL RADAR  /  V17',9,True,MUTED))
        menu.addSpacing(31)
        for i,(name,glyph) in enumerate([('Overview','◉'),('Detection','◇'),('Diagnostics','▤'),('Settings','⚙')]):
            b=QPushButton(f'  {glyph}    {name}');b.setObjectName('sideButton');b.setCheckable(True)
            b.clicked.connect(lambda _checked,idx=i:self._set_page(idx))
            menu.addWidget(b);self.nav.append(b)
        menu.addStretch(1)
        small=QVBoxLayout();small.setContentsMargins(12,12,12,12);small.setSpacing(8)
        small.addWidget(label('CAPTURE STATUS',9,True,MUTED))
        self.side_connection=label('●  Offline',11,True,'#ff8c9a');small.addWidget(self.side_connection)
        self.side_count=label('0 cubes · 0 packets',10,False,MUTED);small.addWidget(self.side_count)
        menu.addWidget(card(small))
        menu.addWidget(label('LOCAL PROCESSING  •  NO UPLOADS',8,True,'#627992'))
        layout.addWidget(sidebar)
        content=QWidget();outer=QVBoxLayout(content);outer.setContentsMargins(26,21,26,21);outer.setSpacing(15)
        top=QHBoxLayout()
        title=QVBoxLayout();title.setSpacing(3)
        title.addWidget(label('AION 2  /  RADAR CONSOLE',10,True,CYAN))
        title.addWidget(label('Live detection center',23,True,WHITE))
        top.addLayout(title);top.addStretch()
        self.header_status=QLabel('SCANNING');self.header_status.setObjectName('status');top.addWidget(self.header_status)
        outer.addLayout(top)
        self.stack=QStackedWidget()
        self.stack.addWidget(self._overview())
        self.stack.addWidget(self._detection())
        self.stack.addWidget(self._diagnostics())
        self.stack.addWidget(self._settings())
        outer.addWidget(self.stack,1)
        bottom=QHBoxLayout()
        self.foot_note=label('READY  ·  Network inactive',10,False,MUTED)
        bottom.addWidget(self.foot_note);bottom.addStretch()
        bottom.addWidget(label('F8 CALIBRATE   •   F7 CLEAR   •   CTRL+SHIFT+F10 NET   •   CTRL+SHIFT+F11 AUDIO',9,True,'#6e819d'))
        outer.addLayout(bottom)
        layout.addWidget(content,1)
        self.setCentralWidget(root)

    def _overview(self):
        page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,0,0);v.setSpacing(15)
        top=QHBoxLayout();top.setSpacing(13)
        radar_frame=card();rv=QVBoxLayout(radar_frame);rv.setContentsMargins(16,15,16,14)
        header=QHBoxLayout();header.addWidget(label('SPATIAL RADAR',12,True,WHITE));header.addStretch()
        self.map_combo=QComboBox();self.map_combo.addItems(['Auto','World','Screen']);self.map_combo.setFixedWidth(110)
        self.map_combo.currentTextChanged.connect(self._change_radar_mode)
        header.addWidget(self.map_combo)
        rv.addLayout(header)
        self.radar=RadarCanvas(self.engine);rv.addWidget(self.radar,1)
        top.addWidget(radar_frame,6)
        right=QVBoxLayout();right.setSpacing(12)
        self.distance_card,self.distance_value=small_metric('3D distance','— m',CYAN)
        self.height_card,self.height_value=small_metric('Elevation','— m',GOLD)
        self.cubes_card,self.cubes_value=small_metric('Visible on network','0',RED)
        for c in (self.distance_card,self.height_card,self.cubes_card):right.addWidget(c)
        right.addStretch(1)
        top.addLayout(right,3);v.addLayout(top,1)
        row=QHBoxLayout();row.setSpacing(12)
        bar=QVBoxLayout();bar.setContentsMargins(15,13,15,15);bar.setSpacing(6)
        bar.addWidget(label('AUDIO PROXIMITY  /  RELATIVE ONLY',10,True,MUTED))
        self.audio_caption=label('No signal',13,True,WHITE);bar.addWidget(self.audio_caption)
        from PySide6.QtWidgets import QProgressBar
        self.audio_bar=QProgressBar();self.audio_bar.setTextVisible(False);self.audio_bar.setRange(0,100)
        self.audio_bar.setStyleSheet('QProgressBar {background:#24334c;border:0;border-radius:5px;height:10px;} QProgressBar::chunk {background:#36dfd4;border-radius:5px;}')
        bar.addWidget(self.audio_bar);row.addWidget(card(bar),2)
        quick=QVBoxLayout();quick.setContentsMargins(14,10,14,10)
        quick.addWidget(label('INDEPENDENT OVERLAYS',10,True,MUTED))
        self.hud_quick=btn('Hide network HUD',lambda:self.set_hud(not self.hud.isVisible()),True)
        quick.addWidget(self.hud_quick)
        self.sound_quick=btn('Hide sound radar',lambda:self.set_sound_hud(not self.sound_hud.isVisible()),True)
        quick.addWidget(self.sound_quick);row.addWidget(card(quick),1)
        v.addLayout(row)
        return page

    def _detection(self):
        page=self._scroll_page();root=page.layout()
        root.addWidget(label('DETECTION MODULES',11,True,CYAN))
        det=QGridLayout();det.setSpacing(15)
        def detcard(title,desc):
            lay=QVBoxLayout();lay.setContentsMargins(20,19,20,19);lay.setSpacing(13)
            lay.addWidget(label(title,17,True,WHITE));d=label(desc,10,False,MUTED);d.setWordWrap(True);lay.addWidget(d)
            frame=card(lay)
            return frame,lay
        n,nl=detcard('Network  /  Coordinates','Read-only TCP capture using your uploaded working parser. True meters when player position is fresh.')
        self.chk_net=QCheckBox('Enable Npcap capture');self.chk_net.toggled.connect(self._toggle_network)
        nl.addWidget(self.chk_net)
        self.chk_network_alert=QCheckBox('Play beep for NEW network cube')
        self.chk_network_alert.toggled.connect(self._set_network_alert)
        nl.addWidget(self.chk_network_alert)
        self.name_edit=QLineEdit();self.name_edit.setPlaceholderText('Character name (optional)');nl.addWidget(self.name_edit)
        network_buttons=QHBoxLayout()
        network_buttons.addWidget(btn('Replay PCAP',self._replay))
        network_buttons.addWidget(btn('Demo target',self._demo))
        nl.addLayout(network_buttons)
        self.net_label=label('OFFLINE',10,True,MUTED);nl.addWidget(self.net_label)
        det.addWidget(n,0,0)
        a,al=detcard('Audio  /  360° Hum','Listen for the 1680 Hz cue; shows signal strength, not an absolute distance.')
        self.chk_audio=QCheckBox('Enable 1680 Hz sound detection');self.chk_audio.setChecked(True)
        self.chk_audio.toggled.connect(self._set_audio_detection);al.addWidget(self.chk_audio)
        al.addWidget(label('Independent of network alerts and network overlay.',10,False,MUTED))
        al.addWidget(label('Sound sensitivity',10,True,MUTED))
        self.sens_slider=QSlider(Qt.Orientation.Horizontal);self.sens_slider.setRange(0,100)
        self.sens_slider.valueChanged.connect(self._change_sensitivity);al.addWidget(self.sens_slider)
        self.sens_label=label('75 / 100',10,False,CYAN);al.addWidget(self.sens_label)
        det.addWidget(a,0,1)
        g,gl=detcard('Visual  /  Rotation Tracking','Find the red cube glow on screen using your recorded rotation patterns and the saved F8 calibration.')
        self.chk_glow=QCheckBox('Enable glow detection');self.chk_glow.setChecked(True)
        self.chk_glow.toggled.connect(self._set_glow_detection);gl.addWidget(self.chk_glow)
        row=QHBoxLayout();row.addWidget(btn('Calibrate F8',self._calibrate));row.addWidget(btn('Clear F7',self._clear_glow));gl.addLayout(row)
        gl.addWidget(label('Color match tolerance',10,True,MUTED))
        self.tol_slider=QSlider(Qt.Orientation.Horizontal);self.tol_slider.setRange(5,120)
        self.tol_slider.valueChanged.connect(self._change_tolerance);gl.addWidget(self.tol_slider)
        self.glow_label=label('No saved glow calibration',10,False,GOLD);gl.addWidget(self.glow_label)
        det.addWidget(g,1,0)
        s,sl=detcard('Target Lifecycle','Remove false targets and check your controls without requiring game traffic.')
        sl.addWidget(btn('Clear all displayed cubes',self._clear_all))
        sl.addWidget(label('Hotkeys: F5/F6 sound sensitivity  ·  F7 clear  ·  F8 sample  ·  F9/F10 tolerance',10,False,MUTED))
        det.addWidget(s,1,1)
        root.addLayout(det);root.addStretch()
        return page

    def _diagnostics(self):
        page=QWidget();v=QVBoxLayout(page);v.setContentsMargins(0,0,0,0);v.setSpacing(13)
        row=QHBoxLayout();row.addWidget(label('NETWORK COUNTERS  /  SAFE SUMMARY',12,True,CYAN));row.addStretch()
        row.addWidget(btn('Copy summary',self._copy_diagnostics,True))
        row.addWidget(btn('Save text',self._save_diagnostics))
        v.addLayout(row)
        self.diag_text=QTextEdit();self.diag_text.setReadOnly(True)
        self.diag_text.setFont(QFont('Consolas',10));v.addWidget(self.diag_text,1)
        phases=QHBoxLayout()
        for name,phase in [('Walk','walking'),('Near cube','near'),('Open cube','opening'),('Stop phase','unlabeled')]:
            phases.addWidget(btn(name,lambda p=phase:self._set_phase(p)))
        v.addLayout(phases)
        self.phase_label=label('Test phase: unlabeled',10,False,MUTED);v.addWidget(self.phase_label)
        return page

    def _settings(self):
        page=self._scroll_page();v=page.layout()
        v.addWidget(label('PERSONALIZE THE OVERLAY',11,True,CYAN))
        rows=QGridLayout();rows.setSpacing(15)
        hud,hl=self._settings_card('Network HUD','Shows only red world-coordinate cubes and their actual network distance. Independent of audio sensing.')
        self.chk_hud=QCheckBox('Show network radar overlay');self.chk_hud.toggled.connect(self.set_hud);hl.addWidget(self.chk_hud)
        hl.addWidget(label('Network opacity',11,True,MUTED))
        self.opacity=QSlider(Qt.Orientation.Horizontal);self.opacity.setRange(45,100)
        self.opacity.valueChanged.connect(self._change_opacity);hl.addWidget(self.opacity)
        self.opacity_value=label('88%',11,True,CYAN);hl.addWidget(self.opacity_value)
        hl.addWidget(label('Network HUD scale',11,True,MUTED))
        self.size_slider=QSlider(Qt.Orientation.Horizontal);self.size_slider.setRange(70,150)
        self.size_slider.valueChanged.connect(self._change_scale);hl.addWidget(self.size_slider)
        self.size_value=label('100%',11,True,CYAN);hl.addWidget(self.size_value)
        self.chk_click=QCheckBox('Network HUD click-through')
        self.chk_click.toggled.connect(self._change_clickthrough)
        hl.addWidget(self.chk_click);rows.addWidget(hud,0,0)
        sound,sl=self._settings_card('Sound radar HUD','Independent sound-direction crosshair (stereo left/right), optional gold visual-glow marker, relative strength percentage, and warmer/colder trend. No actual distance from audio.')
        self.chk_audio_hud=QCheckBox('Show sound direction radar');self.chk_audio_hud.toggled.connect(self.set_sound_hud);sl.addWidget(self.chk_audio_hud)
        sl.addWidget(label('Sound overlay opacity',11,True,MUTED))
        self.sound_opacity=QSlider(Qt.Orientation.Horizontal);self.sound_opacity.setRange(45,100)
        self.sound_opacity.valueChanged.connect(self._change_sound_opacity);sl.addWidget(self.sound_opacity)
        self.sound_opacity_value=label('88%',11,True,CYAN);sl.addWidget(self.sound_opacity_value)
        sl.addWidget(label('Sound overlay scale',11,True,MUTED))
        self.sound_size_slider=QSlider(Qt.Orientation.Horizontal);self.sound_size_slider.setRange(70,150)
        self.sound_size_slider.valueChanged.connect(self._change_sound_scale);sl.addWidget(self.sound_size_slider)
        self.sound_size_value=label('100%',11,True,CYAN);sl.addWidget(self.sound_size_value)
        self.chk_sound_click=QCheckBox('Sound HUD click-through')
        self.chk_sound_click.toggled.connect(self._change_sound_clickthrough)
        sl.addWidget(self.chk_sound_click)
        sl.addWidget(label('Signal % is relative loudness, not distance in meters.',9,False,GOLD))
        rows.addWidget(sound,0,1)
        back,bl=self._settings_card('Network engine','Working radar is the default and uses your uploaded detector without modifying its parsing.')
        self.backend_combo=QComboBox();self.backend_combo.addItems(['Working radar','Experimental v12'])
        self.backend_combo.currentTextChanged.connect(self._change_backend)
        bl.addWidget(self.backend_combo)
        bl.addWidget(label('Engine changes require stopping capture first.',10,False,MUTED))
        bl.addWidget(btn('Reset to original network detector',self._reset_backend))
        bl.addSpacing(11)
        bl.addWidget(label('DISPLAY EXPLANATION',10,True,CYAN))
        explain=label('Red = world cube; cyan = stereo L/R; gold = glow aim; sound % = relative loudness, not meters.',11,False,MUTED)
        explain.setWordWrap(True);bl.addWidget(explain)
        rows.addWidget(back,1,0,1,2)
        v.addLayout(rows);v.addStretch()
        return page

    def _settings_card(self,title,description):
        lay=QVBoxLayout();lay.setContentsMargins(22,22,22,24);lay.setSpacing(12)
        lay.addWidget(label(title,17,True,WHITE))
        d=label(description,10,False,MUTED);d.setWordWrap(True);lay.addWidget(d)
        return card(lay),lay

    def _scroll_page(self):
        page=QWidget()
        layout=QVBoxLayout(page);layout.setContentsMargins(0,0,0,0);layout.setSpacing(17)
        return page

    def _set_ui_values(self):
        self.map_combo.setCurrentText(self.config['radar_mode'])
        self.sens_slider.setValue(self.config['sound_sensitivity'])
        self.tol_slider.setValue(self.engine.glow_tolerance)
        self.opacity.setValue(self.config['hud_opacity'])
        self.size_slider.setValue(self.config['hud_scale'])
        self.backend_combo.setCurrentText(self.config['network_backend'])
        self.chk_hud.setChecked(self.config['hud_visible'])
        self.chk_click.setChecked(self.config['hud_clickthrough'])
        self.chk_audio_hud.setChecked(self.config['audio_hud_visible'])
        self.sound_opacity.setValue(self.config['audio_hud_opacity'])
        self.sound_size_slider.setValue(self.config['audio_hud_scale'])
        self.chk_sound_click.setChecked(self.config['audio_hud_clickthrough'])
        self.chk_network_alert.setChecked(self.config['network_alert_enabled'])
        self.chk_audio.setChecked(self.config['sound_detection_enabled'])
        self.chk_glow.setChecked(self.config['glow_detection_enabled'])

    def _set_page(self,index):
        self.stack.setCurrentIndex(index)
        for i,nav in enumerate(self.nav):nav.setChecked(i==index)
        if index==2:self.diag_text.setPlainText(self.engine.diagnostic_summary())

    def _change_radar_mode(self,text):
        self.radar.mode=text;self.config['radar_mode']=text;self.radar.update()

    def _set_network_alert(self, value):
        self.engine.network_alert_enabled=bool(value)
        self.config['network_alert_enabled']=bool(value)

    def _set_audio_detection(self, value):
        self.engine.sound_enabled=bool(value)
        self.config['sound_detection_enabled']=bool(value)

    def _set_glow_detection(self, value):
        self.engine.glow_enabled=bool(value)
        self.config['glow_detection_enabled']=bool(value)

    def _change_sensitivity(self,value):
        self.engine.sensitivity=value;self.config['sound_sensitivity']=value
        self.sens_label.setText(f'{value} / 100')

    def _change_tolerance(self,value):
        self.engine.glow_tolerance=value;self.engine.save_glow()
        self._update_glow_label()

    def _calibrate(self):
        # The button samples the current mouse pixel; use F8 in game or timer.
        self.engine.calibrate_glow();self._update_glow_label()

    def _clear_glow(self):self.engine.clear_glow();self._update_glow_label()

    def _update_glow_label(self):
        e=self.engine
        text=f'RGB {e.glow_rgb} · {e.glow_state} · match {e.glow_conf:.0%}' if e.glow_rgb else f'No RGB saved · {e.glow_state}'
        self.glow_label.setText(text)

    def _toggle_network(self,value):
        if value:
            try:
                self.engine.character=self.name_edit.text().strip()
                self.engine.start_network()
                self.backend_combo.setEnabled(False)
            except Exception as exc:
                self.engine.network_note=f'Capture failed: {exc}'
                self.chk_net.blockSignals(True);self.chk_net.setChecked(False);self.chk_net.blockSignals(False)
        else:
            self.engine.stop_network();self.backend_combo.setEnabled(True)

    def _replay(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose local capture','','Packet Capture (*.pcap *.pcapng);;All files (*)')
        if path:
            try:
                self.engine.character=self.name_edit.text().strip()
                self.engine.start_network(replay_path=path)
                self.chk_net.blockSignals(True);self.chk_net.setChecked(True);self.chk_net.blockSignals(False)
                self.backend_combo.setEnabled(False)
            except Exception as exc:self.engine.network_note=f'Replay failed: {exc}'

    def _demo(self):
        self.engine.demo_cube()
        self.chk_net.blockSignals(True);self.chk_net.setChecked(False);self.chk_net.blockSignals(False)
        self.backend_combo.setEnabled(True)
        self._set_page(0)

    def _clear_all(self):self.engine.clear_cubes()

    def _copy_diagnostics(self):
        QApplication.clipboard().setText(self.engine.diagnostic_summary())

    def _save_diagnostics(self):
        path,_=QFileDialog.getSaveFileName(self,'Save safe diagnostics','CubeFinder_Diagnostics.txt','Text files (*.txt)')
        if path:Path(path).write_text(self.engine.diagnostic_summary(),encoding='utf-8')

    def _set_phase(self,phase):
        self.engine.set_phase(phase);self.phase_label.setText(f'Test phase: {phase}')

    def _change_backend(self,value):
        if not self.engine.network_enabled:
            self.engine.backend=value;self.config['network_backend']=value

    def _reset_backend(self):self.backend_combo.setCurrentText('Working radar')

    def set_hud(self,visible):
        self.config['hud_visible']=bool(visible)
        if visible:self.hud.show()
        else:self.hud.hide()
        self.chk_hud.blockSignals(True);self.chk_hud.setChecked(bool(visible));self.chk_hud.blockSignals(False)
        self.hud_quick.setText('Hide network HUD' if visible else 'Show network HUD')

    def set_sound_hud(self,visible):
        self.config['audio_hud_visible']=bool(visible)
        if visible:self.sound_hud.show()
        else:self.sound_hud.hide()
        self.chk_audio_hud.blockSignals(True);self.chk_audio_hud.setChecked(bool(visible));self.chk_audio_hud.blockSignals(False)
        self.sound_quick.setText('Hide sound radar' if visible else 'Show sound radar')

    def _change_sound_opacity(self,value):
        self.config['audio_hud_opacity']=value
        self.sound_opacity_value.setText(f'{value}%')
        if hasattr(self,'sound_hud'):self.sound_hud.set_opacity_level(value)

    def _change_sound_scale(self,value):
        self.config['audio_hud_scale']=value
        self.sound_size_value.setText(f'{value}%')
        if hasattr(self,'sound_hud'):self.sound_hud.set_scale(value)

    def _change_sound_clickthrough(self,enabled):
        self.config['audio_hud_clickthrough']=bool(enabled)
        if hasattr(self,'sound_hud'):self.sound_hud.set_clickthrough(enabled)

    def _change_opacity(self,value):
        self.config['hud_opacity']=value
        self.opacity_value.setText(f'{value}%')
        if hasattr(self,'hud'):self.hud.set_opacity_level(value)

    def _change_scale(self,value):
        self.config['hud_scale']=value
        self.size_value.setText(f'{value}%')
        if hasattr(self,'hud'):self.hud.set_scale(value)

    def _change_clickthrough(self,enabled):
        self.config['hud_clickthrough']=bool(enabled)
        if hasattr(self,'hud'):self.hud.set_clickthrough(enabled)

    def _window_rects(self):
        result=[]
        for widget in (self,self.hud,self.sound_hud):
            if widget.isVisible():
                rect=widget.frameGeometry()
                result.append((rect.left(),rect.top(),rect.right(),rect.bottom()))
        return result

    def _tick(self):
        e=self.engine
        now=time.monotonic()
        scan=now-self._last_scan>.17
        if scan:self._last_scan=now
        e.tick(scan=scan,excluded_rects=self._window_rects())
        if e.toggle_hud_requested:
            e.toggle_hud_requested=False;self.set_hud(not self.hud.isVisible())
        if e.toggle_audio_hud_requested:
            e.toggle_audio_hud_requested=False;self.set_sound_hud(not self.sound_hud.isVisible())
        nearest=e.nearest_cube()
        self.header_status.setText(e.status())
        self.side_connection.setText('●  Capture active' if e.network_enabled else '●  Offline')
        self.side_connection.setStyleSheet(f'color:{MINT if e.network_enabled else RED};background:transparent;')
        self.side_count.setText(f'{len(e.netcubes)} cube(s) · {e.packet_count} packets')
        self.cubes_value.setText(str(len(e.netcubes)))
        if nearest and nearest['distance3d'] is not None:
            self.distance_value.setText(f"{nearest['distance3d']:.1f} m")
            self.height_value.setText(f"{nearest['height']:+.1f} m")
        else:
            self.distance_value.setText('— m');self.height_value.setText('— m')
        trend=e.sound_trend()
        self.audio_caption.setText(f"{e.proximity*100:.0f}%  ·  {trend.upper()}" if e.sound_detected else 'No confirmed audio cue')
        self.audio_bar.setValue(round(e.proximity*100) if e.sound_detected else 0)
        stale = (f'  ·  PLAYER POSITION {time.time()-e.position_time:.0f}s OLD' if e.position_time and not e.demo and time.time()-e.position_time>5 else '')
        self.foot_note.setText(('DEMO DATA' if e.demo else ('CAPTURING' if e.network_enabled else 'READY'))+'  ·  '+e.network_note[:65]+stale)
        if not e.network_enabled and self.chk_net.isChecked():
            self.chk_net.blockSignals(True);self.chk_net.setChecked(False);self.chk_net.blockSignals(False)
            self.backend_combo.setEnabled(True)
        self.net_label.setText(e.network_note[:95])
        self._update_glow_label()
        if self.stack.currentIndex()==2:self.diag_text.setPlainText(e.diagnostic_summary())
        self.radar.update()
        if self.hud.isVisible():self.hud.update()
        if self.sound_hud.isVisible():self.sound_hud.update()

    def closeEvent(self,event):
        self.config['hud_x']=self.hud.x();self.config['hud_y']=self.hud.y()
        self.config['hud_visible']=self.hud.isVisible()
        self.config['audio_hud_x']=self.sound_hud.x();self.config['audio_hud_y']=self.sound_hud.y()
        self.config['audio_hud_visible']=self.sound_hud.isVisible()
        try:save_ui(self.config)
        except OSError as exc:print('Could not save UI settings:',exc)
        self.engine.shutdown();self.hud.close();self.sound_hud.close()
        event.accept()


def main():
    # Qt window coords and MSS physical monitor coords should agree on Windows.
    if sys.platform=='win32':
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:pass
    app=QApplication(sys.argv)
    app.setApplicationName('Aion2 Cube Finder')
    app.setStyle('Fusion')
    window=MainWindow();window.show()
    return app.exec()


if __name__=='__main__':sys.exit(main())
