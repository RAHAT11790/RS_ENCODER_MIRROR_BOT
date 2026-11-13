"""Centralized rootless binary manager.

Every tool the bot runs (ffmpeg, ffprobe, yt-dlp, 7-Zip) is resolved from the
project-local ``bin/`` directory first and only then from PATH.  Nothing here
needs root: ``install.sh`` downloads portable builds into ``./bin``.
"""

import os
import stat
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(ROOT, "bin")

TOOLS = {
    "ffmpeg": ("ffmpeg", "ffmpeg.exe"),
    "ffprobe": ("ffprobe", "ffprobe.exe"),
    "yt-dlp": ("yt-dlp", "yt-dlp.exe"),
    "7z": ("7z", "7zz", "7za", "7z.exe"),
}


def ensure_bin_on_path():
    """Make <project>/bin the first PATH entry (inherited by every child process)."""
    os.makedirs(BIN_DIR, exist_ok=True)
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if not parts or os.path.normcase(parts[0]) != os.path.normcase(BIN_DIR):
        os.environ["PATH"] = os.pathsep.join([BIN_DIR] + [p for p in parts if os.path.normcase(p) != os.path.normcase(BIN_DIR)])
    return BIN_DIR


def _candidates(name):
    specs = TOOLS.get(name, (name, name + ".exe"))
    if isinstance(specs, str):
        specs = (specs,)
    for filename in specs:
        path = os.path.join(BIN_DIR, filename)
        if os.path.isfile(path):
            yield path


def resolve(name):
    """Absolute path of *name* (bin/ first, then PATH) or None."""
    ensure_bin_on_path()
    for path in _candidates(name):
        if _make_executable(path):
            return path
    import shutil

    found = shutil.which(name)
    if found:
        return found
    return None


def _make_executable(path):
    if os.name == "nt":
        return True
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return os.access(path, os.X_OK)
    except OSError:
        return False


def check(name):
    """(ok, path_or_message) for one tool."""
    path = resolve(name)
    if not path:
        return False, f"{name} not found in {BIN_DIR} or PATH (run ./install.sh - no root needed)"
    if not _make_executable(path):
        return False, f"{path} is not executable and permissions could not be fixed"
    return True, path


def report():
    """Human-readable startup status for every bundled tool."""
    lines = []
    for name in ("ffmpeg", "ffprobe", "yt-dlp", "7z"):
        ok, info = check(name)
        lines.append(("OK   " if ok else "MISS ") + name + " -> " + info)
    return lines


def missing():
    return [name for name in ("ffmpeg", "ffprobe", "yt-dlp", "7z") if not check(name)[0]]
