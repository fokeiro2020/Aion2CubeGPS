"""Qt-independent Aion 2 detector controller.

Preserves the user-confirmed PureStreamEngine via WorkingCapture.  No game
memory inspection.  Sound and glow work independently of the network engine.
"""
from __future__ import annotations
import collections
import ctypes
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time

import numpy as np

from glow_settings import read_glow_settings, write_glow_settings
from glow_tracking import exclude_window
from rotation_tracking import find_cube, load_rotation_patterns

SAMPLE_RATE = 48000
BLOCK = 4800
BAND_LO, BAND_HI = 1620, 1740
SIGNAL_GATE_DB = -105
TREND_FRAMES = 9
VK = {'F5':0x74,'F6':0x75,'F7':0x76,'F8':0x77,'F9':0x78,'F10':0x79,
      'CTRL':0x11,'SHIFT':0x10,'HUD':0x79,'F11':0x7A}  # Ctrl+Shift+F10 = HUD toggle


def resource_path(*parts):
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).joinpath(*parts)


def margin_for_slider(s):
    return 14.0 - (float(s)/100.)*12.5


def _is_key_down(vk):
    if sys.platform != 'win32':
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def cursor_position():
    class Point(ctypes.Structure):
        _fields_ = [('x',ctypes.c_long),('y',ctypes.c_long)]
    point = Point()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _audio_listener(events, stop):
    try:
        import soundcard as sc
        freq = np.fft.rfftfreq(BLOCK, 1/SAMPLE_RATE)
        bins = np.where((freq>=BAND_LO)&(freq<=BAND_HI))[0]
        window = np.hanning(BLOCK)
        speaker = sc.default_speaker()
        mic = sc.get_microphone(id=str(speaker.name),include_loopback=True)
        with mic.recorder(samplerate=SAMPLE_RATE,channels=2) as recording:
            while not stop.is_set():
                samples = recording.record(numframes=BLOCK)
                def level(a):
                    spectrum = np.abs(np.fft.rfft(a*window))
                    return np.sqrt(np.sum(spectrum[bins]**2))/BLOCK
                left,right = level(samples[:,0]),level(samples[:,1])
                value = 20*np.log10((left+right)/2+1e-9)
                balance = (right-left)/(left+right+1e-9)
                try: events.put_nowait((float(value),float(balance)))
                except queue.Full: pass
    except Exception as e:
        print(f'[AUDIO] {e}')


