"""Professional card UI: status board, completion cards, guides and system panels.

Design language (shared by every screen):
  * one clear title line, then a quiet meta line
  * thin dividers instead of crowded side-by-side rows
  * bold label + monospace value, one field per line
  * a single partial-block progress bar (▰▰▰▱▱) with a live percentage
  * compact, colour-coded inline buttons
"""

import html
import os
import re
import shutil
import time

from . import START_TIME, VERSION

try:  # psutil is optional for the stats block
    import psutil
except Exception:  # noqa: BLE001
    psutil = None

SIZES = ["B", "KB", "MB", "GB", "TB", "PB"]

STATUS_PER_PAGE = 5

STATUS_ICON = {
    "Queued": "🕒",
    "Download": "📥",
    "Upload": "📤",
    "Processing": "⚙️",
    "Convert": "🎞",
    "Extract": "🗜️",
    "Split": "✂️",
    "Password": "🔐",
}

STATUS_LABEL = {
    "Queued": "Queued",
    "Download": "Downloading",
    "Upload": "Uploading",
    "Processing": "Preparing file",
    "Convert": "Converting quality",
    "Extract": "Extracting",
    "Split": "Splitting",
    "Password": "Waiting for password",
}

_FULL = "▰"
_EMPTY = "▱"
_RULE = "┄┄┄┄┄┄┄┄┄┄┄┄"

_SMALL_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ", "h": "ʜ",
    "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ",
    "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
}


def sc(text):
    """Fancy small-caps lettering for headings and labels (ASCII stays inside <code>)."""
    return "".join(_SMALL_CAPS.get(ch.lower(), ch) for ch in str(text))


def readable_size(size):
    try:
        size = float(size)
    except (TypeError, ValueError):
        return "0B"
    if size <= 0:
        return "0B"
    idx = 0
    while size >= 1024 and idx < len(SIZES) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f}{SIZES[idx]}" if idx else f"{int(size)}B"


