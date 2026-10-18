"""
Cube Finder  -  2-in-1 (sound + screen glow)
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

Both only READ (your audio + your own screen pixels). Nothing is read
from or injected into the game - no ToS/ban risk.

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
PROC_WIDTH = 480             # downscale screen to this width for speed
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
        self.target = None
        self.tol = DEFAULT_TOL
        self.max_area = 1.0
        self.glow = None          # (dx, dy, size) or None
        self.prev_keys = {k: False for k in VK}

        root.title("Cube Finder (sound + glow)")
        root.configure(bg=BG)
        root.geometry("380x640")
        root.attributes("-topmost", True)

        self.status = tk.Label(root, text="Listening...", fg=FG_DIM, bg=BG,
                               font=("Segoe UI", 20, "bold"))
        self.status.pack(pady=(10, 0))
        self.mode = tk.Label(root, text="", fg="#6cf", bg=BG,
                             font=("Segoe UI", 11, "bold"))
        self.mode.pack()

        self.aim = tk.Label(root, text="", fg="#4f8", bg=BG,
                            font=("Segoe UI", 14, "bold"))
        self.aim.pack(pady=(4, 2))

        # Crosshair: fed by GLOW when visible, else by SOUND (L/R only).
        self.cv = tk.Canvas(root, width=280, height=280, bg="#15151c",
                            highlightthickness=0)
        self.cv.pack()
        self.cv.create_line(140, 0, 140, 280, fill="#2a2a33")
        self.cv.create_line(0, 140, 280, 140, fill="#2a2a33")
        for t, x, y in [("UP", 140, 9), ("DOWN", 140, 271),
                        ("L", 12, 140), ("R", 268, 140)]:
            self.cv.create_text(x, y, text=t, fill="#555",
                                font=("Segoe UI", 8))
        self.dot = self.cv.create_oval(134, 134, 146, 146, fill="#444",
                                       outline="")

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
        tk.Label(root, text="F8 learn glow  F7 clear  F9/F10 glow tol  "
                 "F5/F6 sound sens", fg="#3a3a44", bg=BG,
                 font=("Segoe UI", 8)).pack()

        self.update_loop()

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
            elif name == "F9":
                self.tol = max(5, self.tol - 5)
            elif name == "F10":
                self.tol = min(120, self.tol + 5)
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
        """Look for the learned glow color on screen. Sets self.glow."""
        if self.target is None:
            self.glow = None
            return
        frame = np.array(self.sct.grab(self.mon))[:, :, :3]   # BGR
        small = frame[::self.scale, ::self.scale]
        b = small[:, :, 0].astype(np.int16)
        g = small[:, :, 1].astype(np.int16)
        r = small[:, :, 2].astype(np.int16)
        tr, tg, tb = self.target
        dist = np.abs(r - tr) + np.abs(g - tg) + np.abs(b - tb)
        bright = (r + g + b) / 3
        mask = (dist < self.tol * 3) & (bright > MIN_BRIGHT)
        ys, xs = np.where(mask)
        if len(xs) >= MIN_PIXELS:
            cx = xs.mean() / small.shape[1]
            cy = ys.mean() / small.shape[0]
            self.max_area = max(self.max_area, len(xs))
            self.glow = ((cx - 0.5) * 2, (cy - 0.5) * 2, len(xs) / self.max_area)
        else:
            self.glow = None

    def update_loop(self):
        self.handle_keys()

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
            self.detected = has_signal and (above > self.margin_db)
            span = self.peak_db - (self.noise_db + self.margin_db)
            raw = float(np.clip(
                (level_db - (self.noise_db + self.margin_db)) / max(span, 1),
                0.0, 1.0))
            self.prox += (raw - self.prox) * SMOOTH
            self.balance += (balance - self.balance) * SMOOTH
        self.hist.append(self.prox)

        # --- glow (only scans if a color has been learned) ---
        self.scan_glow()

        self.render()
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

    def render(self):
        glow = self.glow

        # --- crosshair dot: glow if visible, else audio (L/R only) ---
        if glow is not None:
            dx, dy, size = glow
            px, py = 140 + dx * 130, 140 + dy * 130
            rad = 6 + size * 16
            self.cv.coords(self.dot, px - rad, py - rad, px + rad, py + rad)
            self.cv.itemconfig(self.dot, fill="#fd4")       # gold = glow
            self.mode.config(text="● GLOW IN VIEW — precise aim", fg="#fd4")
            parts = []
            if dx < -0.12: parts.append("◀ LEFT")
            elif dx > 0.12: parts.append("RIGHT ▶")
            if dy < -0.12: parts.append("UP ▲")
            elif dy > 0.12: parts.append("DOWN ▼")
            self.aim.config(text="  ".join(parts) if parts else "ON TARGET",
                            fg="#4f8")
        elif self.detected:
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

        # --- status (audio proximity) ---
        if self.detected and self.prox >= VERY_CLOSE:
            self.status.config(text="VERY CLOSE!", fg="#f66")
        elif self.detected and self.prox >= NEAR_LEVEL:
            self.status.config(text="CUBE NEAR", fg="#fb5")
        elif self.detected:
            self.status.config(text="DETECTED", fg="#6cf")
        else:
            self.status.config(text="NO CUBE", fg="#555")

        self.info.config(
            text=f"glow {self.target}  tol {self.tol}  "
                 f"margin {self.margin_db:.1f}dB")


def main():
    data_queue = queue.Queue(maxsize=5)
    stop_event = threading.Event()
    threading.Thread(target=audio_worker, args=(data_queue, stop_event),
                     daemon=True).start()
    root = tk.Tk()
    CubeFinder(root, data_queue)
    try:
        root.mainloop()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
