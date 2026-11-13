"""Pre-flight for RS Leech Lite: make sure everything the bot needs is installed.

Run automatically by ``python3 main.py``:
   1. every package in requirements.txt is checked (name + version) and installed if
      missing/outdated (no root needed; works inside or outside a virtualenv);
   2. yt-dlp is refreshed at most once per 24h (YouTube breaks old versions fast).

Command-line tools (ffmpeg, ffprobe, 7-Zip, yt-dlp) are handled rootlessly by
``install.sh`` into ``./bin`` via ``bin_bootstrap.py`` - no OS package manager, no sudo.

Environment switches:  RS_SKIP_SETUP=1  skip everything,  RS_ALLOW_MISSING=1  start even if
some package could not be installed,  AUTO_INSTALL_SYSTEM=0  skip the binary downloads.
"""

from __future__ import annotations

import importlib
import os
import re
import site
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQ_FILE = ROOT / "requirements.txt"
YTDLP_MARK = ROOT / ".ytdlp_checked"
YTDLP_SPEC = "yt-dlp[default]"

# Used only if requirements.txt is missing, so `python3 main.py` works on its own.
DEFAULT_REQUIREMENTS = ['wzgram>=3.1.6,<4', 'aiohttp>=3.9.5', 'aiofiles>=23.2.1', 'yt-dlp[default]>=2024.6.9', 'pillow>=10.3.0', 'psutil>=5.9.8', 'py7zr>=0.22']


def _log(msg: str) -> None:
    print(f"[setup] {msg}", flush=True)


def _requirement_cls():
    try:
        from packaging.requirements import Requirement

        return Requirement
    except Exception:  # noqa: BLE001
        try:
            from pip._vendor.packaging.requirements import Requirement  # type: ignore

            return Requirement
        except Exception:  # noqa: BLE001
            return None


def read_requirements() -> list[str]:
    if not REQ_FILE.is_file():
        return list(DEFAULT_REQUIREMENTS)
    lines = []
    for raw in REQ_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        lines.append(line)
    return lines


def find_missing(requirements: list[str]) -> list[str]:
    Requirement = _requirement_cls()
    missing = []
    for line in requirements:
        if Requirement is None:  # very old environment: check the name only
            name = re.split(r"[<>=!~;\[ ]", line, 1)[0]
            try:
                metadata.version(name)
            except metadata.PackageNotFoundError:
                missing.append(line)
            continue
        try:
            req = Requirement(line)
        except Exception:  # noqa: BLE001
            continue
        if req.marker is not None and not req.marker.evaluate():
            continue
        try:
            installed = metadata.version(req.name)
        except metadata.PackageNotFoundError:
            missing.append(line)
            continue
        if req.specifier and not req.specifier.contains(installed, prereleases=True):
            missing.append(line)
    return missing


def _in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix) or bool(
        os.environ.get("VIRTUAL_ENV")
    )


def _pip(args: list[str]) -> tuple[int, str]:
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    cmd = base + args
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = proc.stdout or ""
    if proc.returncode != 0 and "No module named pip" in out:
        _log("pip is missing, bootstrapping it with ensurepip ...")
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"])
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out = proc.stdout or ""
    if proc.returncode != 0 and "externally-managed-environment" in out and not _in_venv():
        proc = subprocess.run(
            cmd + ["--break-system-packages"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        out = proc.stdout or ""
    if proc.returncode != 0 and not _in_venv():
        # no root: install into the user site-packages instead of system Python
        _log("system install failed, retrying with --user (rootless) ...")
        proc = subprocess.run(
            cmd + ["--user"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        out = proc.stdout or ""
    # show a short tail so the user can see what happened
    tail = "\n".join(out.strip().splitlines()[-6:])
    if tail:
        print(tail, flush=True)
    return proc.returncode, out


def _refresh_paths() -> None:
    importlib.invalidate_caches()
    try:
        user_site = site.getusersitepackages()
        if os.path.isdir(user_site):
            site.addsitedir(user_site)
    except Exception:  # noqa: BLE001
        pass


def ensure_python_packages() -> None:
    reqs = read_requirements()
    if not reqs:
        return
    missing = find_missing(reqs)
    if not missing:
        _log(f"all {len(reqs)} Python packages are installed")
        return

    _log(f"{len(missing)} package(s) missing/outdated -> installing: " + ", ".join(missing))
    code, _ = _pip(missing)
    _refresh_paths()
    still = find_missing(reqs)
    if still:
        _log("bulk install incomplete, retrying one by one ...")
        for line in still:
            _pip([line])
        _refresh_paths()
        still = find_missing(reqs)

    if still:
        _log("COULD NOT INSTALL: " + ", ".join(still))
        if os.getenv("RS_ALLOW_MISSING", "").strip().lower() in ("1", "true", "yes"):
            _log("RS_ALLOW_MISSING is set -> starting anyway")
            return
        _log("Fix the error above (internet/disk/build tools) and run again. "
             "Set RS_ALLOW_MISSING=1 to start anyway.")
        raise SystemExit(1)
    _log("all Python packages installed")


def refresh_ytdlp() -> None:
    """Upgrade yt-dlp at most once per 24h (best effort, never blocks startup)."""
    try:
        if YTDLP_MARK.exists() and time.time() - YTDLP_MARK.stat().st_mtime < 86400:
            return
        _log("checking for a newer yt-dlp ...")
        _pip(["--upgrade", "--quiet", YTDLP_SPEC])
        _refresh_paths()
        YTDLP_MARK.touch()
    except Exception as e:  # noqa: BLE001
        _log(f"yt-dlp refresh skipped: {e}")


def ensure_everything() -> None:
    if os.getenv("RS_SKIP_SETUP", "").strip().lower() in ("1", "true", "yes"):
        _log("RS_SKIP_SETUP set -> skipping pre-flight checks")
        return
    if sys.version_info < (3, 10):
        _log(f"Python {sys.version.split()[0]} is too old, 3.10+ is required")
        raise SystemExit(1)
    ensure_python_packages()
    try:
        from bin_bootstrap import sync_7z_aliases, have, download_portable_7z
        sync_7z_aliases()
        if not have("7z"):
            download_portable_7z()
    except Exception as e:
        _log(f"7z auto-bootstrap skipped: {e}")
    refresh_ytdlp()


if __name__ == "__main__":
    ensure_everything()
