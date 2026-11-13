"""Telegram front-end: commands, status board and start-up."""

import asyncio
import os
import re
import sys
import time
from asyncio import create_task, sleep
from contextlib import suppress
from uuid import uuid4

from pyrogram import Client, enums, filters, idle
from pyrogram.errors import FloodWait
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import BotCommand, ReplyParameters

from . import LOGGER, VERSION, store
from .buttons import btn, markup
from .config import Config, id_list, load
from .fmt import (
    cancelled_text,
    clip,
    done_text,
    esc,
    failure_text,
    help_text,
    overview_text,
    ping_text,
    probe_text,
    quality_label,
    quality_text,
    readable_size,
    sc,
    start_text,
    stats_text,
    status_text,
    title,
    visible_tasks,
)
from .pipeline import MANAGER, run_task
from .task import Task
from .ytdl import YtdlError, probe

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

MAX_LINKS_PER_MESSAGE = 10


def RP(message):
    return ReplyParameters(message_id=message.id)


async def _delete_later(message, ttl):
    await sleep(ttl)
    with suppress(Exception):
        await message.delete()


def autodelete(message, ttl=None):
    """Delete a bot message after its lifetime; all failures are silently ignored."""
    if message and Config.AUTO_DELETE_MESSAGES:
        ttl = Config.INFO_MESSAGE_TTL if ttl is None else ttl
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            ttl = 0
        if ttl > 0:
            create_task(_delete_later(message, ttl))
    return message


FLAGS_WITH_VALUE = {"-n", "-q", "-p"}
FLAGS_BOOL = {"-e", "-d", "-a"}


# ---------------------------------------------------------------- helpers
def parse_args(text):
    """-> (positional tokens, flags dict). -n takes everything up to the next flag."""
    tokens = (text or "").split()[1:]
    positional, flags, i = [], {}, 0
    while i < len(tokens):
        token = tokens[i]
        key = token.lower()
        if key in FLAGS_BOOL:
            flags[key] = True
        elif key in FLAGS_WITH_VALUE:
            value = []
            i += 1
            while i < len(tokens) and tokens[i].lower() not in FLAGS_WITH_VALUE | FLAGS_BOOL:
                if key == "-n" and (URL_RE.match(tokens[i]) or tokens[i].startswith("/")):
                    break  # a link or the next /command belongs to the task, not the name
                value.append(tokens[i])
                if key != "-n":
                    i += 1
                    break
                i += 1
            flags[key] = " ".join(value)
            continue
        else:
            positional.append(token)
        i += 1
    return positional, flags


def all_urls(text):
    """Every link in a message, in order (trailing punctuation trimmed). Repeated links stay
    repeated on purpose: each one the user sends becomes its own task."""
    found = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;!?)]}'\"")
        if url:
            found.append(url)
    return found


def is_authorized(message):
    user_id = message.from_user.id if message.from_user else 0
    owner = Config.OWNER_ID
    if user_id and (user_id == owner or user_id in id_list(Config.SUDO_USERS) or user_id in store.get_ids("sudo")):
        return True
    banned = store.get_ids("banned")
    if (user_id and user_id in banned) or message.chat.id in banned:
        return False
    if user_id and user_id in store.get_ids("premium"):
        return True
    allowed = id_list(Config.AUTHORIZED_CHATS) | store.get_ids("authorized")
    return message.chat.id in allowed or (user_id in allowed)


def is_owner(message):
    uid = message.from_user.id if message.from_user else 0
    return bool(uid) and (uid == Config.OWNER_ID or uid in id_list(Config.SUDO_USERS))


def guarded(func):
    async def wrapper(client, message):
        if not is_authorized(message):
            return
        try:
            await func(client, message)
        except Exception:  # noqa: BLE001
            LOGGER.exception(f"handler {func.__name__} failed")
    wrapper.__name__ = func.__name__
    return wrapper


def owner_only(func):
    async def wrapper(client, message):
        if not is_owner(message):
            return
        try:
            await func(client, message)
        except Exception:  # noqa: BLE001
            LOGGER.exception(f"handler {func.__name__} failed")
    wrapper.__name__ = func.__name__
    return wrapper


def _cb_allowed(query):
    uid = query.from_user.id if query.from_user else 0
    chat_id = query.message.chat.id if query.message else 0
    if uid == Config.OWNER_ID or uid in id_list(Config.SUDO_USERS) or uid in store.get_ids("sudo"):
        return True
    banned = store.get_ids("banned")
    if (uid and uid in banned) or chat_id in banned:
        return False
    if uid and uid in store.get_ids("premium"):
        return True
    allowed = id_list(Config.AUTHORIZED_CHATS) | store.get_ids("authorized")
    return uid in allowed or chat_id in allowed


def help_markup(section="home"):
    if section == "home":
        return markup(
            [btn("🔗 Leech", "help:leech", "PRIMARY"), btn("🎬 YT-DLP", "help:ytdl", "PRIMARY")],
            [btn("📊 Control", "help:status", "SUCCESS"), btn("🛠 Tools", "help:tools", "PRIMARY")],
        )
    if section == "leech":
        return markup([btn("🎬 YT-DLP", "help:ytdl", "PRIMARY"), btn("🏠 Home", "help:home", "PRIMARY")])
    if section == "ytdl":
        return markup([btn("🔗 Leech", "help:leech", "PRIMARY"), btn("🏠 Home", "help:home", "PRIMARY")])
    if section == "status":
        return markup([btn("🛠 Tools", "help:tools", "PRIMARY"), btn("🏠 Home", "help:home", "PRIMARY")])
    return markup([btn("📊 Control", "help:status", "PRIMARY"), btn("🏠 Home", "help:home", "PRIMARY")])


def stats_markup(chat_id):
    return markup(
        [btn("🔄 Refresh", f"stats:{chat_id}", "SUCCESS"), btn("🏠 Home", "help:home", "PRIMARY")]
    )


