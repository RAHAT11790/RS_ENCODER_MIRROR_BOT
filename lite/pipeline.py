"""Task manager + the download -> (extract) -> upload pipeline."""

import os
import shutil
from asyncio import CancelledError, Semaphore, get_running_loop, wait_for
from asyncio import TimeoutError as AsyncTimeout
from contextlib import suppress

from . import LOGGER
from . import engines, http_dl, ytdl
from encoder import engine as encoder_engine, is_video
from .archive import PasswordRequired, extract, is_archive
from .config import Config
from .task import Cancelled
from .uploader import UploadError, collect_files, upload_all


class Manager:
    def __init__(self):
        self.tasks = {}
        self._sem = None

    @property
    def sem(self):
        if self._sem is None:
            self._sem = Semaphore(Config.MAX_CONCURRENT_TASKS)
        return self._sem

    def add(self, task):
        self.tasks[task.tid] = task

    def remove(self, task):
        self.tasks.pop(task.tid, None)

    def get(self, tid):
        return self.tasks.get(tid)

    def by_chat(self, chat_id):
        return [t for t in self.tasks.values() if t.chat_id == chat_id]


MANAGER = Manager()


def free_bytes():
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
    return shutil.disk_usage(Config.DOWNLOAD_DIR).free


def ensure_disk(required=0):
    free = free_bytes()
    minimum = int(Config.MIN_FREE_DISK_GB * 1024**3)
    if free < minimum or (required and free < required * 1.15 + minimum // 2):
        raise RuntimeError("Not enough free disk space for this task.")


async def _acquire(client, task, dest):
    """Download the source; returns the main downloaded path."""
    task.set_status("Download")
    if task.mode == "ytdl":
        path, _ = await ytdl.download(
            task.link, dest, task, quality=task.flags.get("quality"), audio=bool(task.flags.get("audio"))
        )
        return path
    if task.mode == "telegram":
        task.engine = engines.telegram()
        media_msg = task.message.reply_to_message
        if not (media_msg and (media_msg.video or media_msg.document or media_msg.audio or media_msg.animation)):
            media_msg = task.message

        async def progress(cur, total):
            task.check_cancel()
            task.update(cur, total)

        path = await client.download_media(media_msg, file_name=dest + os.sep, progress=progress)
        if not path:
            raise RuntimeError("Could not download the Telegram file.")
        task.name = task.name or os.path.basename(path)
        return path
    task.engine = engines.direct()
    return await http_dl.fetch(task.link, dest, task, headers=task.flags.get("headers"), out_name=task.flags.get("name"))


async def _extract_with_prompt(client, task, notify, path, dest):
    """Extract, asking the user for the archive password when Telegram must."""
    attempts = 0
    while True:
        try:
            return await extract(path, dest, task, task.flags.get("password"))
        except PasswordRequired:
            attempts += 1
            if attempts > 3:
                raise RuntimeError("Wrong archive password (3 attempts).")
            task.set_status("Password")
            future = get_running_loop().create_future()
            task.password_wait = future
            try:
                await notify(task, "password", attempts)
                try:
                    password = await wait_for(future, timeout=600)
                except AsyncTimeout as e:
                    raise RuntimeError("No password was provided within 10 minutes.") from e
            finally:
                task.password_wait = None
            if not password:
                raise Cancelled()
            task.flags["password"] = str(password)
            task.set_status("Extract")


async def run_task(client, task, notify):
    """notify(task, text, buttons) sends a message; handles errors itself."""
    dest = os.path.join(Config.DOWNLOAD_DIR, task.tid)
    task.path = dest
    MANAGER.add(task)
    try:
        async with MANAGER.sem:
            task.check_cancel()
            ensure_disk()
            os.makedirs(dest, exist_ok=True)
            main_path = await _acquire(client, task, dest)
            task.check_cancel()
            # Extraction is opt-in: only "-e" turns it on. Without it a zip/rar is uploaded as-is.
            if task.flags.get("extract") and is_archive(main_path):
                task.set_status("Extract")
                task.reset_progress()
                task.engine = engines.sevenzip()
                out_dir = os.path.join(dest, "extracted")
                if not await _extract_with_prompt(client, task, notify, main_path, out_dir):
                    raise RuntimeError("Could not extract the archive (install 7-Zip for RAR/AES archives).")
                with suppress(OSError):
                    os.remove(main_path)
                task.check_cancel()
            elif task.flags.get("extract"):
                LOGGER.info(f"task {task.tid}: -e given but {os.path.basename(main_path)} is not an archive")
            else:
                LOGGER.info(f"task {task.tid}: extraction off (no -e)")

            encode_settings = task.flags.get("encode")
            if encode_settings:
                target_videos = [f for f in collect_files(dest) if is_video(f)]
                if target_videos:
                    task.set_status("Convert")
                    task.engine = engines.ffmpeg()
                    for v_path in target_videos:
                        task.check_cancel()
                        task.reset_progress()
                        out_name = encoder_engine.output_name(v_path) + "." + str(encode_settings.get("container") or "mp4")
                        out_path = os.path.join(os.path.dirname(v_path), "enc_" + out_name)
                        await encoder_engine.encode(v_path, out_path, encode_settings, task)
                        with suppress(OSError):
                            os.remove(v_path)
                        final_path = os.path.join(os.path.dirname(v_path), out_name)
                        if not os.path.exists(final_path):
                            with suppress(OSError):
                                os.rename(out_path, final_path)
                    task.check_cancel()
                else:
                    LOGGER.info(f"task {task.tid}: encode requested but no video found")
            files = collect_files(dest)
            if not files:
                raise RuntimeError("No file was produced.")
            limit = int(Config.MAX_FILE_SIZE_GB * 1024**3)
            total_size = sum(os.path.getsize(f) for f in files)
            if limit and total_size > limit:
                raise RuntimeError(f"File is larger than the allowed {Config.MAX_FILE_SIZE_GB:g} GB.")
            task.total = total_size
            task.files_total = len(files)
            task.name = task.name or os.path.basename(main_path)
            # hand straight over to the uploader: no wait for the next status tick
            task.reset_progress(total_size)
            sent = await upload_all(client, task, files, dest)
            elapsed = task.elapsed()
        await notify(task, "done", (sent, elapsed))
    except (Cancelled, CancelledError):
        LOGGER.info(f"task {task.tid} cancelled")
        await notify(task, "cancelled", None)
    except (http_dl.DownloadError, ytdl.YtdlError, UploadError, RuntimeError) as e:
        LOGGER.warning(f"task {task.tid} failed: {e}")
        await notify(task, "error", str(e))
    except Exception as e:  # noqa: BLE001
        LOGGER.exception(f"task {task.tid} crashed")
        await notify(task, "error", f"{type(e).__name__}: {e}")
    finally:
        MANAGER.remove(task)
        shutil.rmtree(dest, ignore_errors=True)  # automatic cleanup after success, failure and cancel
