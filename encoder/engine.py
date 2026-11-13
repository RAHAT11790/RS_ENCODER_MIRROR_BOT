"""FFmpeg encoding engine: probe, command construction and execution."""

import asyncio
import json
import os
import re

import rsbin
from lite.fmt import clock, readable_size
from .presets import height_for

from . import LOGGER

_SAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)


def output_name(src):
    base = os.path.splitext(os.path.basename(src))[0]
    return (_SAFE.sub("_", base).strip() or "video")[:120]


async def probe(path):
    """(duration, width, height, has_audio, has_subs) - zeros/False when probing fails."""
    ffprobe = rsbin.resolve("ffprobe")
    if not ffprobe:
        return 0.0, 0, 0, False, False
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        data = json.loads(out.decode(errors="ignore") or "{}")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"ffprobe failed for {os.path.basename(path)}: {e}")
        return 0.0, 0, 0, False, False
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    width = height = 0
    has_audio = has_subs = False
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not width:
            width = int(stream.get("width", 0) or 0)
            height = int(stream.get("height", 0) or 0)
        elif kind == "audio":
            has_audio = True
        elif kind == "subtitle":
            has_subs = True
    return duration, width, height, has_audio, has_subs


def build_command(src, dest, settings, height=None, duration=0, has_audio=True, has_subs=False, assets_dir=None):
    """Build the full ffmpeg argument list for one encode."""
    ffmpeg = rsbin.resolve("ffmpeg") or "ffmpeg"
    codec = "libx265" if settings.get("codec") == "h265" else "libx264"
    preset = settings.get("preset") or "veryfast"
    crf = int(settings.get("crf") or 26)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats", "-i", src]

    filters = []
    if height:
        filters.append(f"scale=-2:{int(height)}:flags=lanczos")
    if settings.get("watermark") and assets_dir:
        ass = os.path.join(assets_dir, "watermark.ass")
        if os.path.isfile(ass):
            filters.append("subtitles=" + _ff_path(ass))
    if filters:
        cmd += ["-vf", ",".join(filters)]

    threads = str(settings.get("threads", 0))
    cmd += ["-c:v", codec, "-preset", preset, "-crf", str(crf), "-threads", threads]
    tune = settings.get("tune")
    if tune:
        # libx265 only understands animation/grain/fastdecode/zerolatency/psnr/ssim
        allowed = ("animation", "grain", "fastdecode", "zerolatency")
        if settings.get("codec") == "h265":
            if tune in allowed:
                cmd += ["-tune", tune]
        else:
            cmd += ["-tune", tune]
    if settings.get("ten_bit"):
        cmd += ["-pix_fmt", "yuv420p10le"]
    else:
        cmd += ["-pix_fmt", "yuv420p"]
    cmd += ["-profile:v", "main" if settings.get("codec") == "h265" else "high"]
    if settings.get("codec") != "h265":
        cmd += ["-coder", "1" if settings.get("cabac") else "0"]
        refs = str(settings.get("reframe") or "")
        if refs in ("4", "8", "16"):
            cmd += ["-refs", refs]
    cmd += ["-max_muxing_queue_size", "4096", "-map", "0:v:0"]

    audio_codec = settings.get("audio_codec") or "aac"
    if has_audio:
        if audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "libopus" if audio_codec == "opus" else audio_codec]
            bitrate = str(settings.get("audio_bitrate") or "128")
            if bitrate.isdigit():
                cmd += ["-b:a", bitrate + "k"]
            if settings.get("sample_rate"):
                cmd += ["-ar", str(settings["sample_rate"])]
        channels = str(settings.get("channels") or "")
        if channels and audio_codec != "copy":
            mapping = {"1.0": "1", "2.0": "2", "2.1": "3", "5.1": "6", "7.1": "8"}
            if channels in mapping:
                cmd += ["-ac", mapping[channels]]
        cmd += ["-map", "0:a:0"]

    subtitles = settings.get("subtitles", "copy")
    if has_subs and subtitles == "copy":
        if dest.lower().endswith(".mp4"):
            cmd += ["-c:s", "mov_text", "-map", "0:s?"]
        elif dest.lower().endswith(".mkv"):
            cmd += ["-c:s", "copy", "-map", "0:s?"]

    if settings.get("metadata_tag"):
        tag = str(settings["metadata_tag"])
        cmd += ["-metadata", f"title={tag}"]

    if dest.lower().endswith(".mp4") and settings.get("faststart", True):
        cmd += ["-movflags", "+faststart"]
    cmd += [dest]
    return cmd


def _ff_path(path):
    """Escape a path for an ffmpeg subtitle filter argument."""
    path = path.replace("\\", "/")
    return path.replace(":", "\\:").replace("'", "\\'")


async def encode(src, dest, settings, task=None):
    """Encode *src* to *dest*. Returns dest on success, raises RuntimeError on failure."""
    duration, _, source_h, has_audio, has_subs = await probe(src)
    height = height_for(settings.get("resolution"))
    if height and source_h and height > source_h:
        height = source_h  # never upscale
    assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "encoder", "assets")
    cmd = build_command(
        src, dest, settings, height=height, duration=duration,
        has_audio=has_audio, has_subs=has_subs, assets_dir=assets,
    )
    from .progress import run_ffmpeg

    source_size = os.path.getsize(src) if os.path.isfile(src) else 0
    if task is not None:
        task.set_status("Convert")
        task.set_phase(
            "encoding " + (str(settings.get("resolution") or "OG")),
            percent=0.0,
            length=f"00:00 / {clock(duration)}" if duration > 0 else "",
            size=f"— / {readable_size(source_size)}" if source_size > 0 else "",
        )
    LOGGER.info("ffmpeg encode: " + os.path.basename(src) + " -> " + os.path.basename(dest))
    code, err = await run_ffmpeg(
        cmd, duration, task,
        label="encoding " + str(settings.get("resolution") or "OG"),
        source_size=source_size,
    )
    if task is not None:
        task.set_phase("encoding", percent=100.0)
    if task is not None and getattr(task, "cancelled", False):
        raise asyncio.CancelledError()
    if code != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 1024:
        tail = (err or "").strip().splitlines()[-3:]
        raise RuntimeError("ffmpeg failed: " + (" | ".join(tail) or f"exit {code}"))
    return dest
