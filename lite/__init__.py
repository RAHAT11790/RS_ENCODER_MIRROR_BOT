"""RS Leech Lite - Telegram leech bot: direct links, yt-dlp (incl. HLS/m3u8) and TMDb auto-thumbnails."""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

VERSION = "3.1"
START_TIME = time.time()

try:  # emoji in log lines must not crash a Windows console using a legacy code page
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

LOGGER = logging.getLogger("rsleech")
if not LOGGER.handlers:
    LOGGER.setLevel(logging.INFO)
    _fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", "%d-%b-%y %I:%M:%S %p")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    LOGGER.addHandler(_sh)
    try:
        _fh = RotatingFileHandler("log.txt", maxBytes=2_000_000, backupCount=1, encoding="utf-8")
        _fh.setFormatter(_fmt)
        LOGGER.addHandler(_fh)
    except OSError:
        pass
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def _clean_ld_preload():
    """A missing LD_PRELOAD library makes every child process (ffmpeg, 7z) print loader errors."""
    pre = os.environ.get("LD_PRELOAD", "")
    keep = [p for p in pre.replace(":", " ").split() if os.path.exists(p)]
    if keep:
        os.environ["LD_PRELOAD"] = " ".join(keep)
    else:
        os.environ.pop("LD_PRELOAD", None)


def _attach_bin():
    """Project-local ./bin must win over system tools for the bot and its children."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_dir = os.path.join(root, "bin")
    if not os.path.isdir(bin_dir):
        return
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if not parts or parts[0] != bin_dir:
        os.environ["PATH"] = os.pathsep.join([bin_dir] + [p for p in parts if p != bin_dir])


_clean_ld_preload()
_attach_bin()
