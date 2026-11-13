"""Telegram uploader.

Design rules (fixed):
  * every task is an independent job: its files go out in episode order, while OTHER tasks
    upload their own files at the same time (only a global MAX_CONCURRENT_UPLOADS cap)
  * the "Upload" status only appears when bytes really start moving; probing, thumbnail
    building and splitting are shown as their own states so the progress bar never lies
  * each file is deleted right after it is sent (disk stays free)
"""

import os
import re
from asyncio import Semaphore, sleep

from pyrogram.errors import FloodWait

from . import LOGGER
from . import engines, media, tmdb
from .archive import split_file
from .config import Config
from .fmt import esc, readable_size
from .store import user_thumb_path
from .task import Cancelled


# Files are uploaded in parallel, but the total number of simultaneous transmissions is
# capped by MAX_CONCURRENT_UPLOADS (2 by default). This keeps several tasks moving at once
# without flooding the Telegram connection; it is NOT a per-task serialising queue.
_slots = None
_slots_limit = 0


def _slot_limit():
    try:
        return max(1, int(Config.MAX_CONCURRENT_UPLOADS))
    except (TypeError, ValueError):
        return 2


def _sem():
    global _slots, _slots_limit
    limit = _slot_limit()
    if _slots is None or _slots_limit != limit:
        _slots = Semaphore(limit)
        _slots_limit = limit
    return _slots


_EP = (
    re.compile(r"s(\d{1,3})\s*[ex](\d{1,4})", re.I),
    re.compile(r"(\d{1,2})x(\d{2,4})", re.I),
    re.compile(r"(?:^|[^a-z])(?:ep|episode|e)[\s._-]*(\d{1,4})(?!\d)", re.I),
)


def _natural(text):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def episode_key(path):
    """Season, episode, then natural name order: E1, E2 ... E10, E11."""
    base = os.path.basename(path)
    for pattern in _EP:
        m = pattern.search(base)
        if m:
            nums = [int(x) for x in m.groups()]
            season, episode = (nums[0], nums[1]) if len(nums) == 2 else (0, nums[0])
            return (0, season, episode, _natural(base))
    return (1, 0, 0, _natural(base))


def collect_files(root):
    found = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.startswith(".") or n.endswith((".part", ".ytdl", ".temp")) or "_tmdb" in dirpath:
                continue
            found.append(os.path.join(dirpath, n))
    return sorted(found, key=episode_key)


def msg_link(msg):
    try:
        link = msg.link
    except Exception:  # noqa: BLE001
        link = None
    return link or f"tg://openmessage?user_id={msg.chat.id}&message_id={msg.id}"


def destination(task):
    """Groups -> the user's private chat (when LEECH_TO_PM); private chats stay as they are."""
    in_group = task.chat_id != task.user_id and task.chat_id < 0
    return task.user_id if (Config.LEECH_TO_PM and in_group) else task.chat_id


async def _pick_thumb(task, path, duration, work_dir):
    """user thumbnail > TMDb backdrop+logo > multi-frame ffmpeg sheet. Returns (path, delete_after)."""
    user_thumb = user_thumb_path(task.user_id)
    if user_thumb:
        return user_thumb, False
    tmdb_thumb = await tmdb.auto_thumbnail(os.path.basename(path), work_dir)
    if tmdb_thumb:
        return tmdb_thumb, True
    shot = await media.thumbnail(path, duration, work_dir, Config.THUMBNAIL_LAYOUT)
    return shot, True


def _telegram_thumb(path, work_dir):
    """Telegram rejects thumbnails over 200 kB: shrink to 320px JPEG, or drop it."""
    try:
        if os.path.getsize(path) <= 190 * 1024:
            return path, False
    except OSError:
        return None, False
    try:
        from uuid import uuid4

        from PIL import Image

        small = os.path.join(work_dir, f"thumb_small_{uuid4().hex[:8]}.jpg")
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((320, 320))
            for quality in (85, 75, 65):
                img.save(small, "JPEG", quality=quality, optimize=True)
                if os.path.getsize(small) <= 190 * 1024:
                    return small, True
        os.remove(small)
        LOGGER.warning("thumbnail skipped: still over Telegram's 200 kB limit")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"thumbnail skipped: {type(e).__name__}: {e}")
    return None, False


def _caption(path, size, width=0, height=0):
    meta = f"📦 <code>{readable_size(size)}</code>"
    if width and height:
        meta += f"  ·  🎞 <code>{width}×{height}</code>"
    return f"<b>{esc(os.path.basename(path))}</b>\n<blockquote>{meta}</blockquote>"


