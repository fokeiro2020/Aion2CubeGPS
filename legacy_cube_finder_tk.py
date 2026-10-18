"""
Cube Finder All-in-One - sound + screen glow + experimental network
============================================
Combines both cube detectors in one window:

  * SOUND  (works 360 degrees, through walls, off-screen)
      Tracks the cube's ~1680 Hz hum. Gives proximity, WARMER/COLDER,
      and rough left/right. Use it to get into the area.

  * GLOW   (works only when the cube is on screen & in view)
      Watches your screen for the cube's glow. Gives PRECISE left/right
      AND up/down - the elevation sound can't provide.

HOW THEY WORK TOGETHER
  - No glow in view  -> the crosshair follows SOUND (left/right only)
    plus WARMER/COLDER tells you if you're closing in (incl. up/down:
    move and watch the trend).
  - Glow appears     -> the crosshair switches to the GLOW (gold dot),
    pointing you precisely, including up/down.

The screen/audio modes only read output. Network mode passively inspects
packets, which may still be against the game's rules. No ban guarantee.

KEYS (work even while the game has focus)
  F8  learn glow color under mouse cursor   F7  clear glow color
  F9 / F10   glow tolerance  down / up
  F5 / F6    sound sensitivity  down / up

Requirements:  pip install numpy soundcard mss
Build to .exe:  see build_finder.bat
"""

import collections
import ctypes
import queue
import threading
import tkinter as tk
from tkinter import filedialog
import math
import os
import sys
import time
from pathlib import Path
from network_capture import CaptureWorker
from working_network_capture import WorkingCapture, EmbeddedNetworkRadar
from radar_geometry import project_cube
from game_connections import discover_game_endpoints
from glow_settings import read_glow_settings, write_glow_settings
from glow_tracking import exclude_window
from rotation_tracking import find_cube, load_rotation_patterns

import numpy as np
import soundcard as sc
import mss

# ---------------------------------------------------------------------
# SOUND settings
# ---------------------------------------------------------------------
SAMPLE_RATE = 48000
BLOCK = 4800                 # ~0.1s per audio reading
BAND_LO = 1620               # cube tone band (Hz)
BAND_HI = 1740
SIGNAL_GATE_DB = -105
SMOOTH = 0.35
NEAR_LEVEL = 0.60
VERY_CLOSE = 0.85
TREND_FRAMES = 9             # ~0.6s at ~14 UI fps (warmer/colder lookback)
TREND_DELTA = 0.012

def slider_to_margin(s):
    return 14.0 - (s / 100.0) * 12.5

# ---------------------------------------------------------------------
# GLOW (screen) settings
# ---------------------------------------------------------------------
PROC_WIDTH = 640             # preserve rotating rune details while staying fast
MIN_PIXELS = 6               # min matching pixels to call it a glow
DEFAULT_TOL = 40
MIN_BRIGHT = 90

# Windows virtual-key codes for hotkeys.
VK = {"F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79}
user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def cursor_pos():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def resource_path(*parts):
    # PyInstaller bundles assets into sys._MEIPASS; source mode is relative to this file.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


BG = "#0d0d12"
FG_DIM = "#5a5a66"


# ---------------------------------------------------------------------
# AUDIO THREAD
# ---------------------------------------------------------------------
def audio_worker(out_queue, stop_event):
    freqs = np.fft.rfftfreq(BLOCK, 1 / SAMPLE_RATE)
    band_bins = np.where((freqs >= BAND_LO) & (freqs <= BAND_HI))[0]
    window = np.hanning(BLOCK)
    speaker = sc.default_speaker()
    loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)

    def band_level(samples):
        spec = np.abs(np.fft.rfft(samples * window))
        return np.sqrt(np.sum(spec[band_bins] ** 2)) / BLOCK

    with loopback.recorder(samplerate=SAMPLE_RATE, channels=2) as rec:
        while not stop_event.is_set():
            data = rec.record(numframes=BLOCK)
            l_lvl = band_level(data[:, 0])
            r_lvl = band_level(data[:, 1])
            level_db = 20 * np.log10((l_lvl + r_lvl) / 2 + 1e-9)
            balance = (r_lvl - l_lvl) / (l_lvl + r_lvl + 1e-9)
            try:
                out_queue.put_nowait((level_db, balance))
            except queue.Full:
                pass


