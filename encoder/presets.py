"""Quality presets and default encoder settings."""

QUALITY_MAP = {
    "360p": 360,
    "480p": 480,
    "560p": 576,
    "576p": 576,
    "720p": 720,
    "1080p": 1080,
    "1440p": 1440,
    "2k": 1440,
    "2160p": 2160,
    "4k": 2160,
}

DEFAULT_SETTINGS = {
    "codec": "h264",          # h264 | h265
    "preset": "veryfast",     # ultrafast ... slow
    "crf": 26,
    "resolution": "OG",       # OG keeps the source height
    "audio_codec": "aac",     # aac | copy | ac3 | opus
    "audio_bitrate": "128",   # kbps
    "sample_rate": "",        # "" keeps source
    "channels": "",           # "" | 1.0 | 2.0 | 5.1
    "tune": "",               # "" | film | animation
    "threads": 0,             # 0 = auto-detect all available CPU cores for max speed
    "cabac": True,
    "reframe": "",            # "" keeps preset default
    "ten_bit": False,
    "subtitles": "copy",      # copy | none
    "metadata_tag": "",
    "watermark": False,
    "faststart": True,
    "container": "mp4",       # mp4 | mkv | avi
}

PRESETS = ("ultrafast", "superfast", "veryfast", "fast", "medium", "slow")
AUDIO_CODECS = ("aac", "copy", "ac3", "opus")
CONTAINERS = ("mp4", "mkv", "avi")

RESOLUTIONS = ("OG", "360p", "480p", "560p", "720p", "1080p", "1440p", "4k")


def height_for(name):
    """Map a resolution name (``720p``, ``4k``, ``720``) to an integer height or ``None`` (OG)."""
    if name is None:
        return None
    text = str(name).strip().lower()
    if text in ("", "og", "source", "original"):
        return None
    if text in QUALITY_MAP:
        return QUALITY_MAP[text]
    if text.endswith("p"):
        text = text[:-1]
    try:
        value = int(text)
    except ValueError:
        return None
    return value if 120 <= value <= 4320 else None