class DetectionEngine:
    def __init__(self, start_audio=True, start_screen=True):
        self.netq = queue.Queue(maxsize=400)
        self.audioq = queue.Queue(maxsize=10)
        self.stop_event = threading.Event()
        self.capture = None
        self.backend = 'Working radar'
        self.character = ''
        self.network_enabled = False
        self.sound_enabled = True
        self.network_alert_enabled = True
        self.glow_enabled = True
        self.netcubes = {}
        self.player_pos = None
        self.position_time = 0.0
        self.packet_count = 0
        self.network_note = 'Network offline'
        self.network_stats = {}
        self.test_phase = 'unlabeled'
        self.demo = False
        self.last_alert = 0.
        self.last_audio_reading = 0.
        self.sensitivity = 75
        self.noise_db = -90.
        self.peak_db = -62.
        self.proximity = 0.
        self.balance = 0.
        self.sound_detected = False
        self.history = collections.deque(maxlen=TREND_FRAMES+1)
        self.glow_rgb, self.glow_tolerance = read_glow_settings()
        self.glow_state = 'LOADED' if self.glow_rgb is not None else 'NOT SET'
        self.glow = None
        self.glow_conf = 0.
        self.glow_pixels = 0
        self.glow_anchor = None
        self.glow_smooth = None
        self.glow_misses = 0
        self.glow_refs = load_rotation_patterns(resource_path('assets','rotation_patterns'))
        self.prev_hotkeys = {}
        self.toggle_hud_requested = False
        self.toggle_audio_hud_requested = False
        self.sct = None
        self.mon = None
        self.screen_scale = 1
        self.screen_error = ''
        if start_screen:
            try:
                import mss
                self.sct = mss.mss()
                self.mon = self.sct.monitors[1]
                self.screen_scale = max(1, int(self.mon['width']/640))
            except Exception as exc:
                self.screen_error = str(exc)
        if start_audio:
            threading.Thread(target=_audio_listener,args=(self.audioq,self.stop_event),daemon=True,name='CubeAudio').start()

    def start_network(self, replay_path=None):
        self.stop_network()
        self.netcubes.clear()
        self.player_pos = None
        self.position_time = 0
        self.demo = False
        self.packet_count = 0
        self.network_stats = {}
        if self.backend == 'Working radar':
            from working_network_capture import WorkingCapture
            cls = WorkingCapture
        else:
            from network_capture import CaptureWorker
            cls = CaptureWorker
        self.capture = cls(self.netq,self.character,server_ports=(13328,13320),server_host=None)
        # The uploaded parser has its own beep. Our unified alert handles audio,
        # so mute only that duplicate beep; do not alter its parsing logic.
        if self.backend == 'Working radar':
            self.capture.state.sound_enabled = False
        self.network_enabled = True
        self.network_note = ('Playing capture' if replay_path else 'Listening on 13328 + 13320')
        self.test_phase = 'unlabeled'
        self.capture.start(replay_path=replay_path)

    def stop_network(self):
        if self.capture is not None:
            self.capture.stop()
        self.capture = None
        self.network_enabled = False
        self.network_note = 'Network offline'
        self.test_phase = 'unlabeled'
        # Prevent a stale live cube looking current when capture is off.
        self.netcubes.clear()
        self.player_pos = None
        self.position_time = 0

    def set_phase(self, phase):
        if phase not in ('unlabeled','walking','near','opening'):
            raise ValueError('Invalid test phase')
        self.test_phase = phase
        if self.capture:
            self.capture.set_phase(phase)

    def demo_cube(self):
        self.stop_network()
        self.demo = True
        self.player_pos = (0.,0.,0.)
        self.position_time = time.time()
        self.netcubes = {90001:{'xyz':(7600.,6400.,2200.),'template':1200039,'source':'demo'}}
        self.network_note = 'Demo coordinates (simulated)'

    def clear_cubes(self):
        self.netcubes.clear()

    def _play_alert(self):
        if not self.network_alert_enabled or time.monotonic()-self.last_alert<2:
            return
        self.last_alert = time.monotonic()
        if sys.platform == 'win32':
            try:
                import winsound
                wav=resource_path('assets','cube_alert.wav')
                winsound.PlaySound(str(wav),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
            except Exception: pass

    def process_network_events(self):
        for _ in range(300):
            try: event=self.netq.get_nowait()
            except queue.Empty: break
            kind=event.get('type')
            if kind=='cube':
                eid=event['id']
                if event['action']=='spawn':
                    fresh=eid not in self.netcubes
                    previous=self.netcubes.get(eid)
                    source=event.get('source','stream')
                    if previous is None or previous.get('source')=='packet-local' or source in ('working','stream'):
                        self.netcubes[eid]={'xyz':event['xyz'],'template':event['template'],'source':source}
                    if fresh:self._play_alert()
                else:self.netcubes.pop(eid,None)
            elif kind=='player':
                self.player_pos=tuple(event['xyz'])
                self.position_time=time.time()
            elif kind=='zone_reset':
                self.netcubes.clear();self.player_pos=None;self.position_time=0.
            elif kind=='packets':self.packet_count=event['count']
            elif kind=='network_stats':self.network_stats=event['stats']
            elif kind in ('info','warning','error'):self.network_note=event['text']
            elif kind=='network_stopped' and not (self.capture and self.capture.thread and self.capture.thread.is_alive()):
                self.network_note='Capture stopped'
                self.network_enabled=False

    def process_audio(self):
        reading=None
        while True:
            try: reading=self.audioq.get_nowait()
            except queue.Empty: break
        if reading is not None:
            level_db, balance=reading
            self.last_audio_reading=time.monotonic()
            self.noise_db = level_db if level_db<self.noise_db else self.noise_db+.015
            self.peak_db = level_db if level_db>self.peak_db else self.peak_db-.02
            if self.peak_db-self.noise_db<8:self.peak_db=self.noise_db+8
            margin=margin_for_slider(self.sensitivity)
            self.sound_detected=self.sound_enabled and level_db>SIGNAL_GATE_DB and level_db-self.noise_db>margin
            span=self.peak_db-(self.noise_db+margin)
            raw=float(np.clip((level_db-(self.noise_db+margin))/max(span,1),0,1))
            self.proximity+=(raw-self.proximity)*.35
            self.balance+=(balance-self.balance)*.35
        if not self.sound_enabled:
            self.sound_detected=False
            self.proximity*=.82
        elif reading is None and self.last_audio_reading and time.monotonic()-self.last_audio_reading>1.2:
            # Don't leave a stuck 90% reading if the audio device stops.
            self.sound_detected=False
            self.proximity*=.82
        self.history.append(self.proximity)

    def sound_trend(self):
        if not self.sound_detected or len(self.history)<=TREND_FRAMES:return 'none'
        delta=self.history[-1]-self.history[0]
        if delta>.012:return 'warmer'
        if delta<-.012:return 'colder'
        return 'steady'

    def save_glow(self):
        try:
            write_glow_settings(self.glow_rgb,self.glow_tolerance)
            self.glow_state='SAVED' if self.glow_rgb else 'CLEARED'
        except (OSError,ValueError) as exc:
            self.glow_state=f'SAVE FAILED: {exc}'

    def clear_glow(self):
        self.glow_rgb=None
        self.glow_anchor=None;self.glow_smooth=None;self.glow=None
        self.glow_misses=0;self.glow_pixels=0;self.glow_conf=0
        self.save_glow()

    def calibrate_glow(self):
        if self.sct is None or sys.platform!='win32':
            self.glow_state='SCREEN CAPTURE UNAVAILABLE'
            return False
        try:
            x,y=cursor_position()
            patch=np.asarray(self.sct.grab({'left':x-5,'top':y-5,'width':10,'height':10}))[:,:,:3]
            b,g,r=patch.reshape(-1,3).mean(axis=0)
            self.glow_rgb=(int(r),int(g),int(b))
            self.glow_anchor=((x-self.mon['left'])/self.screen_scale,(y-self.mon['top'])/self.screen_scale)
            self.glow_misses=0;self.glow_smooth=None
            self.save_glow()
            return True
        except Exception as exc:
            self.glow_state=f'CAPTURE FAILED: {exc}'
            return False

    def scan_glow(self, excluded_rects=()):
        if not self.glow_enabled or self.sct is None or self.glow_rgb is None:
            self.glow=None;self.glow_conf=0;return
        try:
            frame=np.asarray(self.sct.grab(self.mon))[:,:,:3]
            small=frame[::self.screen_scale,::self.screen_scale].copy()
            for rect in excluded_rects:
                exclude_window(small,self.mon,self.screen_scale,rect)
            base=.64 if self.glow_anchor is not None else .69
            threshold=max(.54,min(.84,base+(40-self.glow_tolerance)*.0025))
            found=find_cube(small,self.glow_refs,anchor=self.glow_anchor,min_confidence=threshold)
            if found is None:
                self.glow=None;self.glow_conf=0;self.glow_pixels=0
                self.glow_misses+=1
                if self.glow_misses>=28:
                    self.glow_anchor=None;self.glow_smooth=None
                return
            cx,cy,size,count,conf=found
            if self.glow_smooth is None or self.glow_misses>4:
                sx,sy=cx,cy
            else:
                sx=.55*self.glow_smooth[0]+.45*cx
                sy=.55*self.glow_smooth[1]+.45*cy
            self.glow_smooth=(sx,sy)
            self.glow_anchor=(cx,cy)
            self.glow_misses=0
            self.glow_conf=conf;self.glow_pixels=count
            self.glow=(((sx/small.shape[1])-.5)*2,((sy/small.shape[0])-.5)*2,size)
        except Exception as exc:
            self.glow=None;self.screen_error=str(exc)

    def poll_hotkeys(self):
        if sys.platform!='win32':return
        for name in ('F5','F6','F7','F8','F9','F10','F11'):
            pressed=_is_key_down(VK[name])
            triggered=pressed and not self.prev_hotkeys.get(name,False)
            self.prev_hotkeys[name]=pressed
            if not triggered:continue
            if name=='F8':self.calibrate_glow()
            elif name=='F7':self.clear_glow()
            elif name=='F9':
                self.glow_tolerance=max(5,self.glow_tolerance-5);self.save_glow()
            elif name=='F10':
                if _is_key_down(VK['CTRL']) and _is_key_down(VK['SHIFT']):
                    self.toggle_hud_requested=True
                else:
                    self.glow_tolerance=min(120,self.glow_tolerance+5);self.save_glow()
            elif name=='F11' and _is_key_down(VK['CTRL']) and _is_key_down(VK['SHIFT']):
                self.toggle_audio_hud_requested=True
            elif name=='F5':self.sensitivity=max(0,self.sensitivity-5)
            elif name=='F6':self.sensitivity=min(100,self.sensitivity+5)

    def nearest_cube(self):
        if not self.netcubes:return None
        if self.player_pos is None:
            cube=next(iter(self.netcubes.values()))
            return {'xyz':cube['xyz'],'horizontal':None,'height':None,'distance3d':None,'source':cube['source']}
        closest=min(self.netcubes.values(),key=lambda cube: sum((a-b)**2 for a,b in zip(cube['xyz'],self.player_pos)))
        dx,dy,dz=(float(a-b)/100. for a,b in zip(closest['xyz'],self.player_pos))
        return {'xyz':closest['xyz'],'horizontal':math.hypot(dx,dy),'height':dz,
                'distance3d':math.sqrt(dx*dx+dy*dy+dz*dz),'source':closest['source']}

    def status(self):
        if self.glow_enabled and self.glow is not None:return 'VISUAL CONTACT'
        if self.sound_detected and self.proximity>=.85:return 'VERY CLOSE'
        if self.netcubes:return 'CUBE DETECTED'
        if self.sound_detected:return 'AUDIO SIGNAL'
        return 'SCANNING'

    def diagnostic_summary(self):
        lines=['Aion 2 Cube Finder v16 — counters only, no packet content',
               f'Decoder: {self.backend}',f'Network: {self.network_note}',
               'Ports 13328 + 13320; traffic metadata only']
        for k,v in sorted(self.network_stats.items()):
            if isinstance(v,list):v=', '.join(map(str,v)) if v else '(none)'
            lines.append(f'{k}: {v}')
        if not self.network_stats:lines.append('No network stats yet.')
        return '\n'.join(lines)

    def tick(self, scan=False, excluded_rects=()):
        self.poll_hotkeys()
        self.process_network_events()
        self.process_audio()
        if scan:self.scan_glow(excluded_rects)

    def shutdown(self):
        self.stop_event.set()
        self.stop_network()
        if self.sct is not None:
            try:self.sct.close()
            except Exception:pass
