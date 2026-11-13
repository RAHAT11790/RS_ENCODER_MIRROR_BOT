"""yt-dlp wrapper: every site yt-dlp supports, including HLS (.m3u8) and DASH (.mpd) streams.

Fixes in this version:
  * cookies are validated before use and the plain/with-cookies order is retried on the
    exact "format not available / sign in" failures instead of dying on the first attempt;
  * the quality menu offers the real heights of the link plus a standard ladder, and a
    height the site does not provide is produced with ffmpeg (real conversion, not a lie);
  * only the single URL given by the user is processed, in one worker thread with a cancel
    hook, so nothing keeps running after /cancel.
"""

import os
import time
from asyncio import get_running_loop
from urllib.parse import urlparse

from . import LOGGER
from . import engines, media
from .config import Config
from .task import Cancelled


class YtdlError(Exception):
    pass


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_VIDEO_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com", "dailymotion.com",
    "facebook.com", "fb.watch", "instagram.com", "tiktok.com", "twitter.com", "x.com",
    "twitch.tv", "rumble.com", "bilibili.com", "soundcloud.com", "reddit.com",
)

# Heights the menu can offer; anything not in the source is transcoded with ffmpeg.
STANDARD_HEIGHTS = (360, 480, 720, 1080, 1440, 2160)


def _host(url):
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube_link(url):
    host = _host(url)
    return host == "youtu.be" or host.endswith("youtube.com") or host.endswith("youtube-nocookie.com")


def is_video_link(url):
    """True for HLS/DASH streams and for hosts that yt-dlp handles better than a raw download."""
    if is_stream_link(url):
        return True
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS)


def cookies_path():
    """Absolute path of the cookies file (relative paths live next to main.py)."""
    value = str(Config.YT_COOKIES_FILE or "").strip()
    if not value:
        return ""
    if not os.path.isabs(value):
        value = os.path.join(PROJECT_ROOT, value)
    return os.path.normpath(value)


def _cookie_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "\t" in line:
                    lines.append(line)
    except OSError:
        return []
    return lines


def cookies_state():
    """-> (path, ready). ready is True only when the file contains real cookie lines."""
    path = cookies_path()
    return path, bool(_cookie_lines(path))


def is_stream_link(url):
    low = url.lower().split("?")[0]
    return low.endswith((".m3u8", ".mpd")) or ".m3u8" in url.lower()


def _format_for(quality, audio=False):
    if audio:
        return "bestaudio/best"
    if quality:
        q = int(quality)
        return (
            f"bv*[height<={q}][ext=mp4]+ba[ext=m4a]"
            f"/b[height<={q}][ext=mp4]"
            f"/bv*[height<={q}]+ba"
            f"/b[height<={q}]"
            f"/bestvideo[height<={q}]+bestaudio"
            f"/best[height<={q}]/best"
        )
    return (
        "bv*[ext=mp4]+ba[ext=m4a]"
        "/b[ext=mp4]"
        "/bv*+ba/b"
        "/bestvideo+bestaudio/best"
    )


def build_options(dest_dir, task, quality=None, audio=False):
    import yt_dlp  # imported lazily so the bot still starts if it is being upgraded

    name = task.flags.get("name")
    template = f"{name}.%(ext)s" if name else "%(title).150B.%(ext)s"

    def hook(d):
        if task.cancelled:
            raise yt_dlp.utils.DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            task.update(int(d.get("downloaded_bytes") or 0), int(total) or None)
            if d.get("speed"):
                task.speed = d["speed"]
            if d.get("eta") is not None:
                task.eta = d["eta"]
        elif status == "finished":
            task.set_status("Processing")

    opts = {
        "outtmpl": os.path.join(dest_dir, template),
        "format": _format_for(quality, audio),
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "file_access_retries": 3,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": max(16, Config.DOWNLOAD_CONNECTIONS),
        "buffersize": 2 * 1024 * 1024,
        "http_chunk_size": 10 * 1024 * 1024,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "windowsfilenames": True,
        "restrictfilenames": False,
        "overwrites": True,
        "nocheckcertificate": bool(Config.ALLOW_INSECURE_SSL),
        # keep looking for a usable format instead of aborting the whole task
        "ignore_no_formats_error": False,
        "check_formats": False,
    }
    if not audio:
        opts["merge_output_format"] = "mp4"
        opts["format_sort"] = ["res", "fps", "hdr:12", "vcodec"]
    else:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    cookie_file, cookies_ready = cookies_state()
    if cookies_ready:
        opts["cookiefile"] = cookie_file
    return opts