# ---------------------------------------------------------------- status board
class StatusBoard:
    def __init__(self):
        self.loops = {}
        self.page = {}
        self.manual = {}
        self.last_edit = {}

    def ensure(self, client, chat_id):
        loop = self.loops.get(chat_id)
        if not loop or loop.done():
            self.page.setdefault(chat_id, 1)
            self.manual[chat_id] = asyncio.Event()
            self.loops[chat_id] = create_task(self._run(client, chat_id))

    def poke(self, chat_id):
        """Manual redraw request (button press only)."""
        ev = self.manual.get(chat_id)
        if ev is not None:
            ev.set()

    async def restart(self, client, chat_id):
        """Drop the previous board and draw a fresh one, so a new task gets a clear new bar."""
        loop = self.loops.get(chat_id)
        if loop and not loop.done():
            loop.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await loop
        self.page[chat_id] = 1
        self.manual[chat_id] = asyncio.Event()
        self.loops[chat_id] = create_task(self._run(client, chat_id))

    async def _run(self, client, chat_id):
        msg = None
        ev = self.manual.setdefault(chat_id, asyncio.Event())
        interval = max(3, int(Config.STATUS_UPDATE_INTERVAL))
        try:
            while True:
                tasks = MANAGER.by_chat(chat_id)
                if not tasks:
                    break
                # Hard guard: never edit faster than the configured interval, even if a
                # progress hook or a button tried to wake the board early.
                elapsed = time.time() - self.last_edit.get(chat_id, 0.0)
                if elapsed < interval:
                    ev.clear()
                    try:
                        await asyncio.wait_for(ev.wait(), timeout=interval - elapsed)
                    except asyncio.TimeoutError:
                        pass
                    continue
                text, pages = status_text(tasks, Config.DOWNLOAD_DIR, self.page.get(chat_id, 1))
                visible, page, _, _ = visible_tasks(tasks, self.page.get(chat_id, 1))
                self.page[chat_id] = page
                header = [
                    btn("📊 Overview", f"sb:{chat_id}:ov", "PRIMARY"),
                    btn("🔄 Refresh", f"sb:{chat_id}:ref", "SUCCESS"),
                ]
                nav = (
                    [btn("◀", f"sb:{chat_id}:pre", "PRIMARY"), btn(f"{page}/{pages}", "sb:noop", "SUCCESS"),
                     btn("▶", f"sb:{chat_id}:nex", "PRIMARY")]
                    if pages > 1
                    else []
                )
                stops = [btn(f"⛔ {i}", f"cx:{t.tid}", "DANGER") for i, t in enumerate(visible, 1)]
                keyboard = markup(header, nav, stops)
                try:
                    if msg is None:
                        msg = await client.send_message(chat_id, text, reply_markup=keyboard, disable_web_page_preview=True)
                    else:
                        await msg.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
                    self.last_edit[chat_id] = time.time()
                except FloodWait as e:
                    await sleep(e.value + 1)
                except Exception as e:  # noqa: BLE001 (message not modified / deleted)
                    self.last_edit[chat_id] = time.time()
                    if "not modified" not in str(e).lower() and "MESSAGE_NOT_MODIFIED" not in str(e).upper():
                        LOGGER.debug(f"status update: {e}")
                ev.clear()
                try:
                    await asyncio.wait_for(ev.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            if msg is not None:
                try:
                    await msg.delete()
                except Exception:  # noqa: BLE001
                    pass


async def cb_status(client, query):
    data = (query.data or "").split(":")
    if len(data) < 2:
        return
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    if query.message and query.message.chat.type == enums.ChatType.PRIVATE:
        await query.answer("📊 Progress boards are group-only.", show_alert=True)
        return
    if data[1] == "noop":
        await query.answer()
        return
    if len(data) < 3:
        await query.answer()
        return
    try:
        chat_id, action = int(data[1]), data[2]
    except ValueError:
        return
    if action == "ov":
        await query.answer(overview_text(MANAGER.by_chat(chat_id)), show_alert=True)
        return
    if action in ("nex", "pre"):
        BOARD.page[chat_id] = BOARD.page.get(chat_id, 1) + (1 if action == "nex" else -1)
    if action == "ref":
        await query.answer("🔄 Refreshed")
    elif action == "noop":
        await query.answer()
    else:
        await query.answer()
    BOARD.poke(chat_id)


def _admin_uid(uid):
    return bool(uid) and (uid == Config.OWNER_ID or uid in id_list(Config.SUDO_USERS) or uid in store.get_ids("sudo"))


async def cb_cancel(client, query):
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    tid = (query.data or "").split(":", 1)[-1]
    task = MANAGER.get(tid)
    if not task:
        await query.answer("✅ That task has already finished.", show_alert=True)
        return
    uid = query.from_user.id if query.from_user else 0
    if uid != task.user_id and not _admin_uid(uid):
        await query.answer("🔒 Only the task owner can stop it.", show_alert=True)
        return
    task.cancel()
    await query.answer("⛔ Stopping…")


async def cb_help(client, query):
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    section = (query.data or "").split(":", 1)[-1] or "home"
    if section not in ("home", "leech", "ytdl", "status", "tools"):
        section = "home"
    try:
        await query.message.edit_text(help_text(section), reply_markup=help_markup(section))
    except Exception as e:  # noqa: BLE001
        if "not modified" not in str(e).lower():
            LOGGER.debug(f"help screen update: {e}")
    await query.answer()


async def cb_stats(client, query):
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    text = stats_text(Config.DOWNLOAD_DIR, len(MANAGER.tasks))
    keyboard = stats_markup(query.message.chat.id if query.message else 0)
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except Exception as e:  # noqa: BLE001
        if "not modified" not in str(e).lower():
            LOGGER.debug(f"stats update: {e}")
    await query.answer("🔄 Updated")


async def cb_ping(client, query):
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    started = time.time()
    await query.answer()
    latency = (time.time() - started) * 1000
    try:
        await query.message.edit_text(
            ping_text(latency),
            reply_markup=markup([btn("🔙 Back", "help:home", "PRIMARY")]),
        )
    except Exception as e:  # noqa: BLE001
        if "not modified" not in str(e).lower():
            LOGGER.debug(f"ping update: {e}")


async def cb_quality(client, query):
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        await query.answer()
        return
    _, token, value = parts
    entry = QUALITY_WAIT.pop(token, None)
    if not entry or time.time() - entry["created"] > QUALITY_TTL:
        await query.answer("⌛ This quality menu has expired — send /yl again.", show_alert=True)
        return
    uid = query.from_user.id if query.from_user else 0
    if uid != entry["user_id"] and not _admin_uid(uid):
        QUALITY_WAIT[token] = entry  # not yours: keep it for the real owner
        await query.answer("🔒 This menu belongs to another user.", show_alert=True)
        return
    if value == "cancel":
        with suppress(Exception):
            await query.message.delete()
        await query.answer("Cancelled")
        return
    heights = {str(h) for h in entry.get("heights", [])}
    if value == "audio" and not entry.get("audio", True):
        QUALITY_WAIT[token] = entry
        await query.answer("🎵 This link has no separate audio stream.", show_alert=True)
        return
    if value not in heights and value not in ("audio", "best"):
        QUALITY_WAIT[token] = entry
        await query.answer("🚫 That quality is not available for this link.", show_alert=True)
        return
    flags = dict(entry["flags"])
    if value == "audio":
        flags["audio"] = True
    elif value != "best":
        flags["quality"] = value
    real = {str(h) for h in entry.get("real", [])}
    if value not in ("audio", "best") and value not in real:
        await query.answer(f"⚙️ {quality_label(value)} · converting with FFmpeg")
    else:
        label = "audio only" if flags["audio"] else ("best available" if value == "best" else quality_label(value))
        await query.answer(f"⚡ Starting · {label}")
    with suppress(Exception):
        await query.message.delete()
    await start_tasks(client, entry["message"], [("ytdl", link) for link in entry["links"]], flags)


async def on_password(client, message):
    """Take the next plain message from a user whose archive is waiting for a password."""
    uid = message.from_user.id if message.from_user else 0
    task = PASSWORD_WAIT.get(uid)
    future = getattr(task, "password_wait", None) if task else None
    if not task or future is None or future.done():
        PASSWORD_WAIT.pop(uid, None)
        return False
    password = (message.text or "").strip()
    if not password:
        return False
    PASSWORD_WAIT.pop(uid, None)
    future.set_result(password)
    with suppress(Exception):
        await message.delete()  # keep the password out of the chat history when the bot is admin
    card = await client.send_message(
        message.chat.id,
        f"{title('🔓', 'password received', 'extracting the archive …')}",
        disable_web_page_preview=True,
    )
    _task_extras(task).append(card)
    autodelete(card, Config.INFO_MESSAGE_TTL)
    return True


BOARD = StatusBoard()

GROUP_ONLY = (
    f"{title('👥', 'group only', 'transfers start in a group · files arrive here')}\n"
    "<blockquote>"
    "1️⃣ <i>Add me to your group</i>\n"
    "2️⃣ <i>Send</i> <code>/l &lt;link&gt;</code> <i>or</i> <code>/yl &lt;link&gt;</code>\n"
    "3️⃣ <i>Follow the live board in that group</i>\n"
    "📬 <i>the finished file arrives in this private chat</i>"
    "</blockquote>"
)


def _is_private(message):
    return message.chat.type == enums.ChatType.PRIVATE


PASSWORD_WAIT = {}  # user id -> Task waiting for an archive password
COMMAND_REFS = {}  # (chat_id, message_id) -> tasks still sharing that command message
QUALITY_WAIT = {}  # token -> pending quality picker for /yl
QUALITY_TTL = 900  # seconds a quality picker stays valid

def quality_markup(token, heights, sizes=None, audio=True, real=None):
    """Buttons for the offered heights; converted ones carry a ⚙️ marker."""
    sizes = sizes or {}
    real = {int(h) for h in (real if real is not None else heights)}
    cells = []
    for height in sorted(heights, reverse=True):
        label = quality_label(height)
        size = sizes.get(height) or 0
        if size:
            label = f"{label} · {readable_size(size)}"
        if int(height) not in real:
            label = f"⚙️ {label}"
        cells.append((label, str(height), "SUCCESS"))
    if audio:
        cells.append(("🎵 Audio", "audio", "SUCCESS"))
    per_row = 3 if not sizes else 2
    rows = [cells[i:i + per_row] for i in range(0, len(cells), per_row)]
    rows.append([("⭐ Best", "best", "SUCCESS"), ("⛔ Cancel", "cancel", "DANGER")])
    return markup(
        *[[btn(label, f"qy:{token}:{value}", style) for label, value, style in row] for row in rows]
    )


def _quality_cleanup():
    now = time.time()
    for token, entry in list(QUALITY_WAIT.items()):
        if now - entry["created"] > QUALITY_TTL:
            QUALITY_WAIT.pop(token, None)


def _drop_password_wait(task):
    if PASSWORD_WAIT.get(task.user_id) is task:
        PASSWORD_WAIT.pop(task.user_id, None)


# ---------------------------------------------------------------- notifications
def _files_block(sent):
    rows = []
    for index, (name, link) in enumerate(sent, 1):
        rows.append(f"{index}. <a href='{esc(link)}'>{esc(name)}</a>")
        if index >= 30:
            rows.append(f"<i>… and {len(sent) - index} more</i>")
            break
    return "\n\n<b>📂 " + sc("files") + "</b>\n<blockquote>" + "\n".join(rows) + "</blockquote>"


async def _reply(client, message, text, keyboard=None):
    """Reply to the command; if that message was deleted, send a plain message instead."""
    try:
        return await message.reply_text(
            text, reply_markup=keyboard, reply_parameters=RP(message), disable_web_page_preview=True
        )
    except Exception:  # noqa: BLE001
        return await client.send_message(message.chat.id, text, reply_markup=keyboard, disable_web_page_preview=True)


def _task_extras(task):
    extras = getattr(task, "extra_messages", None)
    if extras is None:
        extras = task.extra_messages = []
    return extras


async def _clear_task_messages(client, task):
    """Remove the password card and the command message once the task is over."""
    if Config.AUTO_DELETE_MESSAGES:
        extras = list(_task_extras(task))
        _task_extras(task).clear()
        for message in extras:
            with suppress(Exception):
                await message.delete()
    if Config.CLEAN_USER_MESSAGES:
        key = (task.chat_id, getattr(task.message, "id", 0))
        left = COMMAND_REFS.get(key, 1) - 1
        if left > 0:
            COMMAND_REFS[key] = left
        else:
            COMMAND_REFS.pop(key, None)
            message_id = getattr(task.message, "id", 0)
            try:
                await task.message.delete()
            except Exception as first:  # noqa: BLE001
                if message_id and client is not None:
                    try:
                        await client.delete_messages(task.chat_id, message_id)
                    except Exception as second:  # noqa: BLE001
                        LOGGER.info(
                            f"task {task.tid}: command message not deleted "
                            f"({type(second).__name__}); give the bot delete permission"
                        )
                elif "not found" not in str(first).lower():
                    LOGGER.debug(f"task {task.tid}: command message not deleted: {first}")


async def notify(task, event, payload):
    client = task.message._client
    reply = task.message
    if event != "password":
        _drop_password_wait(task)
    try:
        if event == "done":
            sent, elapsed = payload
            body = done_text(task, len(sent), elapsed) + _files_block(sent)
            in_group = task.chat_id < 0 and task.chat_id != task.user_id
            if in_group and Config.LEECH_TO_PM:
                me = await client.get_me()
                button = markup([btn("📥 Open in Bot PM", url=f"https://t.me/{me.username}", style="PRIMARY")])
                # the files themselves were already uploaded to the user's private chat
                await _clear_task_messages(client, task)
                card = await _reply(
                    client, reply, body + "\n\n<i>📬 Files delivered to your private chat.</i>", button
                )
            else:
                await _clear_task_messages(client, task)
                card = await _reply(client, reply, clip(body, 4000))
            autodelete(card, Config.RESULT_MESSAGE_TTL)
        elif event == "password":
            attempts = int(payload or 1)
            retry = "" if attempts <= 1 else f"  ·  <i>attempt {attempts}/3</i>"
            PASSWORD_WAIT[task.user_id] = task
            card = await _reply(
                client,
                reply,
                f"{title('🔐', 'password required', esc(task.display_name()))}\n"
                "<blockquote>"
                "<i>Send the archive password in this chat.</i>\n"
                f"⏳ <b>Waiting</b>  <i>up to 10 minutes · task</i> <code>{task.tid}</code>{retry}"
                "</blockquote>",
                markup([btn("⛔ Stop task", f"cx:{task.tid}", "DANGER")]),
            )
            if card is not None:
                _task_extras(task).append(card)
        elif event == "cancelled":
            await _clear_task_messages(client, task)
            card = await _reply(client, reply, cancelled_text(task))
            autodelete(card, Config.RESULT_MESSAGE_TTL)
        else:
            await _clear_task_messages(client, task)
            card = await _reply(client, reply, failure_text(task, payload))
            autodelete(card, Config.RESULT_MESSAGE_TTL)
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"notify failed: {e}")


