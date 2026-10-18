# Aion 2 Cube Finder — Developer, GitHub & Windows EXE Handoff

**Baseline:** v17 — Dual Radars (Network + Sound/Glow)  
**Document date:** 2026-10-18  
**Platform:** Windows 10/11, 64-bit  
**Implementation:** Python 3.12, PySide6, Npcap/Scapy, NumPy, SoundCard, MSS, OpenCV, LZ4  
**Status:** Source builds and tests offline; **the complete v17 GUI and its packaged EXE have NOT yet been confirmed working on the user's Windows gaming PC.**

> **Read this before publishing:** `working_aion_radar.py` is derived from a third-party/user-supplied Aion 2 radar. Its redistribution license has **not** been established. Do not make this repository public or release a binary containing that code until you have checked the upstream license and obtained any permission required. Also check the rights to the game screenshots/reference assets. See [Licensing and privacy](#11-licensing-privacy-and-game-rules).

This is the source-of-truth handoff for continuing the project. It deliberately distinguishes working behaviors observed during earlier live tests from features only covered by offline tests. Do **not** treat a passing unit test as proof of live Aion 2 Global compatibility.

## Contents

1. [Goal and current architecture](#1-goal-and-current-architecture)
2. [Current status: working, partial, unverified](#2-current-status-working-partial-unverified)
3. [Prerequisites and dependencies](#3-prerequisites-and-dependencies)
4. [Install and run from source](#4-install-and-run-from-source)
5. [User guide: dashboard, two overlays, hotkeys](#5-user-guide-dashboard-two-overlays-hotkeys)
6. [Settings, assets and project layout](#6-settings-assets-and-project-layout)
7. [Network and audio technical details](#7-network-and-audio-technical-details)
8. [Tests, diagnostics and acceptance checklist](#8-tests-diagnostics-and-acceptance-checklist)
9. [Build and distribute the Windows EXE](#9-build-and-distribute-the-windows-exe)
10. [GitHub upload and release checklist](#10-github-upload-and-release-checklist)
11. [Licensing, privacy and game rules](#11-licensing-privacy-and-game-rules)
12. [Known limitations and troubleshooting](#12-known-limitations-and-troubleshooting)
13. [Version history and next steps](#13-version-history-and-next-steps)
14. [Handoff to the next developer or assistant](#14-handoff-to-the-next-developer-or-assistant)

---

## 1. Goal and current architecture

Build an **all-in-one, local-only Aion 2 Global Hidden Cube assistant** using three independent signals:

- **Network (Npcap):** Passively observes game TCP traffic; decodes cube spawn/removal data and player position. This is the **only** mode with game-world coordinates and calculated meters/elevation.
- **Sound:** Reads Windows **default speaker loopback**, analyses energy around **1,620–1,740 Hz** (nominal 1,680 Hz hum), tracks the relative strength and stereo left/right balance. It does **not** measure accurate physical distance in meters or a full 360° bearing.
- **Vision/Glow:** Captures screen pixels, uses recorded cube rotation patterns plus optional F8 learned RGB/anchor, and displays the cube's **screen** position (gold marker). It is **not** a world-coordinate radar.

A PySide6 dashboard coordinates the detectors and displays **two separate always-on-top overlays**:

```text
                       cube_finder_modern.py (PySide6 dashboard)
                                      |
                           modern_engine.py
                                      |
             +------------------------+-----------------------+
             |                        |                       |
     Working network backend    SoundCard + NumPy      MSS + OpenCV
     working_network_capture   1680 Hz analysis       rotation/glow scan
       -> working_aion_radar      stereo + trend        F8 calibration
             |                        |                       |
      actual XYZ / cubes         relative 0–100%      screen X/Y marker
             |                        |                       |
       NetworkHud (red)        SoundHud (cyan + optional gold)
                       + shared overview / diagnostics
```

**Default network backend:** `Working radar`, an adapter of the user-supplied source in `working_aion_radar.py`. **Alternative:** `Experimental v12`, retained for diagnostics, not the recommended live option. Only **one** network capture backend should be running at a time.

## 2. Current status: working, partial, unverified

These labels matter when reporting features on GitHub:

- **Confirmed in earlier live tests:** User reported that the original, standalone uploaded `aion2_radar.py` showed **red cube markers and a changing distance in meters** on Aion 2 Global. Separately, early Cube Finder versions detected the 1,680 Hz sound and tracked a cube's glow after F8 calibration. Npcap successfully captured live traffic on TCP port 13328.
- **Implemented + offline-tested in v17:** The Qt dashboard; separate network and sound HUDs; sound strength, pulsing cyan horizontal marker and warmer/colder guidance; optional gold screen marker; capture adapter; network alert beep; settings persistence; diagnostic summary; PyInstaller build script. **95 Python unit tests pass locally.** The same test suite was run during this handoff and passed (95 tests). Python source compilation also passed.
- **Not yet demonstrated live in v17:** Both HUDs running together in the actual game, correct live audio marker behavior on your machine, reliable vision tracking across game scenes, accurate cube removal in integrated UI, overlays/drag/click-through under your chosen graphics mode, and running the **PyInstaller EXE** on Windows. Do not mark these as fully validated before testing.

| Component | Current evidence | Limitations / action |
|---|---|---|
| Original standalone network radar | **User-confirmed live** cube markers and changing meters | Validate that the **v17 adapter** reproduces this behavior |
| v17 default Npcap capture | Implemented; unit-tested | Must test actual global server traffic and privileges |
| v17 network overlay | Implemented; geometry tested | Needs live accuracy test; world bearing is **not camera-relative** |
| Audio loopback, 1680 Hz | Prior live signal confirmed; v17 processing present | Other game sounds can trigger false positives; must test output device |
| Sound HUD | **v17: offline tested only** | Cyan dot is **stereo left/right**, never a full radar position |
| Glow / rotating cube | User provided images/videos; 25 rotation templates shipped | False positives/missed detections possible; live v17 confirmation needed |
| F8 RGB persistence | Implemented/tested | Color survives restarts, but the current screen anchor is session-only |
| Independent network alert WAV | Implemented/tested | Confirm the sound plays from the Windows build; 2-second alert cooldown |
| Settings persistence | Implemented/tested | Validate saving/loading and HUD positions on Windows |
| Network stats / PCAP replay | Implemented | Do not publish raw PCAPs; logs are useful only if capture works |
| Windows EXE | **Build script supplied, not yet executed/QA-tested in Windows** | Build on Windows, test on a clean Windows machine |

## 3. Prerequisites and dependencies

### Required for development / running from source

- **Windows 10 or 11, x64.** Linux/macOS are not supported live targets; the program uses Windows loopback audio, hotkey APIs and Npcap.
- **Python 3.12 x64** and the Windows `py` launcher (`py -3.12 --version`). Python 3.12.0 was previously used successfully by the user. Avoid silently choosing Python 3.15; it previously triggered an LZ4 native-package compilation error on the user's machine.
- **Npcap** from <https://npcap.com/> for live network capture. The machine already had Npcap working in earlier tests; reinstalling it is **not** a decoder fix.
- An active **Ethernet** or Wi-Fi adapter and the Aion 2 Global client, for actual game verification.
- Windows default **stereo speaker/headphone playback** with game sound audible for the sound detector; it listens to output loopback, **not** the microphone.
- Internet access for the first `pip install` or a prepared offline package cache.

### Python packages (source: `requirements.txt`)

```text
PySide6>=6.7,<7
numpy>=1.26
soundcard>=0.4.3
mss>=9.0
scapy>=2.5
lz4>=4.3
psutil>=5.9
opencv-python-headless>=4.10,<5
```

The build script separately installs **PyInstaller** when packaging an EXE; it is not currently pinned in `requirements.txt`.

- **PySide6:** Dashboard and translucent overlays (Qt).
- **NumPy + SoundCard:** Spectrum measurement and Windows speaker loopback.
- **MSS + OpenCV:** Screen sampling, rotation-aware image matching, optional glow calibration.
- **Scapy + Npcap:** Packet capture and replay.
- **LZ4 + psutil:** Protocol processing and game connection discovery.

Npcap installer checkboxes are not a substitute for testing. The project reads normal IP/TCP traffic on Ethernet; raw Wi-Fi monitor mode is unnecessary. If you choose administrator-restricted capture, launch with administrator privileges. No claim is made that Npcap or passive sniffing is undetectable or game-policy compliant.

## 4. Install and run from source

### A. Easy installation (recommended)

1. Download/extract the v17 project into a **new folder**, e.g. `C:\Aion2CubeFinder\`. Keep the contents intact, including `assets/` and `tests/`.
2. Ensure `py -3.12 --version` returns `Python 3.12.x`.
3. Run `INSTALL.bat` **once**. It creates `.venv` using Python 3.12, upgrades pip and installs `requirements.txt`.
4. Run `RUN_TESTS.bat` for the offline suite.
5. Run `START.bat` to open `cube_finder_modern.py`.
6. If Npcap is denied by Windows access controls, close the app and use `START_AS_ADMIN.bat` (Windows UAC). Do not run elevated by default unless necessary.

### B. Exact commands in Command Prompt

Open `cmd` **in the project folder** (File Explorer address bar -> `cmd`):

```bat
py -3.12 --version
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe cube_finder_modern.py
```

Do not substitute `python` or `pip` from the system PATH if multiple Python versions are installed. Always use `.venv\Scripts\python.exe` for reproducibility.

**Optional GitHub fetch:** `FETCH_GITHUB_ASSETS.bat` downloads separate upstream files for review, **not** for execution or required startup. A previous attempt failed on the user's PC with an SSL certificate validation error; this does **not** affect core Cube Finder operation. Do not work around SSL errors by disabling certificate verification.

## 5. User guide: dashboard, two overlays, hotkeys

### Dashboard pages

- **Overview:** Spatial radar, 3D cube distance and elevation cards, relative audio bar, quick show/hide controls for both HUDs.
- **Detection:** Npcap toggle, backend selector, optional character name (not saved), network alert beep, sound detector, sound sensitivity, glow detector/color calibration, replay PCAP and demo cube.
- **Diagnostics:** Network counters, 3 test phases (walking, near cube, opening) and a **Copy safe summary** control. Counters alone do not prove packet decoding correctness.
- **Settings:** Independent HUD visibility/opacity/scale/click-through options. The HUDs can be dragged to different locations; their positions are stored on normal app exit.

### Overlay 1 — Network Radar (red/mint)

- Red dots are server-decoded cube **world-coordinate** positions relative to the player (when player XYZ is available); mint is player center.
- Default plotted world scale: **150 meters**. Marker projection uses `world +Y = screen right`, `world +X = screen up` — it does **not** rotate with the in-game camera.
- `3D DISTANCE` uses the three axes, with **100 game-coordinate units = 1 meter**. Elevation is shown independently.
- A stale-position warning appears when there has not been a player-coordinate update for more than ~5 seconds. A stale coordinate is **not** accurate live positioning.
- If the cube has XYZ but the player XYZ is unknown, markers/distance may remain unavailable.

### Overlay 2 — Sound Direction Radar (cyan/gold)

- **Cyan marker:** left/right stereo balance of audio energy near 1,680 Hz; moves **only horizontally**. A central dot does **not** prove the cube is in front; rear sources, reflections and game mixing can confound it.
- **Gold marker:** optional glow/rotation vision result, indicating **on-screen** left/right and up/down. It is not generated by audio and only appears when the vision tracker has a sufficiently confident match.
- **Percentage / flashing pulse:** normalized **relative** audio strength, **not** meters. The signal scale varies with background noise, sound volume, terrain and other audio sources.
- **Warmer / Colder / Steady:** recent rise/fall of the detected hum's strength. To search, rotate camera slowly and move a little at a time while observing the trend.
- This HUD is **independent** of Npcap; turning the network overlay on must not hide the sound radar.

### Hotkeys currently implemented

| Shortcut | Action | Notes |
|---|---|---|
| `F5` / `F6` | Decrease / increase sound sensitivity | Applies to loopback signal detector |
| `F7` | Clear saved glow color | Persists cleared setting |
| `F8` | Learn glow RGB under mouse | Aim cursor at the cube's glowing area; may require app elevated while game has focus |
| `F9` / `F10` | Decrease / increase glow tolerance | Saved automatically |
| `Ctrl + Shift + F10` | Toggle network HUD | Overlay visibility only; doesn't enable/disable packet capture |
| `Ctrl + Shift + F11` | Toggle sound HUD | Overlay visibility only; doesn't enable/disable audio sensing |

**Hotkey caution:** Game focus/privilege level may prevent `GetAsyncKeyState` polling. Use the UI or run as Administrator only if required. Enabling click-through prevents dragging a HUD until click-through is switched off from the dashboard.

### First live-game run (one simple sequence)

1. Keep the default **Working radar** network backend.
2. Open Aion 2 in **Borderless Windowed** (or Windowed) mode; fullscreen exclusive may cover overlays.
3. In the dashboard, enable **Npcap capture**, and separately **1680 Hz sound detection** and **Glow** as desired.
4. Walk normally and verify inbound packet count rises on the relevant server port (earlier captures used **13328**; 13320 may remain idle).
5. Approach a known unopened Hidden Cube, verify cube marker and changing distance **if** player position stays current.
6. Observe the sound strength and stereo direction; optionally press F8 while hovering over cube glow, then rotate the camera and confirm the gold marker tracks the cube.
7. Open the cube. Confirm the network cube disappears if a removal event is decoded and the glow marker disappears after the cube vanishes.
8. Open **Diagnostics** and copy a safe summary if anything does not match expectations.

## 6. Settings, assets and project layout

```text
Aion2_Cube_Finder_v17_Sound_Radar/
├─ README.md                   Quick user guide
├─ DEVELOPER_HANDOFF.md        THIS file: source-of-truth handoff
├─ UPSTREAM_SOURCES.md         Existing attribution notes; resolve license before publishing
├─ requirements.txt
├─ INSTALL.bat                 Python 3.12 venv + pip packages
├─ START.bat                   Launch Qt app
├─ START_AS_ADMIN.bat          UAC-elevated Qt launch if capture denied
├─ RUN_TESTS.bat               Python unittest suite
├─ BUILD_EXE.bat               PyInstaller one-folder build
├─ FETCH_GITHUB_ASSETS.bat     Optional upstream-file download
├─ cube_finder_modern.py       Main PySide6 dashboard (entry point)
├─ modern_engine.py            Shared detection state, audio, glow, events, alerts, keys
├─ dual_overlays.py            Two independent Qt HUD windows
├─ sound_direction.py          Horizontal stereo marker + visual marker geometry
├─ radar_geometry.py           Consistent world map projection and meter conversion
├─ working_network_capture.py Default backend adapter, single Npcap sniffer
├─ working_aion_radar.py       User-supplied working PureStreamEngine source
├─ network_capture.py         Experimental decoder option
├─ aion_protocol_v11.py       Experimental/research protocol parser
├─ game_connections.py       Game process/network discovery
├─ glow_tracking.py           Pixel/color clustering logic
├─ rotation_tracking.py       Cube shape/rotation pattern matching
├─ glow_settings.py           Persistent F8 RGB and tolerance
├─ ui_config.py               Persistent window preferences
├─ cube_finder_original.py    Original sound+pixel project reference
├─ legacy_cube_finder_tk.py   Old Tkinter implementation, not app entry point
├─ packet_local_probe.py      Research/diagnostic helper
├─ sync_github_sources.py     Optional upstream review fetcher
├─ assets/
│  ├─ cube_alert.wav           New-network-cube notification
│  ├─ cube_finder.ico/.png     Application icon
│  ├─ reference_cubes/        User-provided cube images
│  └─ rotation_patterns/      25 reference images extracted from two user videos
└─ tests/                     unittest-based offline tests (95 passing)
```

Saved preferences live **outside** the project folder so they survive upgrades:

| Windows path | Saved data |
|---|---|
| `%LOCALAPPDATA%\Aion2CubeFinder\ui_settings.json` | HUD visibility, opacity, size, click-through, screen positions, backend and detector toggles/sensitivity |
| `%LOCALAPPDATA%\Aion2CubeFinder\settings.json` | Learned RGB glow color and glow tolerance |

These files are **not** copied into GitHub or the EXE by default. Character names, raw packets and game traffic are not deliberately stored in these preferences. For a full reset, close the app, back up the two settings files, and move/remove them before restart. Saved F8 color persists across versions using the same settings path; the temporary on-screen calibration anchor does not.

### Default v17 config (highlights)

`network_backend='Working radar'`, sound enabled, glow enabled, network alerts enabled, both HUDs visible, opacity 88%, scale 100%, click-through disabled. Valid opacity range **45–100%**; HUD scale **70–150%**; sound sensitivity **0–100**.

## 7. Network and audio technical details

### Network path and event pipeline

- `working_network_capture.WorkingCapture` watches TCP ports **13328 and 13320**, both traffic directions, with a Scapy BPF filter; optional server-host filtering exists in the adapter.
- It passes captured IP/port/payload arguments into the original `working_aion_radar.PureStreamEngine.feed_payload` and observes changes to its shared `RadarState`.
- An adapter publishes only events (cube spawn/removal, player XYZ, status and counters) through a queue; `modern_engine.DetectionEngine` consumes these in the UI tick.
- Existing cube templates include multiple Elyos and Asmodian IDs. **Do not assume every template is validated on the current Global patch.**
- The original uploaded parser handles **each TCP payload separately** rather than robustly reconstructing arbitrary split TCP frames. It happened to work in the user's standalone live test, but that is a technical limitation; do not claim complete TCP reconstruction for this default backend.
- `network_capture.py` + `aion_protocol_v11.py` are the **experimental v12** alternative and research path. They do not replace the user-confirmed working parser in the default configuration.
- Only one sniffer is started by the Qt application, even though it displays two overlays.
- A new cube triggers `assets/cube_alert.wav` if network alerts are enabled. There is a **2-second alert cooldown**. This is independent of enabling the 1680 Hz detector.

### Sound and glow path

- SoundCard `default_speaker()` + loopback `get_microphone(..., include_loopback=True)`; stereo blocks of **4,800 frames @ 48 kHz**, ~0.1 s each.
- NumPy FFT tracks the **1620–1740 Hz** band, smooths signal strength and L/R balance, computes an adaptive noise floor and warmer/colder trend.
- Sound is sampled only from the active default output. Changing default audio output while the app is already running may require restarting the app.
- MSS captures the primary screen (`monitors[1]`), and OpenCV matches red/orange cube shapes against the **25** recorded rotation patterns. This means a cube on a secondary display is not automatically covered.
- The visual tracker excludes visible Cube Finder windows to avoid matching its **own** gold/red markers. Similar-colored game UI and scenery can still produce false matches; confidence and anchor behavior are experimental.
- F8 samples a 10x10 pixel patch at the cursor for the RGB target, persists it, and uses an **in-session** anchor. F7 clears the saved color; F9/F10 change tolerance.

## 8. Tests, diagnostics and acceptance checklist

### Offline tests

Run:

```bat
RUN_TESTS.bat
```

Or:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**Baseline result:** `Ran 95 tests ... OK` (confirmed during the creation of this handoff). The tests exercise radar geometry, packet parsing fixtures, queue integration, audio marker geometry, rotation/glow matching, settings and other regression paths. The tests do **not** prove Qt display correctness, administrator hotkeys, real game protocol stability or Windows EXE packaging.

### Manual acceptance checklist — required before claiming v17 is release-ready

- [ ] Run `INSTALL.bat` on a clean Windows 10/11 x64 machine with Python 3.12 and Npcap installed.
- [ ] Run `RUN_TESTS.bat` and capture results.
- [ ] `START.bat` launches dashboard with no console traceback.
- [ ] Dashboard has **two independent** floating HUDs, each draggable and always-on-top in **Borderless Windowed** game mode.
- [ ] Both opacity/size controls and show/hide toggles work and persist after restart.
- [ ] HUD click-through works; turning it off via dashboard restores dragging.
- [ ] Audio HUD remains visible when network capture starts and finds a cube.
- [ ] Sound HUD percentage, cyan horizontal marker, pulse, warmer/colder update near a cube; no spurious claims of meters.
- [ ] F8 color save -> restart -> RGB reload; optional gold marker tracks a visible cube; F7 clears preset.
- [ ] Npcap traffic counters increase on the actual Aion 2 Global connection (historically port 13328).
- [ ] Default `Working radar` backend shows a real cube and a changing meter value as player approaches.
- [ ] Network HUD and dashboard indicate the same **world** direction, not necessarily camera direction.
- [ ] Fresh player XYZ updates continue; stale coordinate status correctly warns after >5s.
- [ ] Opening an unopened cube removes its corresponding marker; entering a new zone clears stale cubes.
- [ ] New cube plays `cube_alert.wav` once; disabling **audio detection** does not silence independently enabled network alerts.
- [ ] `BUILD_EXE.bat` completes on Windows; EXE runs from its `dist` folder with `assets/` included.
- [ ] EXE works after copying the **entire one-folder distribution** to another Windows test machine with Npcap installed.
- [ ] Test error cases: no Npcap, disabled sound device, unplugged headset, no glow calibration, two displays and Windows DPI scaling.

### Safe diagnostics when a live test fails

Use **Diagnostics -> Copy safe summary**. It records counters and text status (port/phase stats, player-position availability, detected cube count); it is **not** a raw PCAP. The app also supports walking, near-cube and opening phases for comparison. Avoid sharing character names, public IP addresses, server endpoints or raw payloads unintentionally when posting logs.

**Caution:** The current diagnostics generator still uses a `v16` heading internally in `modern_engine.py`, even though this is **v17**. That is a labeling bug, not proof that the wrong binary is running. Fix before polished release.

## 9. Build and distribute the Windows EXE

**The repository already contains `BUILD_EXE.bat`.** It uses PyInstaller in **`--onedir` mode** (a folder with one launcher EXE and supporting libraries); it does **not** build a single-file EXE. Packaging has not yet been executed/verified on a Windows target in this handoff.

### Step-by-step production build

1. On **Windows x64**, close the app and game; use the latest vetted source, Python **3.12**, and a fully installed `.venv`.
2. Run offline tests; fix any failures.
3. Double-click `BUILD_EXE.bat`, or from Command Prompt:

```bat
cd /d C:\Aion2CubeFinder
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name "Aion2CubeFinder-v17" ^
  --collect-all PySide6 --collect-all soundcard --collect-all mss --collect-all cv2 ^
  --hidden-import scapy.arch.windows --add-data "assets;assets" ^
  --icon "assets\cube_finder.ico" cube_finder_modern.py
```

The above is the **current build script command**. If you place the code somewhere else, change only the `cd` path; run all following commands from the project root.

4. On success, the expected output is:

```text
dist\Aion2CubeFinder-v17\Aion2CubeFinder-v17.exe
```

5. Run the EXE **from its output folder**. Check that icons, alert WAV and 25 rotation images are accessible. Check network, sound and glow using the manual acceptance list.
6. To distribute, **ZIP the entire** `dist\Aion2CubeFinder-v17\` **folder**, not just `Aion2CubeFinder-v17.exe`.
7. Test the ZIP after extracting it into a new folder, ideally on a clean Windows machine. Npcap is a separate system driver and **is not bundled by PyInstaller**.
8. Only after tests and license review, upload the distribution ZIP as a GitHub Release asset. Record the tested Windows and Python versions in the release notes.

### EXE-specific caveats

- The `.exe` is generated from a Python virtual environment; end users normally should **not** need to install Python separately for the packaged onedir app.
- Npcap **must be installed on the target Windows machine** for live sniffing. Administrator capture permissions may still be required.
- `--windowed` suppresses a useful Python console. **Keep `START.bat` for diagnosis.** For package failures, create a temporary diagnostic build with `--console` instead of `--windowed` and inspect errors; do not upload sensitive traces.
- PyInstaller and optional native dependencies are not pinned, so binary reproducibility is **not guaranteed** until a lockfile/versioned build environment is added.
- Code-signing has **not** been set up. Windows SmartScreen warnings are possible for unsigned new executables; do not advise users to bypass trust checks blindly.
- The app uses `resource_path()` to load bundled assets from `sys._MEIPASS` when packaged; changing the asset layout requires updating this logic and/or `--add-data`.
- If the Windows release fails, capture the full PyInstaller traceback and test import/runtime errors before modifying the game's packet parser.

## 10. GitHub upload and release checklist

### Before publishing source

- [ ] **Resolve licensing** of `working_aion_radar.py` and other user-provided/upstream code. Having the bytes does not by itself authorize public redistribution.
- [ ] Review the redistribution rights for `assets/reference_cubes/`, `assets/rotation_patterns/`, and other copyrighted artwork. Remove/replace if necessary.
- [ ] Remove credentials, account identifiers, raw PCAPs, crash dumps, private IP/connection data and game chat from tracked files.
- [ ] Include `.gitignore` so `.venv/`, cache, `build/`, `dist/`, `.spec`, unneeded dumps and captures are **not** committed.
- [ ] Keep `README.md`, **this** `DEVELOPER_HANDOFF.md`, `requirements.txt`, scripts, tests, and original attribution (`UPSTREAM_SOURCES.md`).
- [ ] Do not publish a LICENSE file claiming ownership of unlicensed third-party code. Once rights are clear, use a valid license and preserve upstream notices.

### If creating a new GitHub repository

Create an empty private repository first. From **Command Prompt** in the project directory:

```bat
git init
git branch -M main
git add .
git status
git commit -m "Initial v17 dual-radar source and developer handoff"
git remote add origin https://github.com/YOUR_USER/YOUR_REPOSITORY.git
git push -u origin main
```

Replace the placeholders. Do not run `git remote add origin` again if the folder already has a configured remote. If adding to an existing repo, copy/commit these files on a feature branch and open a pull request instead. **Keep it private until rights and security checks are complete.**

### GitHub release after Windows QA

1. Commit source changes and confirm clean tests.
2. Build the EXE on Windows with `BUILD_EXE.bat`.
3. Run the test checklist using the packaged output, not just Python source.
4. ZIP `dist\Aion2CubeFinder-v17\` and include a tested `README`/release notes; do not upload the project `.venv`.
5. Tag the verified commit (example `v17.0.0`) and attach the ZIP to a Release.
6. State verified limits openly: server patch/date, Windows version, Npcap, sound behavior, and outstanding defects.

## 11. Licensing, privacy and game rules

**Third-party source:** `UPSTREAM_SOURCES.md` says `working_aion_radar.py` was directly supplied by the user and that its license has **not been established**. A private working copy and permission to redistribute publicly are different matters. Review the original repository history/license and obtain permission as appropriate. If code from GPL projects is copied, fulfill the corresponding license obligations. Do not silently publish copied game assets or user-provided gameplay recordings without rights review.

**Privacy:** The intended design operates locally. The code's diagnostics contain aggregated counters and the two settings files contain UI/visual preferences. The app does not intentionally upload game traffic. **Raw PCAP captures**, if created by outside capture tools or for replay, may contain character names, chat, addresses and other sensitive traffic; keep them out of Git and public tickets. Inspect third-party packages/source before distribution.

**Game rules:** Passive capture and a no-injection design do **not** establish that NCSOFT permits the tool, or that it cannot be detected. Account or anti-cheat policy risk remains with the operator. Never claim “ban-proof” or “guaranteed anti-cheat safe.”

## 12. Known limitations and troubleshooting

| Symptom | Likely explanation | Next diagnostic/action |
|---|---|---|
| `INSTALL.bat` fails building `lz4` | Wrong/default Python version or missing compatible wheel (previously seen with Python 3.15) | `py -3.12 --version`; delete/recreate **only this project's** `.venv`; rerun install |
| App opens but network cubes stay at zero | Parser mismatch, wrong port, missing player/cube events, or incomplete frames | Confirm actual Npcap traffic/port; default `Working radar`; compare standalone baseline; use safe diagnostics |
| Npcap access denied | Capture driver permissions | Use `START_AS_ADMIN.bat`, check Npcap installation; don't alter network protocol first |
| Port 13320 has zero traffic | Global session may use 13328 only | This is not inherently an error; examine 13328 counters |
| Cubes have coordinates but no distance | Player XYZ unknown or stale | Test movement/buff/position events; don't invent a position; inspect stale warning |
| World radar marker doesn't match camera direction | Fixed world axes, not camera-relative | Document fixed axes or implement a separate validated heading mode |
| Distance sometimes drifts or stops | Player movement events stale; extrapolation in original code problematic | v17 adapter disables source dead reckoning; use last decoded coordinates and stale warning |
| Sound value stays 0% | No stereo loopback, wrong default speaker, game muted, or detector disabled | Confirm playback device, volume and checkbox; restart after output device changes |
| Sound dot doesn't point at a cube | Stereo left/right is not 360° and can reflect/mix | Use it as a **search cue**, not true bearing; corroborate via glow/network |
| Sound percentage doesn't reach 100 near cube | Relative normalization, not a physical distance scale | Adjust sensitivity; don't hardcode percent-to-meter mapping |
| F8 works outside game but not with game focused | Windows/game keyboard privileges (observed previously) | Borderless mode, try elevated launch where justified, or GUI calibration |
| Gold glow marker missing or stuck | Low confidence, outdated RGB target, rotation, similar-colored UI or multi-monitor mismatch | Recalibrate F8, adjust F9/F10, inspect tracker and primary-monitor assumption |
| Network HUD hides Sound HUD | This was v15 limitation; v17 should use independent HUDs | Confirm v17 launch and two visibility toggles; report regression |
| HUD hidden behind game | Exclusive fullscreen/topmost interaction | Try Borderless Windowed; check show/hide and offscreen saved coordinates |
| Click-through HUD won't drag | Expected click-through behavior | Disable click-through in **Settings** then drag |
| Settings don't persist | App terminated abruptly, folder permission, corrupt JSON | Close app normally, inspect `%LOCALAPPDATA%\Aion2CubeFinder\...` and logs |
| GitHub fetch SSL error | Certificate validation / environment issue in optional fetch script | Fetch is **optional**; do not disable TLS verification |
| EXE launches blank/crashes | Missing Qt/plugin/native library or asset included incorrectly | Test source app, build console diagnostic variant, check PyInstaller collected dependencies |
| Diagnostics say `v16` | Stale string in `modern_engine.py` | Cosmetic issue to fix before v17 public release |

**Possible additional technical debt to investigate rather than claim fixed:** user-supplied `PureStreamEngine` lacks robust cross-TCP-segment buffering; single-monitor screen capture; unverified Windows multi-DPI screen/window coordinate reconciliation; imported source copyright/license; variable dependency versions; legacy code maintained for reference.

## 13. Version history and next steps

| Version | Development milestone |
|---|---|
| Original `cube_finder.py` | 1680 Hz speaker loopback, relative percentage, L/R stereo, F8 color sampling |
| v3 | Persistent F8 color and tolerance |
| v4–v6 | Self-HUD color exclusion, cluster/rotation recognition, 25 reference patterns from two videos |
| v7–v10 | Network diagnostic counters, dual-port discovery, framing hypotheses |
| v11–v12 | Improved protocol research/decoder, then experimental hybrid capture |
| v13 | Integrated the **user-confirmed working** standalone radar backend |
| v14 | Aligned world-coordinate markers; disabled speculative movement toward nearest cube |
| v15 | Replaced legacy Tkinter main UI with modern PySide6 dashboard and translucent HUD |
| v16 | Split into independent network and audio overlays, with separate settings and alerts |
| **v17** | Added circular **sound-direction** HUD with cyan L/R and optional gold visual marker, pulse, percentage and trend; **95 offline tests pass** |

### Recommended priority order for next developer

1. **Verify v17 live on Windows**, with screenshots and the manual checklist; fix any startup/runtime regressions first.
2. **Build/QA the onedir EXE** on Windows 10/11; verify bundled icons, WAV, image patterns and independent overlays.
3. Confirm the v17 default **working network adapter** matches the user's previously successful standalone radar (cube marker, actual meter updates, removals).
4. Validate HUD accuracy using real player XYZ and avoid presenting stale/guessed positions as precise.
5. Improve audio UX without implying distance is known: better sensitivity, device picker, signal calibration and unobtrusive alerts.
6. Improve glow tracker false positives and secondary-monitor support; consider explicit manual ROI and better confidence visualizations.
7. Harden event/capture thread shutdown and compatibility after disconnects, patches or output-device changes.
8. Remove stale v16 diagnostics label; add error logging suitable for `--windowed` builds.
9. Resolve licenses, pin dependencies, implement GitHub CI for offline tests, then consider a public release.

## 14. Handoff to the next developer or assistant

> Continue **Aion 2 Cube Finder v17 (Dual Radars)** from this repository. It is a Python 3.12 Windows project with PySide6, a working-reference network parser in `working_aion_radar.py` accessed through `working_network_capture.py`, and independent NumPy/SoundCard audio plus MSS/OpenCV glow detectors in `modern_engine.py`. Two overlays live in `dual_overlays.py`. The user confirmed live cube markers and changing meters in the **standalone source** that v13 integrated, but the **v17 integrated GUI and EXE are not yet confirmed live**. All **95 offline tests pass**. Preserve the working parser unless live evidence calls for a change; do not revert to speculative older opcode decoders as the default. The main next job is Windows QA and EXE packaging with `BUILD_EXE.bat`, plus confirming the dual HUDs independently. Consult this file for setup, known issues, privacy/licensing caution and release checklist. Do not claim current game anti-cheat safety or public redistribution rights.

**Key commands:** `INSTALL.bat` -> `RUN_TESTS.bat` -> `START.bat` -> `BUILD_EXE.bat`.  
**Primary entry:** `cube_finder_modern.py`.  
**Default backend:** `Working radar`.  
**Saved config:** `%LOCALAPPDATA%\Aion2CubeFinder\ui_settings.json` and `settings.json`.  
**Build output:** `dist\Aion2CubeFinder-v17\Aion2CubeFinder-v17.exe` (one-folder distribution).