def _run(url, opts, task):
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and info.get("_type") == "playlist" and info.get("entries"):
                info = next((e for e in info["entries"] if e), info)
            task.name = task.name or (info or {}).get("title") or ""
            return info
    except yt_dlp.utils.DownloadCancelled:
        raise Cancelled()
    except yt_dlp.utils.DownloadError as e:
        raise YtdlError(str(e).replace("ERROR: ", "")[:400])


_RETRY_HINTS = (
    "no video formats found",
    "requested format is not available",
    "only images are available",
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "login required",
    "cookies are no longer valid",
    "cookies are missing",
    "private video",
    "age-restricted",
    "age restricted",
    "content isn't available",
    "video unavailable",
    "this video is unavailable",
    "http error 401",
    "http error 403",
    "unable to extract",
)

_FORMAT_HINTS = (
    "requested format is not available",
    "no video formats found",
    "only images are available",
)


def _retry_worthwhile(message):
    low = message.lower()
    return any(hint in low for hint in _RETRY_HINTS)


def _format_problem(message):
    low = message.lower()
    return any(hint in low for hint in _FORMAT_HINTS)


def _relaxed(opts, audio):
    out = dict(opts)
    out.pop("cookiefile", None)  # public ladders are the broadest; private videos already work with cookies
    out["format"] = "bestaudio/best" if audio else "bestvideo*+bestaudio/best/bestvideo*/best"
    return out


def _attempts(opts, url):
    """Ordered option sets: plain first on YouTube (browser cookies hide public ladders),
    cookies first elsewhere (many sites need the login). The last attempt relaxes the
    format selector so an odd site still yields its best stream instead of failing."""
    plain = {k: v for k, v in opts.items() if k != "cookiefile"}
    if "cookiefile" in opts:
        base = [plain, opts] if is_youtube_link(url) else [opts, plain]
    else:
        base = [opts]
    base.append(_relaxed(opts, opts.get("format") == "bestaudio/best"))
    return base


# ---------------------------------------------------------------- real formats
_PROBE_CACHE = {}
_PROBE_TTL = 300


def _probe_options():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 25,
        "retries": 3,
        "nocheckcertificate": bool(Config.ALLOW_INSECURE_SSL),
    }
    cookie_file, ready = cookies_state()
    if ready:
        opts["cookiefile"] = cookie_file
    return opts


def _height_of(fmt):
    value = fmt.get("height")
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    resolution = str(fmt.get("resolution") or "")
    if "x" in resolution:
        try:
            return int(resolution.rsplit("x", 1)[-1])
        except ValueError:
            return 0
    return 0


def _probe_once(url, opts):
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info and info.get("_type") == "playlist" and info.get("entries"):
        info = next((e for e in info["entries"] if e), info) or {}
    heights = {}
    audio = False
    audio_size = 0
    for fmt in info.get("formats") or []:
        acodec = fmt.get("acodec")
        has_audio = bool(acodec) and acodec != "none"
        if fmt.get("vcodec") == "none":
            if has_audio:
                audio = True
                audio_size = max(audio_size, int(fmt.get("filesize") or fmt.get("filesize_approx") or 0))
            continue
        if has_audio:
            audio = True
        height = _height_of(fmt)
        if not height:
            continue
        size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
        heights[height] = max(heights.get(height, 0), size)
    if audio_size:
        heights = {h: (s + audio_size if s else 0) for h, s in heights.items()}
    return {
        "title": info.get("title") or "",
        "heights": heights,
        "audio": audio,
        "live": bool(info.get("is_live")),
    }