# ---------------------------------------------------------------- commands
def _spawn(client, message, mode, flags, link):
    task = Task(message, link, mode, flags)
    MANAGER.add(task)  # visible on the new board immediately, before the pipeline starts
    task.asyncio_task = create_task(run_task(client, task, notify))
    return task


async def start_tasks(client, message, jobs, flags):
    """Start one task per (mode, link); the board is restarted only once."""
    jobs = jobs[:MAX_LINKS_PER_MESSAGE]
    if not jobs:
        return []
    tasks = [_spawn(client, message, mode, flags, link) for mode, link in jobs]
    chat_id = message.chat.id  # Message has no chat_id attribute in this Pyrogram build
    if len(tasks) > 1:
        key = (chat_id, getattr(message, "id", 0))
        COMMAND_REFS[key] = COMMAND_REFS.get(key, 0) + len(tasks)
    await BOARD.restart(client, chat_id)
    return tasks


def _flags_from(raw):
    return {
        "name": raw.get("-n") or None,
        "extract": raw.get("-e") is True,  # extraction is opt-in: only when -e is written
        "doc": bool(raw.get("-d")),
        "password": raw.get("-p") or None,
        "audio": bool(raw.get("-a")),
        "quality": raw.get("-q") or None,
    }


@guarded
async def cmd_leech(client, message):
    if _is_private(message):
        sent = await message.reply_text(
            GROUP_ONLY,
            reply_markup=markup([btn("📖 Command centre", "help:home", "PRIMARY")]),
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    text = message.text or message.caption or ""
    _, raw = parse_args(text)
    flags = _flags_from(raw)
    reply = message.reply_to_message
    links = all_urls(text)
    if not links and reply:
        links = all_urls(reply.text or reply.caption or "")
    if links:
        from .ytdl import is_video_link

        jobs = [("ytdl" if is_video_link(link) else "direct", link) for link in links]
        await start_tasks(client, message, jobs, flags)
        return
    if reply and (reply.document or reply.video or reply.audio or reply.photo or reply.animation or reply.voice):
        await start_tasks(client, message, [("telegram", "")], flags)
        return
    sent = await message.reply_text(
        f"{title('🔗', 'leech', 'send a link, or reply to a file')}\n"
        "<blockquote>"
        "<b>Direct download</b>\n"
        "<code>/l https://…</code>\n"
        "<i>uploaded exactly as downloaded</i>\n"
        "\n"
        "<b>Extract an archive</b>\n"
        "<code>/l https://… -e</code>\n"
        "<i>download → extract → upload</i>"
        "</blockquote>\n"
        "💡 <i>Without</i> <code>-e</code> <i>a zip/rar is uploaded unchanged.</i>",
        reply_markup=markup([btn("📖 Leech guide", "help:leech", "PRIMARY"), btn("🏠 Command centre", "help:home", "PRIMARY")]),
        reply_parameters=RP(message),
    )
    autodelete(sent)


@guarded
async def cmd_ytdl(client, message):
    if _is_private(message):
        sent = await message.reply_text(
            GROUP_ONLY,
            reply_markup=markup([btn("📖 Command centre", "help:home", "PRIMARY")]),
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    text = message.text or ""
    _, raw = parse_args(text)
    flags = _flags_from(raw)
    links = all_urls(text)
    if not links and message.reply_to_message:
        links = all_urls(message.reply_to_message.text or message.reply_to_message.caption or "")
    links = links[:MAX_LINKS_PER_MESSAGE]
    if not links:
        sent = await message.reply_text(
            f"{title('🎬', 'yt-dlp', 'send a video or stream link')}\n"
            "<blockquote>"
            "<code>/yl https://youtu.be/…</code>\n"
            "<code>/yl https://site.com/stream.m3u8</code>"
            "</blockquote>\n"
            "<blockquote>"
            "🎚 <b>Flags</b>  <code>-q 720</code>  ·  <code>-a</code>  ·  <code>-n name</code>\n"
            "🍪 <b>Cookies</b>  <code>/cookies</code>"
            "</blockquote>\n"
            "💡 <i>Several links in one message become separate tasks.</i>",
            reply_markup=markup([btn("🎬 YT-DLP guide", "help:ytdl", "PRIMARY"), btn("🏠 Command centre", "help:home", "PRIMARY")]),
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    if flags["quality"] and not str(flags["quality"]).isdigit():
        sent = await message.reply_text(
            f"{title('🎚', 'quality must be a number')}\n"
            "<blockquote>Example: <code>/yl URL -q 720</code>\n"
            "<i>valid heights: 2160 · 1440 · 1080 · 720 · 480 · 360</i></blockquote>",
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    if flags["audio"] or flags["quality"]:
        await start_tasks(client, message, [("ytdl", link) for link in links], flags)
        return
    _quality_cleanup()
    token = uuid4().hex[:8]
    uid = message.from_user.id if message.from_user else message.chat.id
    card = await message.reply_text(probe_text(len(links)), reply_parameters=RP(message))
    autodelete(card, 300)
    try:
        results = await asyncio.gather(*(probe(link) for link in links))
    except YtdlError as e:
        with suppress(Exception):
            await card.edit_text(
                f"{title('🚫', 'formats not available', esc(str(e)[:200]))}\n"
                "💡 <i>Send the link again, or check</i> <code>/cookies</code> <i>for private videos.</i>",
                reply_markup=markup([btn("🎬 YT-DLP guide", "help:ytdl", "PRIMARY")]),
            )
        return
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"format probe failed: {e}")
        with suppress(Exception):
            await card.edit_text(
                f"{title('🚫', 'formats not available', 'the site did not return its format list')}\n"
                "💡 <i>Try the link again in a moment.</i>",
                reply_markup=markup([btn("🎬 YT-DLP guide", "help:ytdl", "PRIMARY")]),
            )
        return
    real = set(results[0]["heights"])
    for info in results[1:]:
        real &= set(info["heights"])
    audio_ok = all(info["audio"] for info in results)
    sizes = dict(results[0]["heights"]) if len(links) == 1 else {}
    from .ytdl import menu_heights

    offered = menu_heights(real)
    QUALITY_WAIT[token] = {
        "message": message,
        "links": links,
        "flags": dict(flags),
        "user_id": uid,
        "created": time.time(),
        "heights": offered,
        "real": sorted(real),
        "audio": audio_ok,
    }
    try:
        await card.edit_text(
            quality_text(len(links), offered, sizes, audio_ok, real),
            reply_markup=quality_markup(token, offered, sizes, audio_ok, real),
        )
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"quality picker could not be drawn: {type(e).__name__}: {e}")


async def cmd_start(client, message):
    if not is_authorized(message):
        uid = message.from_user.id if message.from_user else message.chat.id
        sent = await message.reply_text(
            f"{title('🔒', 'access required', 'this bot is private')}\n"
            f"<blockquote>👤 <b>Your ID</b>  <code>{uid}</code>\n"
            "<i>Ask the owner to authorize this account.</i></blockquote>",
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    name = message.from_user.first_name if message.from_user else "there"
    keyboard = markup(
        [btn("🔗 Leech", "help:leech", "PRIMARY"), btn("🎬 YT-DLP", "help:ytdl", "PRIMARY"), btn("📖 Guide", "help:home", "PRIMARY")],
        [btn("📈 Stats", f"stats:{message.chat.id}", "SUCCESS"), btn("🛠 Tools", "help:tools", "PRIMARY"), btn("🏓 Ping", "ping:start", "SUCCESS")],
    )
    sent = await message.reply_text(start_text(name), reply_markup=keyboard, reply_parameters=RP(message))
    autodelete(sent, Config.START_MESSAGE_TTL)


@guarded
async def cmd_cookies(client, message):
    from .ytdl import cookies_state

    path, ready = cookies_state()
    status = "✅ loaded" if ready else "⚪ empty"
    sent = await message.reply_text(
        f"{title('🍪', 'yt-dlp cookies', 'used for private or age-restricted videos')}\n"
        "<blockquote>"
        f"📄 <b>File</b>\n<code>{esc(path or 'not configured')}</code>\n"
        f"📌 <b>Status</b>  <i>{status}</i>\n"
        "🧾 <b>Format</b>  <i>Netscape cookies.txt</i>"
        "</blockquote>\n"
        "💡 <i>Paste the cookie lines into that file, save it, then restart the bot.</i>",
        reply_parameters=RP(message),
    )
    autodelete(sent)


COMMAND_MENU = [
    ("leech", "Leech a direct link or a Telegram file"),
    ("ytdlleech", "Leech YouTube / HLS / any yt-dlp link"),
    ("encode", "Encode with your saved settings"),
    ("360p", "Encode at 360p"),
    ("480p", "Encode at 480p"),
    ("560p", "Encode at 560p"),
    ("720p", "Encode at 720p"),
    ("1080p", "Encode at 1080p"),
    ("1440p", "Encode at 1440p"),
    ("4k", "Encode at 4K (2160p)"),
    ("264h", "Encoder codec: H.264"),
    ("265h", "Encoder codec: H.265"),
    ("settings", "Show encoder settings"),
    ("reset", "Reset encoder settings"),
    ("synccommands", "Owner: resync the Telegram command menu"),
    ("status", "Live progress board"),
    ("cancel", "Stop a running task"),
    ("stats", "Bot and server statistics"),
    ("cookies", "Where to paste yt-dlp cookies"),
    ("ping", "Check bot latency"),
    ("setthumb", "Save a custom video thumbnail"),
    ("delthumb", "Remove your custom thumbnail"),
    ("help", "Show the command guide"),
    ("restart", "Owner: restart the bot"),
    ("log", "Owner: download the log file"),
    ("authorize", "Owner: grant access to a user or chat"),
    ("unauthorize", "Owner: revoke access"),
    ("ban", "Owner: block a user or chat"),
    ("unban", "Owner: unblock a user or chat"),
    ("premium", "Owner: add, remove or list premium users"),
]


@guarded
async def cmd_help(client, message):
    await message.reply_text(help_text("home"), reply_markup=help_markup("home"), reply_parameters=RP(message))


@guarded
async def cmd_ping(client, message):
    started = time.time()
    sent = await message.reply_text("<b>🏓 Pinging…</b>", reply_parameters=RP(message))
    latency = (time.time() - started) * 1000
    await sent.edit_text(ping_text(latency))
    autodelete(sent)


@guarded
async def cmd_status(client, message):
    if _is_private(message):
        sent = await message.reply_text(
            f"{title('📊', 'status lives in the group', 'progress boards are group-only')}\n"
            "<blockquote>"
            "<i>Send</i> <code>/status</code> <i>in your group to open the live board.</i>\n"
            "📬 <i>this chat only receives the finished files</i>"
            "</blockquote>",
            reply_markup=markup([btn("📖 Command centre", "help:home", "PRIMARY")]),
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    tasks = MANAGER.by_chat(message.chat.id)
    if not tasks:
        await message.reply_text(
            stats_text(Config.DOWNLOAD_DIR, 0),
            reply_markup=stats_markup(message.chat.id),
            reply_parameters=RP(message),
        )
        return
    BOARD.ensure(client, message.chat.id)


@guarded
async def cmd_stats(client, message):
    await message.reply_text(
        stats_text(Config.DOWNLOAD_DIR, len(MANAGER.tasks)),
        reply_markup=stats_markup(message.chat.id),
        reply_parameters=RP(message),
    )


def _cancel(user_msg, tid):
    task = MANAGER.get(tid)
    if not task:
        return None
    uid = user_msg.from_user.id if user_msg.from_user else 0
    if uid != task.user_id and not is_owner(user_msg):
        return False
    task.cancel()
    return True


@guarded
async def cmd_cancel_id(client, message):
    m = re.match(r"^/c_([0-9a-f]{8})", message.text or "")
    await _finish_cancel(message, m.group(1) if m else "")


@guarded
async def cmd_cancel(client, message):
    parts = (message.text or "").split()
    if len(parts) > 1:
        tid = parts[1].lstrip("/")
        if tid.startswith("c_"):
            tid = tid[2:]
        await _finish_cancel(message, tid)
        return
    mine = [
        t
        for t in MANAGER.by_chat(message.chat.id)
        if t.user_id == (message.from_user.id if message.from_user else 0)
    ]
    if len(mine) == 1:
        mine[0].cancel()
        sent = await message.reply_text(
            f"⛔ <b>Stopping</b> <code>{esc(mine[0].display_name())}</code>…", reply_parameters=RP(message)
        )
        autodelete(sent)
        _task_extras(mine[0]).append(sent)
        return
    if not mine:
        sent = await message.reply_text(
            f"{title('🍃', 'nothing to cancel', 'no active task in this chat')}",
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    rows = [
        [btn(f"⛔ {t.display_name()[:28]}", f"cx:{t.tid}", "DANGER")]
        for t in mine[:8]
    ]
    sent = await message.reply_text(
        f"{title('🎛', 'several tasks are running', 'tap the one you want to stop')}",
        reply_markup=markup(*rows),
        reply_parameters=RP(message),
    )
    autodelete(sent)


async def _finish_cancel(message, tid):
    task = MANAGER.get(tid)
    result = _cancel(message, tid)
    if result is None:
        sent = await message.reply_text(
            f"{title('🔎', 'task not found', 'that ID is not running any more')}",
            reply_parameters=RP(message),
        )
    elif result is False:
        sent = await message.reply_text(
            f"{title('🔒', 'not your task', 'only the owner of a task can stop it')}",
            reply_parameters=RP(message),
        )
    else:
        sent = await message.reply_text(
            f"⛔ <b>Stopping</b> <code>{esc(task.display_name())}</code>…", reply_parameters=RP(message)
        )
        _task_extras(task).append(sent)
    autodelete(sent)


@guarded
async def cmd_setthumb(client, message):
    reply = message.reply_to_message
    if not reply or not (reply.photo or (reply.document and (reply.document.mime_type or "").startswith("image/"))):
        sent = await message.reply_text(
            f"{title('🖼', 'set thumbnail', 'reply to a photo with')} <code>/setthumb</code>",
            reply_parameters=RP(message),
        )
        autodelete(sent)
        return
    status = await message.reply_text("🖼 <i>Saving your thumbnail…</i>", reply_parameters=RP(message))
    uid = message.from_user.id if message.from_user else message.chat.id
    target = store.thumb_target(uid)
    tmp = None
    try:
        tmp = await client.download_media(reply, file_name=target + ".src")
        if not tmp or not os.path.isfile(tmp):
            raise ValueError("Telegram did not return the photo")
        from PIL import Image

        with Image.open(tmp) as img:
            img = img.convert("RGB")
            img.thumbnail((320, 320))
            img.save(target, "JPEG", quality=90, optimize=True)
    except Exception as e:  # noqa: BLE001 (unreadable image / disk / network)
        LOGGER.warning(f"thumbnail save failed: {type(e).__name__}: {e}")
        await status.edit_text(
            f"{title('❌', 'thumbnail not saved', 'that file could not be read as an image')}\n"
            "💡 <i>Send a normal photo and reply to it with</i> <code>/setthumb</code>."
        )
        autodelete(status)
        return
    finally:
        if tmp and os.path.isfile(tmp):
            os.remove(tmp)
    await status.edit_text(
        f"{title('🖼', 'thumbnail saved', 'it will be used on your next videos')}"
    )
    autodelete(status)


@guarded
async def cmd_delthumb(client, message):
    uid = message.from_user.id if message.from_user else message.chat.id
    ok = store.delete_user_thumb(uid)
    sent = await message.reply_text(
        f"{title('🗑', 'thumbnail removed')}"
        if ok
        else f"{title('🍃', 'no thumbnail', 'you have not saved one yet')}",
        reply_parameters=RP(message),
    )
    autodelete(sent)


def _target_at(message, index):
    parts = (message.text or "").split()
    if len(parts) > index and parts[index].lstrip("-").isdigit():
        return int(parts[index])
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return message.chat.id


def _target_id(message):
    return _target_at(message, 1)


def _explicit_target(message, index):
    """Answer only with a typed id or a replied-to user (never the current chat)."""
    parts = (message.text or "").split()
    if len(parts) > index and parts[index].lstrip("-").isdigit():
        return int(parts[index])
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return None


async def _say(message, text):
    sent = await message.reply_text(text, reply_parameters=RP(message))
    autodelete(sent)
    return sent


@owner_only
async def cmd_authorize(client, message):
    target = _target_id(message)
    store.remove_id("banned", target)
    store.add_id("authorized", target)
    await _say(
        message,
        f"{title('🔓', 'access granted')}\n<blockquote><code>{target}</code> can use the bot now.</blockquote>",
    )


@owner_only
async def cmd_unauthorize(client, message):
    target = _target_id(message)
    store.remove_id("authorized", target)
    await _say(
        message,
        f"{title('🔒', 'access revoked')}\n<blockquote><code>{target}</code> was removed.</blockquote>",
    )


def _protected(target):
    return target == Config.OWNER_ID or target in id_list(Config.SUDO_USERS)


@owner_only
async def cmd_ban(client, message):
    target = _explicit_target(message, 1)
    if target is None:
        await _say(
            message,
            f"{title('⛔', 'ban a user')}\n"
            "<blockquote><code>/ban 123456789</code>\n"
            "<i>or reply to a user with</i> <code>/ban</code></blockquote>",
        )
        return
    if _protected(target):
        await _say(
            message,
            f"{title('🛡', 'cannot ban an admin', 'the owner and sudo users stay protected')}",
        )
        return
    store.remove_id("authorized", target)
    store.remove_id("premium", target)
    store.add_id("banned", target)
    await _say(
        message,
        f"{title('⛔', 'user banned')}\n<blockquote><code>{target}</code> can no longer use the bot.</blockquote>",
    )


@owner_only
async def cmd_unban(client, message):
    target = _explicit_target(message, 1)
    if target is None:
        await _say(
            message,
            f"{title('🔓', 'unban a user')}\n"
            "<blockquote><code>/unban 123456789</code>\n"
            "<i>or reply to a user with</i> <code>/unban</code></blockquote>",
        )
        return
    store.remove_id("banned", target)
    await _say(
        message,
        f"{title('🔓', 'user unbanned')}\n<blockquote><code>{target}</code> was removed from the ban list.</blockquote>",
    )


def _premium_list_text():
    ids = sorted(store.get_ids("premium"))
    if not ids:
        return f"{title('⭐', 'premium users', 'no premium users yet')}"
    shown = "\n".join(f"<code>{i}</code>" for i in ids[:40])
    extra = f"\n<i>… and {len(ids) - 40} more</i>" if len(ids) > 40 else ""
    return (
        f"{title('⭐', 'premium users', f'{len(ids)} total')}\n"
        f"<blockquote>{shown}{extra}</blockquote>"
    )


async def _premium_change(message, target, add):
    if _protected(target):
        await _say(
            message,
            f"{title('🛡', 'already an admin', 'that user is the owner or a sudo user')}",
        )
        return
    if add:
        store.remove_id("banned", target)
        store.add_id("premium", target)
        await _say(
            message,
            f"{title('⭐', 'premium added')}\n<blockquote><code>{target}</code> can use the bot now.</blockquote>",
        )
    else:
        store.remove_id("premium", target)
        await _say(
            message,
            f"{title('☆', 'premium removed')}\n<blockquote><code>{target}</code> is no longer premium.</blockquote>",
        )


@owner_only
async def cmd_premium(client, message):
    parts = (message.text or "").split()
    action = parts[1].lower() if len(parts) > 1 else "list"
    if action in ("add", "remove", "del", "delete"):
        target = _explicit_target(message, 2)
        if target is None:
            await _say(
                message,
                f"{title('⭐', 'premium users')}\n"
                "<blockquote>"
                "<code>/premium add 123456789</code>\n"
                "<code>/premium remove 123456789</code>\n"
                "<code>/premium list</code>\n"
                "<i>or reply to a user with</i> <code>/premium add</code>"
                "</blockquote>",
            )
            return
        await _premium_change(message, target, action == "add")
        return
    await _say(message, _premium_list_text())


@owner_only
async def cmd_premium_add(client, message):
    target = _explicit_target(message, 1)
    if target is None:
        await _say(
            message,
            f"{title('⭐', 'add premium')}\n"
            "<blockquote><code>/addpremium 123456789</code>\n"
            "<i>or reply to a user with</i> <code>/addpremium</code></blockquote>",
        )
        return
    await _premium_change(message, target, True)


@owner_only
async def cmd_premium_remove(client, message):
    target = _explicit_target(message, 1)
    if target is None:
        await _say(
            message,
            f"{title('☆', 'remove premium')}\n"
            "<blockquote><code>/removepremium 123456789</code>\n"
            "<i>or reply to a user with</i> <code>/removepremium</code></blockquote>",
        )
        return
    await _premium_change(message, target, False)


@owner_only
async def cmd_log(client, message):
    if os.path.isfile("log.txt"):
        await message.reply_document(
            "log.txt", caption=f"{title('📄', 'bot log')}", reply_parameters=RP(message)
        )
    else:
        sent = await message.reply_text(
            f"{title('📄', 'no log', 'log.txt has not been created yet')}",
            reply_parameters=RP(message),
        )
        autodelete(sent)


@owner_only
async def cmd_restart(client, message):
    for task in list(MANAGER.tasks.values()):
        task.cancel()
    await message.reply_text(
        f"{title('♻️', 'restarting', 'the supervisor will bring me back in a moment')}",
        reply_parameters=RP(message),
    )
    await sleep(2)
    os._exit(3)  # the supervisor in main.py starts the bot again


# ---------------------------------------------------------------- start-up
def make_client():
    kwargs = dict(
        api_id=Config.TELEGRAM_API,
        api_hash=Config.TELEGRAM_HASH,
        bot_token=Config.BOT_TOKEN,
        parse_mode=enums.ParseMode.HTML,
        # a saved session means a restart reuses the existing auth key instead of asking
        # Telegram to authorise the bot again (repeated logins hit FLOOD_WAIT for ~40 min)
        workdir=".",
        workers=16,
        sleep_threshold=10,
        app_version=VERSION,
        device_model="RS Leech Lite",
    )
    if Config.TG_PROXY:
        from urllib.parse import urlparse

        p = urlparse(Config.TG_PROXY)
        kwargs["proxy"] = {
            "scheme": p.scheme,
            "hostname": p.hostname,
            "port": p.port,
            "username": p.username,
            "password": p.password,
        }
    from inspect import signature

    if "max_concurrent_transmissions" in signature(Client.__init__).parameters:
        kwargs["max_concurrent_transmissions"] = 16  # parallel upload chunks: faster large files
    return Client(f"rs-leech-{Config.BOT_TOKEN.split(':', 1)[0]}", **kwargs)


def register(client):
    cmd = filters.command
    table = [
        (cmd(["leech", "l"]), cmd_leech),
        (cmd(["ytdlleech", "yl", "ytleech", "ytdl"]), cmd_ytdl),
        (cmd("start"), cmd_start),
        (cmd(["help", "h"]), cmd_help),
        (cmd("ping"), cmd_ping),
        (cmd(["status", "s", "statusall"]), cmd_status),
        (cmd(["stats", "st"]), cmd_stats),
        (cmd("cookies"), cmd_cookies),
        (cmd(["cancel", "c"]), cmd_cancel),
        (filters.regex(r"^/c_[0-9a-f]{8}"), cmd_cancel_id),
        (cmd("setthumb"), cmd_setthumb),
        (cmd("delthumb"), cmd_delthumb),
        (cmd("authorize"), cmd_authorize),
        (cmd("unauthorize"), cmd_unauthorize),
        (cmd("ban"), cmd_ban),
        (cmd("unban"), cmd_unban),
        (cmd("premium"), cmd_premium),
        (cmd("addpremium"), cmd_premium_add),
        (cmd("removepremium"), cmd_premium_remove),
        (cmd("log"), cmd_log),
        (cmd(["restart", "r"]), cmd_restart),
    ]
    for flt, handler in table:
        client.add_handler(MessageHandler(handler, flt))
    client.add_handler(CallbackQueryHandler(cb_status, filters.regex(r"^sb:")))
    client.add_handler(CallbackQueryHandler(cb_help, filters.regex(r"^help:")))
    client.add_handler(CallbackQueryHandler(cb_stats, filters.regex(r"^stats:")))
    client.add_handler(CallbackQueryHandler(cb_ping, filters.regex(r"^ping:")))
    client.add_handler(CallbackQueryHandler(cb_quality, filters.regex(r"^qy:")))
    client.add_handler(CallbackQueryHandler(cb_cancel, filters.regex(r"^cx:")))
    try:
        from .encoder_commands import register_encoder

        register_encoder(client)
    except Exception:  # noqa: BLE001
        LOGGER.exception("encoder command registration failed")
    client.add_handler(
        MessageHandler(on_password, filters.text & ~filters.regex(r"^/")), group=-1
    )


async def sync_commands(client):
    """Register the complete menu with Telegram. -> (ok, detail)."""
    seen, commands = set(), []
    for name, desc in COMMAND_MENU:
        name = str(name).strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        commands.append(BotCommand(name, desc))
    try:
        await client.set_bot_commands(commands)
        return True, f"command menu updated ({len(commands)} commands)"
    except Exception as e:  # noqa: BLE001
        return False, f"could not update the command menu: {e}"


async def amain():
    load()
    problems = [n for n, v in (("BOT_TOKEN", Config.BOT_TOKEN), ("TELEGRAM_API", Config.TELEGRAM_API),
                               ("TELEGRAM_HASH", Config.TELEGRAM_HASH), ("OWNER_ID", Config.OWNER_ID)) if not v]
    if problems:
        LOGGER.error("Missing configuration: " + ", ".join(problems) + " (config.py or environment variables)")
        sys.exit(2)
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
    # leftovers of a previous crash: only this bot's own task folders (8 hex chars) are
    # removed, and only when DOWNLOAD_DIR is a dedicated folder - never the project itself
    import shutil

    project = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    target = os.path.realpath(Config.DOWNLOAD_DIR)
    if target in (project, os.path.realpath(os.sep)):
        LOGGER.warning(f"DOWNLOAD_DIR points at {target}: stale files are left untouched")
    else:
        for entry in os.listdir(Config.DOWNLOAD_DIR):
            full = os.path.join(Config.DOWNLOAD_DIR, entry)
            if re.fullmatch(r"[0-9a-f]{8}", entry) and os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
    client = make_client()
    register(client)
    LOGGER.info(f"RS Leech Lite v{VERSION} · connecting to Telegram …")
    while True:
        try:
            await client.start()
            break
        except FloodWait as e:
            wait = int(getattr(e, "value", 60)) + 5
            LOGGER.warning(f"Telegram login cooldown: retrying in {wait // 60}m {wait % 60}s …")
            try:
                await client.stop()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(wait)
    try:
        import rsbin

        for line in rsbin.report():
            LOGGER.info("tool " + line)
        from encoder import LOGGER as enc_log  # noqa: F401

        LOGGER.info("encoder engine ready (shared bin/ffmpeg)")
    except Exception as e:  # noqa: BLE001
        LOGGER.warning(f"startup tool check failed: {e}")
    me = await client.get_me()
    LOGGER.info(f"RS Leech Lite v{VERSION} started as @{me.username or me.id} (id {me.id})")
    LOGGER.info(f"owner {Config.OWNER_ID} · {Config.MAX_CONCURRENT_TASKS} tasks · {Config.DOWNLOAD_CONNECTIONS} connections")
    from .ytdl import cookies_state

    cookie_file, cookies_ready = cookies_state()
    LOGGER.info(
        "yt-dlp cookies: "
        + (
            f"loaded from {cookie_file}"
            if cookies_ready
            else f"not configured ({cookie_file or 'no path'}) — public links work, add cookies.txt for private/age-locked videos"
        )
    )
    if Config.SET_COMMANDS:  # keeps the Telegram command menu in sync on every start
        ok, detail = await sync_commands(client)
        if ok:
            LOGGER.info(detail)
        else:
            LOGGER.warning(detail)
    try:
        await idle()
    finally:
        await client.stop()


def run():
    asyncio.run(amain())
