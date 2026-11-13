"""Video encoder engine integrated with the mirror-leech pipeline.

Pure-ffmpeg, rootless: every binary comes from ``rsbin`` (project ``bin/`` first).
"""

VERSION = "3.1"

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXT = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac", ".wma"}


def is_video(path):
    import os

    return os.path.splitext(str(path))[1].lower() in VIDEO_EXT


def is_audio(path):
    import os

    return os.path.splitext(str(path))[1].lower() in AUDIO_EXT

import logging

LOGGER = logging.getLogger("rsleech.encoder")