async def _send_one(client, task, chat_id, path, work_dir, base=0, overall=0):
    kind = media.kind(path)
    if Config.AS_DOCUMENT or task.flags.get("doc"):
        kind = "document"
    name = os.path.basename(path)
    size = os.path.getsize(path)

    thumb, thumb_tmp = (None, False)
    duration = width = height = 0
    if kind == "video":
        # Preparation is its own state: the bar stays out of "Upload" until data flows.
        task.set_status("Processing")
        duration, width, height = await media.probe(path)
        thumb, thumb_tmp = await _pick_thumb(task, path, duration, work_dir)
        if thumb:
            small, made = _telegram_thumb(thumb, work_dir)
            if small:
                if made and thumb_tmp:
                    try:
                        os.remove(thumb)
                    except OSError:
                        pass
                thumb, thumb_tmp = small, thumb_tmp or made
            else:
                if thumb_tmp:
                    try:
                        os.remove(thumb)
                    except OSError:
                        pass
                thumb, thumb_tmp = None, False
    elif kind == "audio":
        task.set_status("Processing")
        duration, _, _ = await media.probe(path)

    caption = _caption(path, size, width, height)
    # One bar for the whole task: the second file of a batch continues where the first
    # stopped instead of dropping back to 0%.
    if overall:
        task.resume_at(base, overall)
    else:
        task.reset_progress(size)
    task.set_status("Upload")
    task.engine = engines.telegram()

    async def progress(current, total):
        task.check_cancel()
        task.update(base + current, overall or total)

    try:
        tries = 0
        while True:
            task.check_cancel()
            try:
                async with _sem():
                    if kind == "video":
                        return await client.send_video(
                            chat_id, path, caption=caption, duration=duration or None,
                            width=width or None, height=height or None,
                            thumb=thumb, supports_streaming=True, progress=progress, disable_notification=True,
                        )
                    if kind == "audio":
                        title = os.path.splitext(name)[0][:64]
                        return await client.send_audio(
                            chat_id, path, caption=caption, duration=duration, title=title, performer="RS Leech",
                            progress=progress, disable_notification=True,
                        )
                    return await client.send_document(
                        chat_id, path, caption=caption, force_document=True, progress=progress, disable_notification=True
                    )
            except FloodWait as e:
                LOGGER.warning(f"FloodWait {e.value}s while uploading {name}")
                await sleep(e.value + 1)
            except Cancelled:
                raise
            except Exception as e:  # noqa: BLE001
                tries += 1
                kind_name = type(e).__name__
                if kind_name in ("PeerIdInvalid", "UserIsBlocked", "InputUserDeactivated", "ChatWriteForbidden"):
                    raise UploadError(
                        "I can't message you privately. Open the bot in a private chat, press /start "
                        "(unblock it if needed) and send the command again."
                    ) from e
                if tries >= 4:
                    raise UploadError(f"Upload failed: {kind_name}: {e}") from e
                LOGGER.warning(f"upload retry {tries}/4 for {name}: {kind_name}")
                if tries >= 2:
                    thumb = None  # a bad thumbnail part: send without it
                await sleep(2 * tries)
    finally:
        if thumb_tmp and thumb and os.path.isfile(thumb):
            try:
                os.remove(thumb)
            except OSError:
                pass


class UploadError(Exception):
    pass


async def upload_all(client, task, files, work_dir):
    """Upload *files* one by one for THIS task (other tasks run their own uploads in parallel)."""
    sent = []
    chat_id = destination(task)
    overall = sum(os.path.getsize(f) for f in files)
    task.total = overall
    task.files_total = task.files_total or len(files)
    base = 0
    for index, path in enumerate(files, 1):
        task.check_cancel()
        task.file_index = index
        parts = [path]
        size = os.path.getsize(path)
        if size > Config.SPLIT_SIZE:
            import shutil

            free = shutil.disk_usage(os.path.dirname(path)).free
            if free < size + 64 * 1024 * 1024:
                raise UploadError(
                    "Not enough free disk space to split this file. Free some space and try again."
                )
            task.set_status("Split")
            LOGGER.info(f"splitting {os.path.basename(path)} ({size} bytes)")
            from asyncio import get_running_loop

            parts = await get_running_loop().run_in_executor(None, split_file, path, Config.SPLIT_SIZE)
            os.remove(path)
        for part in parts:
            part_size = os.path.getsize(part)
            msg = await _send_one(client, task, chat_id, part, work_dir, base, max(overall, base + part_size))
            base += part_size
            task.files_sent += 1
            sent.append((os.path.basename(part), msg_link(msg)))
            try:
                os.remove(part)  # free the disk before the next file
            except OSError:
                pass
    return sent
