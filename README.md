# Aion 2 Cube Finder v17 — Network Radar + Independent Sound Radar

v17 restores the **sound-guidance radar** requested after v16 introduced separate HUDs. The working network parser, audio listener, screen glow detector, glow calibration storage, and controls have not been changed. Only the audio HUD display and explanatory labels are updated.

> **Developer / GitHub release handoff:** Read [DEVELOPER_HANDOFF.md](DEVELOPER_HANDOFF.md) for requirements, full Windows installation, runtime modes, tests, known limitations, licensing review, GitHub upload, and step-by-step EXE packaging.

## Two independent floating radars

**Network radar (red / mint):** Displays actual decoded Hidden Cube coordinates, world bearings, distances in meters, and elevation. Enable **Npcap capture** to use it. May show stale-player-position warning if fresh coordinates are unavailable.

**Sound direction radar (cyan / gold):** Stays visible and updates whether Npcap is on or off.
- **Moving CYAN dot** — stereo left/right balance of the isolated 1,620–1,740 Hz game audio cue. The dot **only moves along the horizontal line**. Center or left/right is not a 360° bearing; the source could be ahead/behind, reflected, or affected by game stereo processing.
- **Moving GOLD dot** — optional screen-glow detection. When a cube is visible and correctly recognized, it shows screen left/right **and** up/down. This is *pixel aiming*, not audio triangulation.
- **0–100% strength bar** — relative signal strength, **not meters**. A strong reading does not reliably mean a fixed distance, particularly through walls or with other sounds.
- **WARMER / COLDER / STEADY** — whether detected hum strength has increased or decreased recently, useful when moving.
- **Animated pulse** — flashes around the audio marker while a matching hum is detected.

The cyan sound indicator never becomes a world-coordinate cube marker and is not overridden by the network detector. The gold screen-glow dot disappears when the vision tracker no longer sees a reliable match.

### Practical way to find a cube using the sound radar

1. With game audio playing to your **default Windows stereo output**, enable **1680 Hz Sound Detection**.
2. If the cyan dot leans LEFT or RIGHT, slowly rotate the **game camera** and compare how the stereo indication changes. Sound reflections and game spatial mixing can be misleading; do not treat it as a compass.
3. Move toward the suspected area. Watch the signal percentage and **WARMER/COLDER** feedback.
4. Once the cube is on screen, optionally turn on **Glow**. The **gold marker** gives 2D screen aiming (up/down too), assuming a valid match.
5. If the working network radar is enabled and has player/cube coordinates, follow **its** real distance in meters.

## Install on Windows 10/11

1. Close previous versions, unzip v17 to a **new folder**.
2. Run `INSTALL.bat` (Python 3.12 + dependencies) or, if your current `.venv` has these requirements, re-use it after checking your environment.
3. Optionally run `RUN_TESTS.bat` (offline tests only).
4. Run `START.bat`. The two floating windows should appear.
5. In the dashboard's **Detection** page, enable the **1680 Hz sound detector** and optionally **Npcap** and **Glow**.
6. In **Settings**, adjust each HUD's opacity, size, click-through, position and visibility independently. Settings persist at `%LOCALAPPDATA%\Aion2CubeFinder\ui_settings.json`. Saved F8 glow RGB also persists.

## Preserved safety and privacy behaviors

- `working_aion_radar.py` network parsing is not modified in v17.
- Sound data is analyzed on-device from Windows loopback; no microphone recording files are saved.
- No second network capture thread is added.
- The sound and network alerts remain independently enabled/disabled.
- Packet capture may violate Aion 2 game terms, regardless of passivity.

## Testing

The test suite verifies no network dependency for sound direction, clamps/axis restrictions for markers, optional glow X/Y projection, independent HUD state, packet decoders, and existing vision/audio calculations. Offline testing cannot verify your physical Windows display or how your game mixes stereo positional sound.
