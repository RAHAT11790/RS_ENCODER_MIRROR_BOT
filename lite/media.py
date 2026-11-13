"""ffprobe / ffmpeg helpers.

Every ffmpeg process is time limited, killed on timeout and counted against
MAX_PARALLEL_FFMPEG so the server is never flooded with processes.
"""

import json
import os
import shutil
from asyncio import Semaphore, create_subprocess_exec, gather, wait_for
from asyncio.subprocess import PIPE
from contextlib import suppress
from time import time

from . import LOGGER
from .config import Config

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mpg", ".mpeg", ".3gp"}
AUDIO_EXT = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".aac", ".wma"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

_sem = None


def _slot():
    global _sem
    if _sem is None:
        _sem = Semaphore(max(1, Config.MAX_PARALLEL_FFMPEG))
    return _sem


def kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    return "document"


def tool(name):
    return shutil.which(name)


async def run(cmd, timeout=40):
    """Run a command; kill it when the timeout expires. Returns (stdout, stderr, returncode)."""
    async with _slot():
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        try:
            out, err = await wait_for(proc.communicate(), timeout=timeout)
        except BaseException:
            with suppress(Exception):
                proc.kill()
                await proc.wait()
            raise
        return out.decode(errors="ignore"), err.decode(errors="ignore"), proc.returncode


def _parse_time(val):
    try:
        parts = val.strip().split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    except (TypeError, ValueError):
        pass
    return None


async def _run_percent(cmd, timeout, on_progress):
    """Run ffmpeg with -progress pipe:1 and report encoded progress data."""
    async with _slot():
        proc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

        cur = {"seconds": 0.0, "speed_str": "", "speed_val": 0.0, "fps": "", "size": 0}

        async def pump():
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode(errors="ignore").strip()
                if not line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key == "out_time":
                    parsed = _parse_time(value)
                    if parsed is not None and parsed >= 0:
                        cur["seconds"] = parsed
                elif key == "out_time_us":
                    if cur["seconds"] == 0:
                        try:
                            cur["seconds"] = max(int(value) / 1_000_000, 0.0)
                        except (TypeError, ValueError):
                            pass
                elif key == "speed":
                    cur["speed_str"] = value
                    try:
                        cur["speed_val"] = float(value.replace("x", "").strip())
                    except (TypeError, ValueError):
                        pass
                elif key == "fps":
                    cur["fps"] = value
                elif key == "total_size":
                    try:
                        cur["size"] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif key == "progress":
                    try:
                        on_progress(cur["seconds"], cur["speed_str"], cur["speed_val"], cur["fps"], cur["size"])
                    except Exception:
                        pass

        async def drain():
            return await proc.stderr.read()

        try:
            _, err, _ = await wait_for(gather(pump(), drain(), proc.wait()), timeout=timeout)
        except BaseException:
            with suppress(Exception):
                proc.kill()
                await proc.wait()
            raise
        return "", err.decode(errors="ignore"), proc.returncode


async def probe(path):
    """(duration_seconds, width, height) - zeros when ffprobe is missing or fails."""
    if not tool("ffprobe"):
        return 0, 0, 0
    try:
        out, _, code = await run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path], 30
        )
        if code != 0:
            return 0, 0, 0
        data = json.loads(out or "{}")
        duration = int(float(data.get("format", {}).get("duration", 0) or 0))
        width = height = 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width, height = int(stream.get("width", 0) or 0), int(stream.get("height", 0) or 0)
                break
        return duration, width, height
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"ffprobe failed for {os.path.basename(path)}: {e}")
        return 0, 0, 0