def readable_time(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "-"
    if seconds < 0:
        return "-"
    parts = []
    for unit, name in ((86400, "d"), (3600, "h"), (60, "m"), (1, "s")):
        value, seconds = divmod(seconds, unit)
        if value:
            parts.append(f"{value}{name}")
    return "".join(parts[:3]) or "0s"


def clock(seconds):
    """00:42 or 01:12:09 for ETA / elapsed fields."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "--:--"
    if seconds < 0:
        return "--:--"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def progress_bar(percent, length=12):
    """Modern filled / empty bar: ▰▰▰▰▰▰▱▱▱▱▱▱"""
    try:
        p = min(max(float(percent), 0.0), 100.0)
    except (TypeError, ValueError):
        p = 0.0
    filled = int(round(p / 100 * length))
    return _FULL * filled + _EMPTY * (length - filled)


def badge(number):
    """① ② ③ ... for task cards."""
    return chr(0x2460 + number - 1) if 1 <= number <= 20 else f"#{number}"


def esc(text):
    return html.escape(str(text), quote=False)


_TAG_RE = re.compile(r"</?([a-zA-Z][\w-]*)[^>]*>")


def clip(text, limit=4000):
    """Trim long messages on a line boundary and close any tag left open, so Telegram
    never rejects the card as malformed HTML (an unclosed blockquote used to freeze the board)."""
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 80, 0)].rsplit("\n", 1)[0] or text[: max(limit - 80, 0)]
    stack = []
    for match in _TAG_RE.finditer(cut):
        name = match.group(1).lower()
        if match.group(0).startswith("</"):
            if stack and stack[-1] == name:
                stack.pop()
        else:
            stack.append(name)
    closing = "".join(f"</{name}>" for name in reversed(stack))
    return cut + closing + "\n\n<i>… trimmed</i>"


def title(icon, text, meta=""):
    head = f"<b>{icon} {sc(text)}</b>"
    if meta:
        head += f"\n<i>{meta}</i>"
    return head


def _field(label, value, icon=""):
    prefix = f"{icon} " if icon else ""
    return f"{prefix}<b>{label}</b>  {value}"


def _metrics(download_dir):
    cpu = ram = 0.0
    try:
        if psutil:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
    except Exception:  # noqa: BLE001
        pass
    free = total = 0
    try:
        usage = shutil.disk_usage(download_dir if os.path.isdir(download_dir) else ".")
        free, total = usage.free, usage.total
    except OSError:
        pass
    free_pct = round(free / total * 100, 1) if total else 0.0
    return {
        "cpu": cpu,
        "ram": ram,
        "free": free,
        "total": total,
        "free_pct": free_pct,
        "used_pct": 100 - free_pct if total else 0.0,
        "uptime": time.time() - START_TIME,
    }


def system_block(download_dir):
    m = _metrics(download_dir)
    cpu = f"{m['cpu']:.0f}%"
    ram = f"{m['ram']:.0f}%"
    free = readable_size(m["free"])
    uptime = readable_time(m["uptime"])
    return (
        f"{title('🖥', 'server health')}\n"
        "<blockquote>"
        f"{_field('CPU', '<code>' + cpu + '</code>')}\n"
        f"{_field('RAM', '<code>' + ram + '</code>')}\n"
        f"{_field('Disk free', '<code>' + free + '</code> <i>(' + str(m['free_pct']) + '%)</i>')}\n"
        f"{_field('Uptime', '<code>' + uptime + '</code>')}"
        "</blockquote>"
    )


def visible_tasks(tasks, page=1, per_page=STATUS_PER_PAGE):
    pages = max((len(tasks) + per_page - 1) // per_page, 1)
    page = ((page - 1) % pages) + 1
    start = (page - 1) * per_page
    return tasks[start : start + per_page], page, pages, start


def _task_card(task, number):
    icon = STATUS_ICON.get(task.status, "•")
    label = STATUS_LABEL.get(task.status, task.status)

    if task.phase_pct is not None:
        pct = task.phase_pct
        bar_line = f"{progress_bar(pct)}  <b>{pct:.1f}%</b>"
    elif task.total:
        pct = task.percent
        bar_line = f"{progress_bar(pct)}  <b>{pct:.1f}%</b>"
    elif task.done:
        bar_line = "<i>⏳ counting bytes…</i>"
    else:
        bar_line = f"{progress_bar(0)}  <b>0.0%</b>"

    len_row = ""
    if getattr(task, "phase_len", ""):
        len_row = f"{_field('Length', f'<code>{esc(task.phase_len)}</code>')}\n"

    if getattr(task, "phase_size", ""):
        size_line = f"<code>{esc(task.phase_size)}</code>"
    elif getattr(task, "phase_info", ""):
        size_line = f"<code>{esc(task.phase_info)}</code>"
    elif task.total:
        size_line = f"<code>{readable_size(task.done)}</code> / <code>{readable_size(task.total)}</code>"
    elif task.done:
        size_line = f"<code>{readable_size(task.done)}</code>"
    else:
        size_line = "<code>—</code>"
    size_row = f"{_field('Size', size_line)}\n"

    file_row = ""
    if task.files_total > 1 and task.file_index:
        file_row = f"{_field('File', f'<code>{task.file_index}</code> / <code>{task.files_total}</code>')}\n"

    if getattr(task, "speed_str", ""):
        speed = task.speed_str
    elif task.speed:
        speed = f"{readable_size(task.speed)}/s"
    else:
        speed = "—"
    speed_row = f"{_field('Speed', f'<code>{speed}</code>')}\n"

    eta_str = clock(task.eta) if task.eta is not None else "--:--"
    elapsed_str = clock(task.elapsed())
    time_row = f"<b>ETA</b>  <code>{eta_str}</code>  ·  <b>Elapsed</b>  <code>{elapsed_str}</code>\n"

    mode_row = f"{_field('Mode', f'<code>#{esc(task.in_mode)} → #{esc(task.out_mode)}</code>')}\n"
    link = f"  ·  <a href='{esc(task.link_for_status())}'>open ↗</a>" if task.is_group() else ""
    by_row = f"{_field('By', f'{task.requester_html()}  ·  <code>{task.tid}</code>')}{link}"

    return (
        f"<b>{badge(number)} {esc(task.display_name())}</b>\n"
        "<blockquote>"
        f"{icon} <b>{esc(label)}</b>\n"
        f"{bar_line}\n"
        f"{len_row}"
        f"{size_row}"
        f"{file_row}"
        f"{speed_row}"
        f"{time_row}"
        f"{mode_row}"
        f"{by_row}"
        "</blockquote>"
    )


def status_text(tasks, download_dir, page=1, per_page=STATUS_PER_PAGE):
    """Live board. Returns (text, pages)."""
    visible, page, pages, start = visible_tasks(tasks, page, per_page)
    down = sum(t.speed for t in tasks if t.status == "Download")
    up = sum(t.speed for t in tasks if t.status == "Upload")
    lines = [
        title("📊", "active transfers", f"{len(tasks)} running  ·  page {page} of {pages}"),
        "<blockquote>"
        f"⬇️ <b>{readable_size(down)}/s</b>    ⬆️ <b>{readable_size(up)}/s</b>"
        "</blockquote>",
    ]
    for offset, task in enumerate(visible, start=1):
        lines.append(_task_card(task, start + offset))
    lines.append(system_block(download_dir))
    return clip("\n\n".join(lines), 3950), pages


def overview_text(tasks):
    """Short summary shown in the Overview pop-up (Telegram alert limit is 200 chars)."""
    down = sum(t.speed for t in tasks if t.status == "Download")
    up = sum(t.speed for t in tasks if t.status == "Upload")
    counts = {}
    for t in tasks:
        counts[t.status] = counts.get(t.status, 0) + 1
    detail = "  ·  ".join(f"{STATUS_ICON.get(k, '•')} {v}" for k, v in sorted(counts.items()))
    text = (
        f"⚡ {len(tasks)} active\n"
        f"⬇️ {readable_size(down)}/s  ·  ⬆️ {readable_size(up)}/s\n"
        f"{detail or 'idle'}"
    )
    return text[:190]


def _footer_requester(task):
    return task.requester_html()


def done_text(task, total_files, elapsed):
    size = task.total or task.done
    avg = size / elapsed if elapsed > 0 else 0
    return (
        f"{title('✅', 'task complete', esc(task.display_name()))}\n"
        "<blockquote>"
        f"{_field('Size', f'<code>{readable_size(size)}</code>', '📦')}\n"
        f"{_field('Files', f'<code>{total_files}</code>', '📄')}\n"
        f"{_field('Time', f'<code>{readable_time(elapsed)}</code>', '⏱')}\n"
        f"{_field('Average', f'<code>{readable_size(avg)}/s</code>', '⚡')}\n"
        f"{_field('Mode', f'<code>#{esc(task.in_mode)} → #{esc(task.out_mode)}</code>', '🎛')}\n"
        f"{_field('By', _footer_requester(task), '👤')}"
        "</blockquote>"
    )


def cancelled_text(task):
    return (
        f"{title('⛔', 'task cancelled', esc(task.display_name()))}\n"
        "<blockquote>"
        f"{_field('Task', f'<code>{task.tid}</code>', '🆔')}\n"
        f"{_field('Stopped after', f'<code>{readable_time(task.elapsed())}</code>', '⏱')}\n"
        f"{_field('By', _footer_requester(task), '👤')}"
        "</blockquote>"
    )


def _hint(reason):
    low = str(reason).lower()
    if "password" in low:
        return "Check the archive password, or pass it with -p <password>."
    if "403" in low or "forbidden" in low:
        return "The link is expired or hotlink-protected. Try a fresh direct link."
    if "404" in low or "not found" in low:
        return "The file no longer exists on that server."
    if "disk" in low or "space" in low:
        return "Free disk space on the bot server, then try again."
    if "empty file" in low:
        return "That link returned no data. Open it in a browser and try again."
    if "no file was produced" in low:
        return "The site produced no file. Try /yl for video links, or another source."
    if "larger than" in low:
        return "Raise MAX_FILE_SIZE_GB in config.py, or choose a smaller source."
    if "7-zip" in low or "extract" in low or "archive" in low:
        return "Use a zip/tar archive, or run install.sh so 7-Zip can open rar/7z."
    if "format is not available" in low or "no video formats" in low:
        return "Pick another quality, or refresh cookies.txt for private videos."
    if "cookies" in low or "bot" in low or "login" in low:
        return "Refresh cookies.txt with a fresh browser export, then restart the bot."
    if "flood" in low:
        return "Telegram asked the bot to slow down. Wait a minute, then retry."
    if "private" in low or "start" in low or "blocked" in low:
        return "Open the bot in a private chat, press /start, then retry."
    if "timeout" in low or "timed out" in low or "stalled" in low or "segment" in low:
        return "The transfer stalled. Check the bot server's internet and try again."
    if "unsupported" in low or "http" in low:
        return "Check that the URL is a public direct link."
    return "Check the link and try again. Use /help for command examples."


def failure_text(task, reason):
    reason = str(reason or "Unknown error")
    return (
        f"{title('⚠️', 'task stopped', esc(task.display_name()))}\n"
        "<blockquote>"
        f"<b>Reason</b>\n<code>{esc(reason[:300])}</code>\n"
        f"{_field('Size', f'<code>{readable_size(task.total or task.done)}</code>', '📦')}\n"
        f"{_field('Time', f'<code>{readable_time(task.elapsed())}</code>', '⏱')}\n"
        f"{_field('Mode', f'<code>#{esc(task.in_mode)} → #{esc(task.out_mode)}</code>', '🎛')}\n"
        f"{_field('By', _footer_requester(task), '👤')}"
        "</blockquote>\n"
        f"💡 <i>{_hint(reason)}</i>"
    )


def stats_text(download_dir, active=0):
    m = _metrics(download_dir)
    cpu = f"{m['cpu']:.0f}%"
    ram = f"{m['ram']:.0f}%"
    free = readable_size(m["free"])
    uptime = readable_time(m["uptime"])
    return (
        f"{title('📈', 'bot statistics', 'live server health')}\n"
        "<blockquote>"
        f"{_field('Uptime', '<code>' + uptime + '</code>')}\n"
        f"{_field('Active tasks', '<code>' + str(active) + '</code>')}"
        "</blockquote>\n"
        f"<b>🖥 {sc('server')}</b>\n"
        "<blockquote>"
        f"{_field('CPU', '<code>' + cpu + '</code>')}\n"
        f"{progress_bar(m['cpu'], 10)}\n"
        f"{_field('RAM', '<code>' + ram + '</code>')}\n"
        f"{progress_bar(m['ram'], 10)}\n"
        f"{_field('Disk free', '<code>' + free + '</code> <i>(' + str(m['free_pct']) + '%)</i>')}\n"
        f"{progress_bar(m['used_pct'], 10)}"
        "</blockquote>"
    )


# ------------------------------------------------------------------ help screens
def help_text(section="home"):
    if section == "leech":
        return (
            f"{title('🔗', 'leech guide', 'direct links · telegram files · archives')}\n"
            f"<b>▸ {sc('basic')}</b>\n"
            "<blockquote><code>/l https://example.com/file.zip</code>\n"
            "<i>Reply to any Telegram file with</i> <code>/l</code> <i>to re-upload it.</i></blockquote>\n"
            f"<b>▸ {sc('extract')}</b>\n"
            "<blockquote><code>/l https://example.com/file.zip -e</code>\n"
            "<i>Extraction happens only when you add</i> <code>-e</code><i>.\n"
            "Without it the file is uploaded unchanged — even a zip.</i></blockquote>\n"
            f"<b>▸ {sc('flags')}</b>\n"
            "<blockquote>"
            "<b>🏷 Rename</b>\n<code>-n New Name</code>\n"
            "<b>🗜 Extract</b>\n<code>-e</code>\n"
            "<b>🔑 Password</b>\n<code>-p password</code>\n"
            "<b>📄 Document</b>\n<code>-d</code></blockquote>\n"
            f"<b>▸ {sc('example')}</b>\n"
            "<blockquote><code>/l https://…/pack.zip -n Pack -e -p 1234</code></blockquote>\n"
            f"<b>▸ {sc('limits')}</b>\n"
            "<blockquote>"
            "📦 <i>Up to</i> <b>2GB</b> <i>per upload — larger files are split automatically</i>\n"
            "💾 <i>Free disk is checked before every task</i>\n"
            "🧹 <i>Files are removed from the server right after upload</i></blockquote>"
        )
    if section == "ytdl":
        return (
            f"{title('🎬', 'yt-dlp guide', 'YouTube · HLS/m3u8 · DASH · 1000+ sites')}\n"
            f"<b>▸ {sc('basic')}</b>\n"
            "<blockquote><code>/yl https://youtu.be/…</code>\n"
            "<code>/yl https://site.com/stream.m3u8</code>\n"
            "<i>The quality menu lists only the heights this video really has,</i>\n"
            "<i>with approximate sizes · audio · best.</i></blockquote>\n"
            f"<b>▸ {sc('flags')}</b>\n"
            "<blockquote>"
            "<b>🏷 Rename</b>\n<code>-n Name</code>\n"
            "<b>🎚 Quality</b>\n<code>-q 720</code>\n"
            "<i>skips the menu · 2160 / 1440 / 1080 / 720 / 480 / 360 …</i>\n"
            "<b>🎧 Audio</b>\n<code>-a</code>\n"
            "<i>MP3 @ 192k</i></blockquote>\n"
            f"<b>▸ {sc('cookies')}</b>\n"
            "<blockquote><code>cookies.txt</code>\n"
            "<i>Paste Netscape cookies into that file for private or\n"
            "age-restricted videos, then restart the bot.</i>\n"
            "<code>/cookies</code> <i>shows the exact path and status.</i></blockquote>\n"
            f"<b>▸ {sc('example')}</b>\n"
            "<blockquote><code>/yl https://youtu.be/… -q 1080 -n MyVideo</code></blockquote>\n"
            "<i>Playlists and livestreams are not supported.</i>"
        )
    if section == "status":
        return (
            f"{title('📊', 'control guide', 'watch, stop and manage transfers')}\n"
            f"<b>▸ {sc('live board')}</b>\n"
            "<blockquote><code>/status</code>\n"
            "<i>One message updates itself while tasks run.</i>\n"
            "<b>📊 Overview</b>  <i>quick summary</i>\n"
            "<b>🔄 Refresh</b>  <i>redraw the board</i>\n"
            "<b>◀ ▶</b>  <i>change page</i></blockquote>\n"
            f"<b>▸ {sc('stop a task')}</b>\n"
            "<blockquote><code>/cancel</code>\n"
            "<i>tap a red stop button — no code to copy</i>\n"
            "<code>/c_ab12cd34</code>\n"
            "<i>direct stop link</i>\n"
            "<i>Only the task owner can stop it.</i></blockquote>\n"
            f"<b>▸ {sc('board icons')}</b>\n"
            "<blockquote><i>📥 download\n📤 upload\n🎞 converting quality\n🗜 extract\n✂️ split\n"
            "⬇️⬆️ live speed\n⏳ ETA\n⏱ elapsed</i></blockquote>"
        )
    if section == "tools":
        return (
            f"{title('🛠', 'tools and access')}\n"
            f"<b>▸ {sc('thumbnails')}</b>\n"
            "<blockquote><b>Save</b>  <code>/setthumb</code>\n"
            "<i>reply to a photo</i>\n"
            "<b>Remove</b>  <code>/delthumb</code>\n"
            "<i>Videos without a custom thumb get a composed TMDb card, then a video frame.</i></blockquote>\n"
            f"<b>▸ {sc('cookies')}</b>\n"
            "<blockquote><b>File</b>  <code>cookies.txt</code>\n"
            "<i>Paste Netscape cookies here for private / age-locked videos.</i>\n"
            "<b>Check</b>  <code>/cookies</code></blockquote>\n"
            f"<b>▸ {sc('info')}</b>\n"
            "<blockquote><b>Stats</b>  <code>/stats</code>\n"
            "<b>Latency</b>  <code>/ping</code>\n"
            "<b>Guide</b>  <code>/help</code></blockquote>\n"
            f"<b>▸ {sc('owner')}</b>\n"
            "<blockquote><code>/authorize</code> · <code>/unauthorize</code>\n"
            "<code>/ban</code> · <code>/unban</code>\n"
            "<code>/premium add|remove|list</code>\n"
            "<code>/log</code> · <code>/restart</code></blockquote>\n"
            "<i>Use the bot only for content you own or may share.</i>"
        )
    return (
        f"{title('📖', 'command centre', 'every command, explained')}\n"
        f"<b>🚀 {sc('transfers')}</b>\n"
        "<blockquote>"
        "<b>Leech a link</b>\n"
        "<code>/l &lt;link&gt;</code>\n"
        "<i>download and upload exactly as-is</i>\n"
        "\n"
        "<b>Extract an archive</b>\n"
        "<code>/l &lt;link&gt; -e</code>\n"
        "<i>only with -e: extract, then upload</i>\n"
        "\n"
        "<b>Video or stream</b>\n"
        "<code>/yl &lt;link&gt;</code>\n"
        "<i>YouTube, HLS, DASH and 1000+ sites</i>\n"
        "\n"
        "<b>Telegram file</b>\n"
        "<i>reply to any file with</i> <code>/l</code>"
        "</blockquote>\n"
        f"<b>🎛 {sc('control')}</b>\n"
        "<blockquote>"
        "<b>Status board</b>\n"
        "<code>/status</code>\n"
        "<i>live progress — group only</i>\n"
        "\n"
        "<b>Stop a task</b>\n"
        "<code>/cancel &lt;id&gt;</code>\n"
        "<i>or tap the stop button on the board</i>"
        "</blockquote>\n"
        f"<b>ℹ️ {sc('more')}</b>\n"
        "<blockquote><code>/stats</code>  ·  <code>/ping</code>  ·  <code>/cookies</code></blockquote>\n"
        "<i>Tap a section below for flags, examples and limits.</i>"
    )


def quality_label(height):
    height = int(height)
    return {2160: "4K", 1440: "2K"}.get(height, f"{height}p")


def probe_text(count):
    links = int(count or 1)
    many = "" if links == 1 else "s"
    return (
        f"<b>🔍 {sc('reading formats')}</b>\n"
        f"<i>checking {links} link{many} — only the qualities that really exist are shown</i>"
    )


def ping_text(latency):
    try:
        ms = int(round(float(latency)))
    except (TypeError, ValueError):
        ms = 0
    return (
        f"<b>🏓 {sc('pong')}</b>\n"
        "<i>the bot is online and listening</i>\n"
        "<blockquote>"
        f"⚡ <b>Latency</b>  <code>{ms} ms</code>\n"
        "🟢 <b>Status</b>  <i>online</i>\n"
        f"♾ <b>Version</b>  <code>v{esc(VERSION)}</code>"
        "</blockquote>"
    )


def quality_text(count, heights=None, sizes=None, audio=True, real=None):
    links = int(count or 1)
    heights = sorted({int(h) for h in (heights or [])}, reverse=True)
    real = {int(h) for h in (real if real is not None else heights)}
    sizes = sizes or {}
    formats = []
    for height in heights:
        size = sizes.get(height) or 0
        label = quality_label(height)
        if height not in real:
            label = f"⚙️ {label}"
        if size:
            label += f"  ~{readable_size(size)}"
        formats.append(label)
    if formats:
        block = "<blockquote>📼 <b>Formats</b>\n<code>" + "  ·  ".join(formats) + "</code></blockquote>"
    else:
        block = (
            "<blockquote>📼 <b>Formats</b>\n"
            "<i>this site publishes no format list — Best takes the highest stream</i></blockquote>"
        )
    rows = [f"🔗 <b>Links</b>  <code>{links}</code>"]
    if audio:
        rows.append("🎵 <b>Audio</b>  <i>MP3 · 192k</i>")
    rows.append("⭐ <b>Best</b>  <i>highest available</i>")
    note = (
        "⚙️ <i>converted with FFmpeg · the chosen height is used for every link</i>"
        if links > 1
        else "⚙️ <i>converted with FFmpeg · sizes are approximate</i>"
    )
    return "\n".join(
        [
            f"<b>🎚 {sc('choose a quality')}</b>",
            "<i>only the formats this link really has are listed</i>",
            block,
            "<blockquote>" + "\n".join(rows) + "</blockquote>",
            note,
        ]
    )


def start_text(name):
    who = esc(str(name)[:24])
    return (
        f"<blockquote><b>🫧𓆩𖣐 {who} 𖣐𓆪 🫧</b>\n"
        "<i>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴀᴅᴠᴀɴᴄᴇᴅ ғɪʟᴇ ᴏʀɢᴀɴɪᴢᴇʀ ʙᴏᴛ</i></blockquote>\n"
        "<blockquote><i>ᴛʜɪs ʙᴏᴛ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴏʀɢᴀɴɪᴢᴇs ᴀɴᴅ ᴅᴇʟɪᴠᴇʀs ʏᴏᴜʀ "
        "ғɪʟᴇs ɪɴ ᴛʜᴇ ʀɪɢʜᴛ sᴇǫᴜᴇɴᴄᴇ. sᴇɴᴅ ᴀɴʏ ɴᴜᴍʙᴇʀ ᴏғ ʟɪɴᴋs ɪɴ ᴏɴᴇ "
        "ᴍᴇssᴀɢᴇ — ᴇᴀᴄʜ ʟɪɴᴋ ʙᴇᴄᴏᴍᴇs ɪᴛs ᴏᴡɴ ᴛᴀsᴋ.</i></blockquote>\n"
        "<blockquote>💠 <i>ᴛʜɪs ɪs ᴀ ᴘʀɪᴠᴀᴛᴇʟʏ ᴍᴀɴᴀɢᴇᴅ sʏsᴛᴇᴍ ғᴏʀ "
        "ᴏʀɢᴀɴɪᴢɪɴɢ ᴄᴏɴᴛᴇɴᴛ ɪɴ ᴛʜᴇ ʀɪɢʜᴛ sᴇǫᴜᴇɴᴄᴇ.</i>\n"
        "📬 <i>finished files arrive in your private chat</i></blockquote>\n"
        f"<b>⚡ {sc('quick start')}</b>\n"
        "<blockquote>"
        "🔗 <code>/l &lt;direct link&gt;</code>\n"
        "🎬 <code>/yl &lt;video link&gt;</code>\n"
        "🗜 <code>/l &lt;archive&gt; -e</code>\n"
        "👥 <i>send these in your group</i>"
        "</blockquote>\n"
        "<blockquote><b>𝚃ʜɪs 𝙸s 𝙰ɴ 𝙰ᴅᴠᴀɴᴄᴇᴅ 𝙰ɴᴅ 𝚈ᴇ𝚃 𝙿ᴏᴡᴇʀғᴜʟ "
        "𝙼𝙸𝚁𝚁𝙾𝚁 𝙻𝙴𝙴𝙲𝙷 𝙱𝙾𝚃</b></blockquote>"
    )