def _probe(url):
    opts = _probe_options()
    plain = {k: v for k, v in opts.items() if k != "cookiefile"}
    if "cookiefile" in opts:
        attempts = [plain, opts] if is_youtube_link(url) else [opts, plain]
    else:
        attempts = [opts]
    last = None
    for attempt in attempts:
        try:
            return _probe_once(url, attempt)
        except Exception as e:  # noqa: BLE001 (yt-dlp raises many error types)
            last = e
    raise YtdlError(str(last).replace("ERROR: ", "")[:300])


async def probe(url):
    """Formats the link really offers: {height: approx bytes} plus audio availability."""
    cached = _PROBE_CACHE.get(url)
    if cached and time.time() - cached[0] < _PROBE_TTL:
        return cached[1]
    result = await get_running_loop().run_in_executor(None, _probe, url)
    _PROBE_CACHE[url] = (time.time(), result)
    return result


def menu_heights(actual):
    """Heights offered in the menu: the real ones plus a standard ladder for conversion."""
    real = sorted(int(h) for h in actual if int(h) > 0)
    if not real:
        return []
    top = max(real)
    ceiling = max(top, 720)  # a 360p-only source can still be offered as 480/720
    ladder = [h for h in STANDARD_HEIGHTS if h <= ceiling]
    return sorted(set(real) | set(ladder))


def converted_heights(heights, actual):
    """Heights in the menu that the source does not provide (they need ffmpeg)."""
    real = {int(h) for h in actual}
    return sorted(set(int(h) for h in heights) - real)


def _actual_height(path):
    width, height = 0, 0
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=p=0:s=x", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        if "x" in out:
            width, height = (int(x) for x in out.split("x")[:2])
    except Exception:  # noqa: BLE001
        pass
    return width, height


async def _convert_if_needed(path, task, quality, audio):
    """Produce the requested height with ffmpeg when the source did not have it."""
    if audio or not quality:
        return path
    wanted = int(quality)
    _, height = _actual_height(path)
    if not height or height == wanted:
        return path
    # small tolerance: 1080 requested, source 1078 -> no need to re-encode
    if abs(height - wanted) <= 8:
        return path
    task.reset_progress()
    task.set_status("Convert")
    converted = await media.transcode_height(path, os.path.dirname(path), wanted, task)
    if not converted:
        LOGGER.warning(
            f"source is {height}p and conversion to {wanted}p failed; uploading the original"
        )
        return path
    try:
        os.remove(path)
    except OSError:
        pass
    return converted


async def download(url, dest_dir, task, quality=None, audio=False):
    os.makedirs(dest_dir, exist_ok=True)
    task.engine = engines.ytdlp()
    task.set_status("Download")
    opts = build_options(dest_dir, task, quality, audio)
    loop = get_running_loop()
    LOGGER.info(f"yt-dlp: {url[:100]}")

    attempts = _attempts(opts, url)
    info, failure = None, None
    for index, attempt in enumerate(attempts):
        try:
            info = await loop.run_in_executor(None, _run, url, attempt, task)
            failure = None
            break
        except YtdlError as e:
            failure = e
            if not _retry_worthwhile(str(e)):
                raise
            if index + 1 < len(attempts):
                LOGGER.warning(f"yt-dlp: retry {index + 2}/{len(attempts)} after: {str(e)[:120]}")
                task.check_cancel()
                task.reset_progress()
                continue
            break
    if failure is not None:
        raise failure
    task.check_cancel()
    files = [
        os.path.join(dest_dir, f)
        for f in os.listdir(dest_dir)
        if not f.endswith((".part", ".ytdl", ".temp")) and os.path.isfile(os.path.join(dest_dir, f))
    ]
    if not files:
        raise YtdlError("yt-dlp finished but no file was produced.")
    files.sort(key=os.path.getmtime)
    path = files[-1]
    path = await _convert_if_needed(path, task, quality, audio)
    return path, info
