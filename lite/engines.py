"""Engine labels shown in the status message (name + real library version)."""

from importlib import metadata

_cache = {}


def _ver(dist):
    if dist not in _cache:
        try:
            _cache[dist] = metadata.version(dist)
        except Exception:  # noqa: BLE001
            _cache[dist] = "N/A"
    return _cache[dist]


def direct():
    return f"AioHTTP v{_ver('aiohttp')}"


def ytdlp():
    return f"yt-dlp v{_ver('yt-dlp')}"


def telegram():
    return f"WzPyro v{_ver('wzgram')}"


def sevenzip():
    return "7-Zip"


def ffmpeg():
    return "FFmpeg"