async def screenshot(path, duration, out_dir):
    """JPEG frame from the middle of the video; three attempts at different positions."""
    if not tool("ffmpeg"):
        return None
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"shot_{time():.0f}_{os.getpid()}_{abs(hash(path)) % 10**6}.jpg")
    duration = duration or 3
    for position in (max(int(duration) // 2, 0), max(int(duration) // 10, 1), 1):
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(position), "-i", path,
            "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2,format=yuv420p", "-q:v", "2", out,
        ]
        try:
            _, err, code = await run(cmd, 40)
            if code == 0 and os.path.isfile(out):
                return out
        except Exception as e:  # noqa: BLE001
            LOGGER.warning(f"screenshot attempt at {position}s failed: {e or 'timeout'}")
    return None


def _layout_size(layout):
    """'2x2' / '2 2' -> (2, 2); anything invalid -> None."""
    try:
        cols, rows = str(layout or "").lower().replace(" ", "x").split("x")
        cols, rows = int(cols), int(rows)
        if 1 <= cols <= 6 and 1 <= rows <= 6:
            return cols, rows
    except (ValueError, AttributeError):
        pass
    return None


async def frame_sheet(path, duration, out_dir, layout):
    """Tile N frames from the video into one JPEG sheet (the old bot's thumbnail mode)."""
    if not tool("ffmpeg"):
        return None
    size = _layout_size(layout)
    if not size:
        return None
    cols, rows = size
    count = cols * rows
    duration = int(duration or 0)
    if duration < 2:
        return None
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"sheet_{time():.0f}_{os.getpid()}_{abs(hash(path)) % 10**6}.jpg")
    fps = max(count / max(duration, 1), 0.01)
    vf = f"fps={fps:.6f},scale=480:-2,tile={cols}x{rows}:padding=4:margin=4,format=yuv420p"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path,
        "-vf", vf, "-frames:v", "1", "-q:v", "2", out,
    ]
    try:
        _, err, code = await run(cmd, 60)
        if code == 0 and os.path.isfile(out):
            return out
        LOGGER.warning(f"frame sheet failed: {err[:160]}")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"frame sheet error: {e or 'timeout'}")
    return None


async def thumbnail(path, duration, out_dir, layout=""):
    """Best thumbnail ffmpeg can give: frame sheet when a layout is set, else one frame."""
    sheet = await frame_sheet(path, duration, out_dir, layout)
    if sheet:
        return sheet
    return await screenshot(path, duration, out_dir)


async def transcode_height(src, dest_dir, height, task=None):
    """Re-encode *src* down to *height* (used when the site has no such format)."""
    if not tool("ffmpeg"):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    out = os.path.join(dest_dir, f"{base}_{int(height)}p.mp4")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
        "-vf", f"scale=-2:{int(height)}:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast",
        "-threads", "0", "-crf", "23", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
    ]
    LOGGER.info(f"transcoding {os.path.basename(src)} -> {int(height)}p")
    try:
        if task is None:
            _, err, code = await run(cmd + [out], 6 * 3600)
        else:
            from .fmt import clock, readable_size

            source_length, _, _ = await probe(src)
            label = f"encoding {int(height)}p"
            t0 = time()

            src_sz = os.path.getsize(src) if os.path.isfile(src) else 0

            def on_progress(done_sec, speed_s, speed_v, fps, size):
                if source_length <= 0:
                    return
                cur_sec = min(done_sec, source_length)
                pct = min(max(cur_sec / source_length * 100.0, 0.0), 100.0)
                speed_disp = ""
                if speed_v > 0:
                    speed_disp = f"{speed_v:.2f}x"
                    if fps and fps not in ("0", "0.0"):
                        speed_disp += f" ({fps} fps)"
                elif speed_s and speed_s != "N/A":
                    speed_disp = speed_s
                else:
                    elapsed = time() - t0
                    if elapsed > 1 and done_sec > 0:
                        speed_disp = f"{done_sec / elapsed:.2f}x"
                    else:
                        speed_disp = "—"

                rem = max(source_length - cur_sec, 0)
                eta_s = rem / speed_v if speed_v > 0.05 else None
                len_s = f"{clock(cur_sec)} / {clock(source_length)}"
                if src_sz > 0 and size > 0:
                    sz_s = f"{readable_size(size)} / {readable_size(src_sz)}"
                elif size > 0:
                    sz_s = f"{readable_size(size)}"
                else:
                    sz_s = "—"

                task.set_phase(label, percent=pct, speed=speed_disp, eta=eta_s, length=len_s, size=sz_s)

            _, err, code = await _run_percent(
                cmd + ["-progress", "pipe:1", "-nostats", out], 6 * 3600, on_progress
            )
        if code == 0 and os.path.isfile(out):
            if task is not None:
                task.set_phase(label, 100.0)
            return out
        LOGGER.warning(f"transcode failed: {err[:200]}")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"transcode error: {e or 'timeout'}")
    return None