# ---------------------------------------------------------------------
# COMBINED GUI
# ---------------------------------------------------------------------
class CubeFinder:
    def __init__(self, root, data_queue):
        self.root = root
        self.q = data_queue
        self.netq = queue.Queue(maxsize=300)
        self.capture = None
        self.netcubes = {}
        self.player_pos = None
        self.packet_count = 0
        self.network_stats = {}
        self.radar_window = None
        self.radar_overlay = None
        self.stats_window = None
        self.stats_text = None
        self.network_note = "Network idle"
        self.demo_mode = False
        self.last_alert = 0.0
        self.sound_on = tk.BooleanVar(value=True)
        self.glow_on = tk.BooleanVar(value=True)
        self.network_on = tk.BooleanVar(value=False)

        # --- audio state ---
        self.noise_db = -90.0
        self.peak_db = -62.0
        self.prox = 0.0
        self.balance = 0.0        # audio left/right
        self.detected = False
        self.margin_db = slider_to_margin(75)
        self.hist = collections.deque(maxlen=TREND_FRAMES + 1)

        # --- glow state ---
        self.sct = mss.mss()
        self.mon = self.sct.monitors[1]
        self.scale = max(1, int(self.mon["width"] / PROC_WIDTH))
        self.target, self.tol = read_glow_settings()
        self.settings_state = "LOADED" if self.target is not None else "NOT SET"
        self.max_area = 1.0
        self.glow = None          # (dx, dy, apparent_size) or None
        self.glow_refs = load_rotation_patterns(resource_path("assets", "rotation_patterns"))
        self.glow_smooth = None     # smoothed screen center, distinct from anchor
        self.glow_conf = 0.0
        self.glow_anchor = None   # downsampled screen location of the tracked glow
        self.glow_misses = 0
        self.glow_pixels = 0
        self.prev_keys = {k: False for k in VK}

        root.title("Aion 2 - Cube Finder v14 (aligned radar)")
        try:
            root.iconbitmap(str(resource_path("assets", "cube_finder.ico")))
        except (OSError, tk.TclError):
            pass
        root.configure(bg=BG)
        root.geometry("425x880")
        root.minsize(425, 800)
        root.attributes("-topmost", True)

        self.status = tk.Label(root, text="Listening...", fg=FG_DIM, bg=BG,
                               font=("Segoe UI", 20, "bold"))
        self.status.pack(pady=(10, 0))
        self.mode = tk.Label(root, text="", fg="#6cf", bg=BG,
                             font=("Segoe UI", 11, "bold"))
        self.mode.pack()

        controls = tk.Frame(root, bg=BG)
        controls.pack(pady=(5, 3))
        for text, var, action in (
            ("Sound", self.sound_on, None),
            ("Glow", self.glow_on, None),
            ("Network (Npcap)", self.network_on, self.toggle_network),
        ):
            tk.Checkbutton(controls, text=text, variable=var, command=action,
                           bg=BG, fg="#cbd5e1", selectcolor="#273142",
                           activebackground=BG, activeforeground="#ffffff",
                           font=("Segoe UI", 9)).pack(side="left", padx=5)

        tools = tk.Frame(root, bg=BG)
        tools.pack(pady=(1, 3))
        tk.Label(tools, text="Character (optional):", fg="#9ca3af", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left")
        self.character = tk.Entry(tools, width=14, bg="#212634", fg="#f1f5f9",
                                  insertbackground="#f1f5f9", relief="flat")
        self.character.pack(side="left", padx=5)
        tk.Button(tools, text="Replay PCAP", command=self.choose_replay,
                  bg="#263044", fg="white", relief="flat").pack(side="left", padx=2)

        backend_bar = tk.Frame(root, bg=BG)
        backend_bar.pack(pady=(1, 3))
        tk.Label(backend_bar,text="Network engine:",fg="#9ca3af",bg=BG,
                 font=("Segoe UI",9)).pack(side="left",padx=(0,4))
        self.backend_choice = tk.StringVar(value="Working radar")
        self.backend_menu = tk.OptionMenu(backend_bar,self.backend_choice,
                                         "Working radar","Experimental v12")
        self.backend_menu.config(bg="#263044",fg="white",highlightthickness=0,
                                 activebackground="#3c4b63")
        self.backend_menu.pack(side="left",padx=2)
        tk.Button(backend_bar,text="Show mini radar",command=self.show_mini_radar,
                  bg="#263044",fg="white",relief="flat").pack(side="left",padx=5)
        extra = tk.Frame(root, bg=BG)
        extra.pack(pady=(1, 4))
        tk.Button(extra, text="Demo cube", command=self.add_demo_cube,
                  bg="#293449", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(extra, text="Clear cubes", command=self.clear_cubes,
                  bg="#293449", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(extra, text="Network stats", command=self.show_network_stats,
                  bg="#293449", fg="white", relief="flat").pack(side="left", padx=4)
        # Named test phases make walking / approaching / opening counts
        # directly comparable in the copied, privacy-safe diagnostic summary.
        self.phase_info = tk.Label(root, text="Test phase: Unlabeled", bg=BG,
                                   fg="#d6c58a", font=("Segoe UI", 9))
        self.phase_info.pack(pady=(1, 1))
        phase_bar = tk.Frame(root, bg=BG)
        phase_bar.pack(pady=(1, 3))
        for text, key in (("1 Walk", "walking"), ("2 Near cube", "near"),
                          ("3 Open cube", "opening"), ("Stop phase", "unlabeled")):
            tk.Button(phase_bar, text=text, command=lambda k=key: self.set_test_phase(k),
                      bg="#293449", fg="white", relief="flat",
                      font=("Segoe UI", 8)).pack(side="left", padx=2)

        self.net_info = tk.Label(root, text="Network OFF | No cube coordinates",
                                 fg="#64748b", bg=BG, font=("Consolas", 9))
        self.net_info.pack(pady=2)
        self.net_detail = tk.Label(root, text="", fg="#9ca3af", bg=BG,
                                   font=("Consolas", 9), wraplength=405,
                                   justify="center")
        self.net_detail.pack(pady=(0, 4))

        self.aim = tk.Label(root, text="", fg="#4f8", bg=BG,
                            font=("Segoe UI", 14, "bold"))
        self.aim.pack(pady=(4, 2))

        # Crosshair: fed by GLOW when visible, else by SOUND (L/R only).
        self.cv = tk.Canvas(root, width=280, height=280, bg="#15151c",
                            highlightthickness=0)
        self.cv.pack()
        self.cv.create_line(140, 0, 140, 280, fill="#2a2a33")
        self.cv.create_line(0, 140, 280, 140, fill="#2a2a33")
        self.cv.create_oval(12, 12, 268, 268, outline="#303543", width=1)
        self.axis_items = {}
        for key, label, x, y in [("top", "UP", 140, 9), ("bottom", "DOWN", 140, 271),
                                 ("left", "L", 12, 140), ("right", "R", 268, 140)]:
            self.axis_items[key] = self.cv.create_text(x, y, text=label, fill="#555", font=("Segoe UI", 8))
        self.world_center = self.cv.create_oval(135, 135, 145, 145, fill="#22c55e", outline="#a7f3d0", state="hidden")
        self.axis_world_mode = None
        self.dot = self.cv.create_oval(134, 134, 146, 146, fill="#444",
                                       outline="")
        self.cross_note = tk.Label(root, text="GOLD = screen position | RED = world position",
                                   fg="#64748b", bg=BG, font=("Segoe UI", 8))
        self.cross_note.pack(pady=(2, 0))

        self.trend = tk.Label(root, text="", fg=FG_DIM, bg=BG,
                              font=("Segoe UI", 22, "bold"))
        self.trend.pack(pady=(6, 0))

        # Distance bar + number (audio).
        self.distnum = tk.Label(root, text="--%", fg=FG_DIM, bg=BG,
                                font=("Segoe UI", 16, "bold"))
        self.distnum.pack()
        self.distcv = tk.Canvas(root, width=300, height=22, bg="#1a1a22",
                                highlightthickness=0)
        self.distcv.pack(pady=(2, 0))
        self.distbar = self.distcv.create_rectangle(0, 0, 0, 22,
                                                     fill="#2a2", width=0)

        srow = tk.Frame(root, bg=BG)
        srow.pack(pady=(8, 0))
        tk.Label(srow, text="Sound sens.", fg="#aaa", bg=BG,
                 font=("Segoe UI", 9)).pack(side="left", padx=4)
        self.sens = tk.Scale(srow, from_=0, to=100, orient="horizontal",
                             length=200, bg=BG, fg="#aaa", troughcolor="#333",
                             highlightthickness=0, command=self.on_sens)
        self.sens.set(75)
        self.sens.pack(side="left")

        self.info = tk.Label(root, text="", fg="#4a4a55", bg=BG,
                             font=("Consolas", 8))
        self.info.pack(pady=(4, 0))
        tk.Label(root, text="F8 learn + save glow  F7 clear saved glow  F9/F10 tolerance  "
                 "F5/F6 sound sens", fg="#3a3a44", bg=BG,
                 font=("Segoe UI", 8)).pack()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.update_loop()

    def set_test_phase(self, phase):
        if self.capture is None:
            self.phase_info.config(text="Enable Network first")
            return
        self.capture.set_phase(phase)
        nice = {"walking": "1 - walking", "near": "2 - near cube",
                "opening": "3 - opening cube", "unlabeled": "Unlabeled / paused"}
        self.phase_info.config(text="Test phase: " + nice[phase])

    def start_capture(self, replay_path=None):
        self.packet_count = 0
        self.network_stats = {}
        if self.capture:
            self.capture.stop()
        self.netcubes.clear()
        self.player_pos = None
        self.demo_mode = False
        # Always listen on BOTH published game ports. Discovery is displayed
        # only as a hint; filtering to one endpoint would miss secondary ports.
        endpoints = [] if replay_path else discover_game_endpoints()
        selected = endpoints[0] if endpoints else None
        use_working = self.backend_choice.get() == "Working radar"
        factory = WorkingCapture if use_working else CaptureWorker
        self.capture = factory(
            self.netq,
            self.character.get(),
            server_ports=(13328, 13320),
            server_host=None,
        )
        self.backend_menu.config(state="disabled")
        if self.radar_window is not None and self.radar_window.winfo_exists():
            self.radar_window.destroy()
            self.radar_window = None
        if use_working:
            self.show_mini_radar()
        self.network_on.set(True)
        self.network_note = ("Working radar detector on 13328 + 13320"
                             if use_working else "Experimental v12 detector on 13328 + 13320")
        self.phase_info.config(text="Test phase: Unlabeled")
        self.capture.start(replay_path=replay_path)

    def toggle_network(self):
        if self.network_on.get():
            self.start_capture()
        else:
            if self.capture:
                self.capture.stop()
            self.capture = None
            self.netcubes.clear()
            self.player_pos = None
            self.network_note = "Network disabled"
            self.phase_info.config(text="Test phase: Unlabeled")
            self.backend_menu.config(state="normal")
            if self.radar_window is not None and self.radar_window.winfo_exists():
                self.radar_window.destroy()
                self.radar_window = None

    def show_mini_radar(self):
        """Optional source radar view sharing the already-active capture state."""
        if self.radar_window is not None and self.radar_window.winfo_exists():
            self.radar_window.lift()
            return
        if self.capture is None or not isinstance(self.capture,WorkingCapture):
            self.network_note="Enable Network with 'Working radar' selected first"
            return
        window=tk.Toplevel(self.root)
        self.radar_window=window
        self.radar_overlay=EmbeddedNetworkRadar(window,self.capture.state)

    def choose_replay(self):
        path = filedialog.askopenfilename(title="Select your local packet capture",
            filetypes=[("Capture files", "*.pcap *.pcapng"), ("All files", "*.*")])
        if path:
            self.start_capture(replay_path=path)

    def clear_cubes(self):
        self.netcubes.clear()
        self.player_pos = None
        self.net_detail.config(text="")

    def add_demo_cube(self):
        # A deterministic UI demo. Not evidence that live game decoding works.
        if self.capture:
            self.capture.stop()
            self.capture = None
        self.network_on.set(False)
        self.demo_mode = True
        self.netcubes = {90001: {"xyz": (2200.0, 700.0, 400.0), "template": 1000295}}
        self.player_pos = (0.0, 0.0, 0.0)
        self.network_note = "DEMO - simulated cube / positions"

    def process_network_events(self):
        for _ in range(150):
            try:
                event = self.netq.get_nowait()
            except queue.Empty:
                break
            kind = event.get("type")
            if kind == "cube":
                cube_id = event["id"]
                if event["action"] == "spawn":
                    is_new = cube_id not in self.netcubes
                    source = event.get("source", "stream")
                    prev = self.netcubes.get(cube_id)
                    # An unverified packet-local hit must never downgrade
                    # an already confirmed stream-decoded cube.
                    if prev is None or prev.get("source") == "packet-local" or source in ("stream", "working"):
                        self.netcubes[cube_id] = {"xyz": event["xyz"], "template": event["template"], "source": source}
                    if is_new:
                        self.alert_new_cube()
                else:
                    self.netcubes.pop(cube_id, None)
            elif kind == "player":
                self.player_pos = event["xyz"]
            elif kind == "zone_reset":
                self.clear_cubes()
            elif kind == "packets":
                self.packet_count = event["count"]
            elif kind == "network_stats":
                self.network_stats = event["stats"]
            elif kind in ("info", "warning", "error"):
                self.network_note = event["text"]
            elif kind == "network_stopped":
                if not (self.capture and self.capture.thread and self.capture.thread.is_alive()):
                    self.network_note = "Network capture stopped"

    def diagnostic_summary(self):
        """A safely shareable text summary: counters, no packets or IPs."""
        lines = ["Aion 2 Cube Finder v13 — working backend + optional experimental decoder",
                 "Ports 13328 + 13320: both directions counted; opcodes only from server-to-client.",
                 "The working network mode uses the user-confirmed radar parser unchanged; the experimental mode remains unverified.",
                 "PHASES: 1 Walk, 2 Near cube, 3 Open cube (click buttons during each activity)."]
        for key, value in sorted(self.network_stats.items()):
            if isinstance(value, list):
                lines.append(f"{key}: {', '.join(value) if value else '(none)'}")
            else:
                lines.append(f"{key}: {value}")
        if not self.network_stats:
            lines.append("No diagnostic data yet. Enable Network and wait for traffic.")
        return "\n".join(lines)

    def show_network_stats(self):
        if self.stats_window is not None and self.stats_window.winfo_exists():
            self.stats_window.lift()
            return
        win = tk.Toplevel(self.root)
        self.stats_window = win
        win.title("Network diagnostics (no packet contents)")
        win.geometry("700x560")
        win.configure(bg=BG)
        self.stats_text = tk.Text(win, wrap="word", bg="#15151c", fg="#dbeafe",
                                  font=("Consolas", 10), padx=10, pady=10)
        self.stats_text.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Button(win, text="Copy safe summary", command=self.copy_network_stats,
                  bg="#293449", fg="white", relief="flat").pack(pady=(0, 8))
        self.refresh_stats_window()

    def refresh_stats_window(self):
        if self.stats_window is None or not self.stats_window.winfo_exists():
            return
        self.stats_text.config(state="normal")
        self.stats_text.delete("1.0", "end")
        self.stats_text.insert("1.0", self.diagnostic_summary())
        self.stats_text.config(state="disabled")

    def copy_network_stats(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.diagnostic_summary())

    def alert_new_cube(self):
        # Alerts once per unique network entity, not on every sound/glow frame.
        if not self.sound_on.get():
            return
        import time
        now = time.monotonic()
        if now - self.last_alert < 2:
            return
        self.last_alert = now
        try:
            import winsound
            sound_file = resource_path("assets", "cube_alert.wav")
            if sound_file.exists():
                winsound.PlaySound(str(sound_file), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            else:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except (ImportError, RuntimeError):
            pass

    def nearest_cube(self):
        if not self.netcubes:
            return None
        if self.player_pos is None:
            entity = next(iter(self.netcubes.values()))
            return (entity["xyz"], None, None)
        px, py, pz = self.player_pos
        nearest = min(self.netcubes.values(), key=lambda c:
            sum((a-b)**2 for a, b in zip(c["xyz"], self.player_pos)))
        x,y,z = nearest["xyz"]
        planar = math.hypot(x-px, y-py) / 100.0
        altitude = (z-pz) / 100.0
        return (nearest["xyz"], planar, altitude)

    def close(self):
        self.save_glow_settings()
        if self.capture:
            self.capture.stop()
        if self.radar_window is not None and self.radar_window.winfo_exists():
            self.radar_window.destroy()
        try:
            self.sct.close()
        except Exception:
            pass
        self.root.destroy()

    def save_glow_settings(self):
        try:
            write_glow_settings(self.target, self.tol)
        except (OSError, ValueError) as exc:
            self.settings_state = "SAVE FAILED"
            print(f"[GLOW SETTINGS ERROR] Could not save glow calibration: {exc}")
        else:
            self.settings_state = "SAVED" if self.target is not None else "CLEARED"

    # --- sound sensitivity ---
    def on_sens(self, val):
        self.margin_db = slider_to_margin(float(val))

    def nudge_sens(self, d):
        self.sens.set(min(100, max(0, self.sens.get() + d)))

    # --- hotkeys ---
    def handle_keys(self):
        for name, vk in VK.items():
            now = key_down(vk)
            pressed = now and not self.prev_keys[name]
            self.prev_keys[name] = now
            if not pressed:
                continue
            if name == "F8":
                self.sample_glow()
            elif name == "F7":
                self.target = None
                self.glow = None
                self.max_area = 1.0
                self.glow_anchor = None
                self.glow_misses = 0
                self.glow_pixels = 0
                self.glow_smooth = None
                self.glow_conf = 0.0
                self.save_glow_settings()
            elif name == "F9":
                self.tol = max(5, self.tol - 5)
                self.save_glow_settings()
            elif name == "F10":
                self.tol = min(120, self.tol + 5)
                self.save_glow_settings()
            elif name == "F5":
                self.nudge_sens(-5)
            elif name == "F6":
                self.nudge_sens(+5)

    def sample_glow(self):
        """Average a small patch under the mouse = learned glow color."""
        x, y = cursor_pos()
        box = {"left": x - 5, "top": y - 5, "width": 10, "height": 10}
        patch = np.array(self.sct.grab(box))[:, :, :3]       # BGR
        b, g, r = patch.reshape(-1, 3).mean(axis=0)
        self.target = (int(r), int(g), int(b))
        self.max_area = 1.0
        self.glow_anchor = ((x - self.mon["left"]) / self.scale,
                            (y - self.mon["top"]) / self.scale)
        self.glow_misses = 0
        self.glow_smooth = None
        self.save_glow_settings()

    # --- audio intake ---
    def drain(self):
        latest = None
        try:
            while True:
                latest = self.q.get_nowait()
        except queue.Empty:
            pass
        return latest

    def scan_glow(self):
        """Identify glowing cube silhouette across multiple rotation poses."""
        if self.target is None:
            self.glow = None
            self.glow_pixels = 0
            self.glow_conf = 0.0
            return
        frame = np.array(self.sct.grab(self.mon))[:, :, :3]  # BGR
        small = frame[::self.scale, ::self.scale].copy()
        try:
            wx, wy = self.root.winfo_rootx(), self.root.winfo_rooty()
            app_rect = (wx, wy, wx + self.root.winfo_width(),
                        wy + self.root.winfo_height())
        except tk.TclError:
            app_rect = None
        exclude_window(small, self.mon, self.scale, app_rect)
        # The working radar mini-window belongs to this app too. Its red cube
        # markers must not be mistaken for the cube's rotating game glow.
        if self.radar_window is not None and self.radar_window.winfo_exists():
            try:
                radar_rect = (self.radar_window.winfo_rootx(),
                              self.radar_window.winfo_rooty(),
                              self.radar_window.winfo_rootx() + self.radar_window.winfo_width(),
                              self.radar_window.winfo_rooty() + self.radar_window.winfo_height())
                exclude_window(small, self.mon, self.scale, radar_rect)
            except tk.TclError:
                pass
        # F9/F10 change the similarity threshold: lower tolerance = stricter.
        base_conf = .64 if self.glow_anchor is not None else .69
        confidence_threshold = max(.54, min(.84, base_conf + (40 - self.tol) * .0025))
        result = find_cube(small, self.glow_refs, anchor=self.glow_anchor,
                           min_confidence=confidence_threshold)
        if result is None:
            # Remove dot immediately; never show a stale position after a miss.
            self.glow = None
            self.glow_pixels = 0
            self.glow_conf = 0.0
            self.glow_misses += 1
            # After a short gap allow finding a cube elsewhere on the screen.
            if self.glow_misses >= 28:
                self.glow_anchor = None
                self.glow_smooth = None
            return
        cx, cy, size, count, confidence = result
        # Smooth modest rune-center fluctuations caused by rotation.
        if self.glow_smooth is None or self.glow_misses > 4:
            sx, sy = cx, cy
        else:
            sx = self.glow_smooth[0] * .55 + cx * .45
            sy = self.glow_smooth[1] * .55 + cy * .45
        self.glow_smooth = (sx, sy)
        self.glow_anchor = (cx, cy)  # raw center for continuity gating
        self.glow_misses = 0
        self.glow_pixels = count
        self.glow_conf = confidence
        self.glow = (((sx / small.shape[1]) - 0.5) * 2,
                     ((sy / small.shape[0]) - 0.5) * 2, size)

    def update_loop(self):
        self.handle_keys()

        # --- network ---
        self.process_network_events()

        # --- audio ---
        reading = self.drain()
        if reading is not None:
            level_db, balance = reading
            has_signal = level_db > SIGNAL_GATE_DB
            if level_db < self.noise_db:
                self.noise_db = level_db
            else:
                self.noise_db += 0.015
            if level_db > self.peak_db:
                self.peak_db = level_db
            else:
                self.peak_db -= 0.02
            if self.peak_db - self.noise_db < 8:
                self.peak_db = self.noise_db + 8
            above = level_db - self.noise_db
            self.detected = self.sound_on.get() and has_signal and (above > self.margin_db)
            span = self.peak_db - (self.noise_db + self.margin_db)
            raw = float(np.clip(
                (level_db - (self.noise_db + self.margin_db)) / max(span, 1),
                0.0, 1.0))
            self.prox += (raw - self.prox) * SMOOTH
            self.balance += (balance - self.balance) * SMOOTH
        self.hist.append(self.prox)

        if not self.sound_on.get():
            self.detected = False

        # --- glow (only scans if enabled and color learned) ---
        if self.glow_on.get():
            self.scan_glow()
        else:
            self.glow = None
            self.glow_pixels = 0

        self.render()
        self.refresh_stats_window()
        self.root.after(70, self.update_loop)

    def _trend(self):
        if not self.detected or len(self.hist) <= TREND_FRAMES:
            return "none"
        d = self.hist[-1] - self.hist[0]
        if d > TREND_DELTA:
            return "warmer"
        if d < -TREND_DELTA:
            return "colder"
        return "steady"

    def set_axis_mode(self, world: bool):
        """Never describe a world-coordinate plot as camera-relative directions."""
        if self.axis_world_mode == world:
            return
        self.axis_world_mode = world
        labels = ({"top":"+X","bottom":"-X","left":"-Y","right":"+Y"} if world
                  else {"top":"UP","bottom":"DOWN","left":"L","right":"R"})
        for key, item in self.axis_items.items():
            self.cv.itemconfig(item, text=labels[key])
        self.cv.itemconfig(self.world_center, state="normal" if world else "hidden")
        self.cross_note.config(text=("RED = world X/Y map (NOT camera-facing direction)" if world else
                                     "GOLD = cube's position on screen (NOT distance)"))

    def render(self):
        glow = self.glow
        nearest = self.nearest_cube()
        if self.netcubes:
            provisional = sum(c.get("source") == "packet-local" for c in self.netcubes.values())
            label = f"CUBES {len(self.netcubes)}" + (f" ({provisional} provisional)" if provisional else "")
            self.net_info.config(text=f"{label} | packets {self.packet_count}",
                                 fg="#f87171")
        else:
            self.net_info.config(text=(self.network_note + f" | packets {self.packet_count}")[:65],
                                 fg="#94a3b8")
        if nearest and nearest[1] is not None:
            flat, height = nearest[1], nearest[2]
            dist3d = math.hypot(flat, height)
            label = f"Cube: {flat:.1f}m horizontal | {dist3d:.1f}m 3D | height {height:+.1f}m"
            if isinstance(self.capture, WorkingCapture) and self.capture.state.last_pos_time:
                age = time.time() - self.capture.state.last_pos_time
                if age > 5:
                    label += f" | position {age:.0f}s old"
            self.net_detail.config(text=label, fg="#fbbf24" if " old" in label else "#e2e8f0")
        elif nearest:
            self.net_detail.config(text="Cube coords received; player position unknown")
        else:
            self.net_detail.config(text="No network cube target")

        # --- crosshair priority: GLOW > NETWORK (world X/Y) > SOUND ---
        if glow is not None:
            self.set_axis_mode(False)
            dx, dy, size = glow
            px, py = 140 + dx * 130, 140 + dy * 130
            rad = 5 + size * 10  # larger spot = larger visible glow; not meters
            self.cv.coords(self.dot, px - rad, py - rad, px + rad, py + rad)
            self.cv.itemconfig(self.dot, fill="#fd4")       # gold = glow
            self.mode.config(text="● GLOW SEEN — screen direction", fg="#fd4")
            parts = []
            if dx < -0.12: parts.append("◀ LEFT")
            elif dx > 0.12: parts.append("RIGHT ▶")
            if dy < -0.12: parts.append("UP ▲")
            elif dy > 0.12: parts.append("DOWN ▼")
            self.aim.config(text="  ".join(parts) if parts else "ON TARGET",
                            fg="#4f8")
        elif nearest and self.player_pos is not None:
            self.set_axis_mode(True)
            # Same world +Y-right / +X-up projection AND 150m scale as the
            # source mini-radar. No independent axis swap or per-axis clip.
            proj = project_cube(self.player_pos, nearest[0], center=(140, 140),
                                radius_px=128, range_m=150, margin_px=16)
            tx, ty = proj.screen_x, proj.screen_y
            self.cv.coords(self.dot, tx-9, ty-9, tx+9, ty+9)
            self.cv.itemconfig(self.dot, fill="#ff5555")
            self.mode.config(text="● NETWORK CUBE — WORLD MAP", fg="#f55")
            edge = " | beyond 150m" if proj.off_scale else ""
            self.aim.config(text=f"{proj.distance_3d_m:.1f}m 3D | height {proj.height_m:+.1f}m{edge}", fg="#f88")
        elif self.detected:
            self.set_axis_mode(False)
            # Audio only: dot on horizontal axis (no vertical info).
            px = 140 + self.balance * 130
            self.cv.coords(self.dot, px - 7, 133, px + 7, 147)
            self.cv.itemconfig(self.dot, fill="#4af")        # blue = sound
            self.mode.config(text="♪ SOUND — move to bring cube into view",
                             fg="#6cf")
            if self.balance < -0.12:
                self.aim.config(text="◀ LEFT", fg="#6cf")
            elif self.balance > 0.12:
                self.aim.config(text="RIGHT ▶", fg="#6cf")
            else:
                self.aim.config(text="straight — use WARMER/COLDER", fg="#6cf")
        else:
            self.set_axis_mode(False)
            self.cv.coords(self.dot, 134, 134, 146, 146)
            self.cv.itemconfig(self.dot, fill="#444")
            self.mode.config(text="", fg=FG_DIM)
            self.aim.config(text="")

        # --- warmer/colder (audio) ---
        tr = self._trend()
        if tr == "warmer":
            self.trend.config(text="▲ WARMER", fg="#5d5")
        elif tr == "colder":
            self.trend.config(text="▼ COLDER", fg="#e55")
        elif tr == "steady":
            self.trend.config(text="• steady", fg="#aa7")
        else:
            self.trend.config(text="", fg=FG_DIM)

        # --- distance bar + number (audio) ---
        width = int(300 * self.prox)
        self.distcv.coords(self.distbar, 0, 0, width, 22)
        if self.prox < 0.5: col = "#2a2"
        elif self.prox < NEAR_LEVEL: col = "#9d2"
        elif self.prox < VERY_CLOSE: col = "#fa2"
        else: col = "#f33"
        self.distcv.itemconfig(self.distbar, fill=col)
        self.distnum.config(text=f"{self.prox*100:.0f}%" if self.detected
                            else "--%", fg=col if self.detected else FG_DIM)

        # --- status: show whichever detector currently has a signal ---
        if glow is not None:
            self.status.config(text="GLOW IN VIEW", fg="#fd4")
        elif self.detected and self.prox >= VERY_CLOSE:
            self.status.config(text="VERY CLOSE!", fg="#f66")
        elif self.detected and self.prox >= NEAR_LEVEL:
            self.status.config(text="CUBE NEAR", fg="#fb5")
        elif nearest is not None:
            has_confirmed = any(c.get("source") != "packet-local" for c in self.netcubes.values())
            self.status.config(text="NETWORK CUBE!" if has_confirmed else "POSSIBLE NETWORK CUBE", fg="#f66" if has_confirmed else "#fa5")
        elif self.detected:
            self.status.config(text="DETECTED", fg="#6cf")
        else:
            self.status.config(text="NO CUBE", fg="#555")

        self.info.config(
            text=f"glow {self.target} [{self.settings_state}]  tol {self.tol}  cube match {self.glow_conf:.0%}  pixels {self.glow_pixels}\n"
                 f"sound margin {self.margin_db:.1f}dB")


def safe_audio_worker(q, stop_event):
    try:
        audio_worker(q, stop_event)
    except Exception as exc:
        print(f"[AUDIO ERROR] {exc}")


def main():
    data_queue = queue.Queue(maxsize=5)
    stop_event = threading.Event()
    threading.Thread(target=safe_audio_worker, args=(data_queue, stop_event),
                     daemon=True).start()
    root = tk.Tk()
    CubeFinder(root, data_queue)
    try:
        root.mainloop()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
