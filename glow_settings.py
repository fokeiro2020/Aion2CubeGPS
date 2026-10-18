r"""Persist the glow-color calibration outside the source/exe folder.

On Windows the preset lives at:
    %LOCALAPPDATA%\Aion2CubeFinder\settings.json

Only color and matching tolerance are saved (no recordings, game data or packets).
"""

import json
import os
from pathlib import Path
import tempfile

DEFAULT_TOL = 40


def settings_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Aion2CubeFinder" / "settings.json"
    return Path.home() / ".config" / "Aion2CubeFinder" / "settings.json"


def _valid_rgb(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    if not all(type(x) is int and 0 <= x <= 255 for x in value):
        return None
    return tuple(value)


def read_glow_settings(path=None):
    """Return (RGB tuple or None, tolerance). Missing/malformed files use defaults."""
    path = Path(path) if path is not None else settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None, DEFAULT_TOL
    if not isinstance(data, dict):
        return None, DEFAULT_TOL
    rgb = _valid_rgb(data.get("glow_rgb"))
    tol = data.get("glow_tolerance", DEFAULT_TOL)
    if type(tol) is not int or not 5 <= tol <= 120:
        tol = DEFAULT_TOL
    return rgb, tol


def write_glow_settings(rgb, tolerance, path=None):
    """Safely write settings, returning the final filename.

    Atomic replace protects an existing preset from partial/failed writes.
    Errors propagate to the caller so the UI cannot falsely display SAVED.
    """
    rgb = _valid_rgb(rgb) if rgb is not None else None
    if type(tolerance) is not int or not 5 <= tolerance <= 120:
        raise ValueError("Tolerance must be an integer between 5 and 120")
    path = Path(path) if path is not None else settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix="settings_", suffix=".tmp", delete=False,
        ) as temp:
            tmp_path = Path(temp.name)
            json.dump({"version": 1, "glow_rgb": list(rgb) if rgb else None,
                       "glow_tolerance": tolerance}, temp, indent=2)
            temp.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
    return path
