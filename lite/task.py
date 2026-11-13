"""Task object shared by downloader, uploader and status messages."""

import time
from asyncio import Event
from uuid import uuid4

from . import engines
from .fmt import esc


class Cancelled(Exception):
    """Raised inside a task when the user pressed stop."""


class Task:
    def __init__(self, message, link, mode, flags=None):
        self.tid = uuid4().hex[:8]
        self.message = message
        self.chat_id = message.chat.id
        user = message.from_user
        self.user_id = user.id if user else message.chat.id
        self.username = (user.username if user else None) or ""
        self.first_name = (user.first_name if user else "") or ""
        self.link = link or ""
        self.mode = mode            # "direct" | "ytdl" | "telegram"
        self.flags = flags or {}
        self.name = self.flags.get("name") or ""
        self.status = "Queued"
        self.engine = {"direct": engines.direct, "ytdl": engines.ytdlp, "telegram": engines.telegram}[mode]()
        self.in_mode = {"direct": "Direct", "ytdl": "YT-DLP", "telegram": "Telegram"}.get(mode, "Direct")
        self.total = 0
        self.done = 0
        self.speed = 0
        self.eta = None
        self.started = time.time()
        self.cancelled = False
        self.cancel_event = Event()
        self.asyncio_task = None
        self.password_wait = None   # future resolved with the password typed in chat
        self.extra_messages = []    # bot cards (password prompt) removed when the task ends
        self.path = ""          # task working directory
        self.files_sent = 0
        self.files_total = 0    # files this task will upload (after extraction/split)
        self.file_index = 0     # which file is uploading right now
        self.phase = ""         # short label for a phase that reports percent, not bytes
        self.phase_pct = None
        self.phase_len = ""     # e.g. "01:54 / 23:04"
        self.phase_size = ""    # e.g. "14.25MB / 350.50MB"
        self.speed_str = ""     # live speed string, e.g. "2.99x (179 fps)"
        self.phase_info = ""
        self._samples = []

    # ---- progress ------------------------------------------------------
    @property
    def percent(self):
        if not self.total:
            return 0.0
        return min(max(self.done / self.total * 100.0, 0.0), 100.0)

    def update(self, done, total=None):
        now = time.time()
        self.done = done
        if total:
            self.total = total
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[0][0] > 5:
            self._samples.pop(0)
        if len(self._samples) >= 2:
            t0, d0 = self._samples[0]
            span = now - t0
            if span > 0.2:
                self.speed = max((done - d0) / span, 0)
        remainder = max(self.total - done, 0) if self.total else 0
        self.eta = (remainder / self.speed) if self.speed and self.total else None
        # NOTE: the status board is refreshed only by its own timer (STATUS_UPDATE_INTERVAL).
        # Progress updates must NOT wake it, otherwise a single second of transfer causes
        # several Telegram edits and quickly reaches FloodWait.

    def reset_progress(self, total=0):
        self.done = 0
        self.total = total
        self.speed = 0
        self.eta = None
        self.phase = ""
        self.phase_pct = None
        self.phase_len = ""
        self.phase_size = ""
        self.speed_str = ""
        self.phase_info = ""
        self._samples.clear()

    def set_phase(self, label, percent=None, speed=None, eta=None, length=None, size=None, info=None):
        """Percent-only phase (e.g. an FFmpeg encode or archive extraction)."""
        self.phase = label or ""
        if percent is None:
            self.phase_pct = None
        else:
            self.phase_pct = min(max(float(percent), 0.0), 100.0)
        if speed is not None:
            self.speed_str = str(speed)
        if eta is not None:
            self.eta = eta
        if length is not None:
            self.phase_len = str(length)
        if size is not None:
            self.phase_size = str(size)
        elif info is not None:
            self.phase_size = str(info)

    def set_status(self, status):
        """Phase change: the previous phase's speed and ETA no longer describe work."""
        if status != self.status:
            self.status = status
            self.speed = 0
            self.eta = None
            self.phase = ""
            self.phase_pct = None
            self.phase_len = ""
            self.phase_size = ""
            self.speed_str = ""
            self.phase_info = ""
            self._samples.clear()

    def resume_at(self, done, total):
        """Continue the same overall bar at *done* bytes (next file of a batch)."""
        self.done = max(int(done), 0)
        self.total = int(total or self.total or 0)
        self.speed = 0
        self.eta = None
        self.phase = ""
        self.phase_pct = None
        self.phase_len = ""
        self.phase_size = ""
        self.speed_str = ""
        self.phase_info = ""
        self._samples.clear()

    def elapsed(self):
        return time.time() - self.started

    def estimated_total(self):
        return self.elapsed() + (self.eta or 0)

    # ---- cancel --------------------------------------------------------
    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()
        if self.asyncio_task and not self.asyncio_task.done():
            self.asyncio_task.cancel()

    def check_cancel(self):
        if self.cancelled:
            raise Cancelled()

    # ---- display -------------------------------------------------------
    def display_name(self):
        return self.name or (self.link[:60] if self.link else "Preparing...")

    @property
    def out_mode(self):
        if self.flags.get("encode"):
            res = (self.flags.get("encode") or {}).get("resolution") or "OG"
            return f"Encode-{res}"
        return "Leech-Unzip" if self.flags.get("extract") else "Leech"

    def is_group(self):
        return self.chat_id < 0 and self.chat_id != self.user_id

    def requester_html(self):
        # built here (instead of User.mention) so a name with <, > or & cannot break the HTML
        if self.first_name:
            return f"<a href='tg://user?id={self.user_id}'>{esc(self.first_name)}</a>"
        if self.username:
            return f"@{esc(self.username)}"
        return f"<code>{self.user_id}</code>"

    def link_for_status(self):
        try:
            return self.message.link or "https://t.me"
        except Exception:  # noqa: BLE001
            return "https://t.me"
