"""Encoder commands integrated into the mirror-leech bot.

Every command queues the normal download pipeline and adds one extra stage:
``download -> encode -> upload``.  Settings live per user in ``encoder.settings``.
"""

import os

from pyrogram import filters

from .bot import (
    BOARD,
    MAX_LINKS_PER_MESSAGE,
    _spawn,
    all_urls,
    autodelete,
    guarded,
    parse_args,
    start_tasks,
)
from .buttons import btn, markup
from .fmt import esc, title
from encoder import settings as esettings

QUALITY_COMMANDS = {
    "360p": "360p", "480p": "480p", "560p": "560p", "576p": "576p",
    "720p": "720p", "1080p": "1080p", "1440p": "1440p", "2k": "1440p",
    "2160p": "2160p", "4k": "4k",
}


def _reply_target(message):
    """The message carrying the media (the reply target or the command message itself)."""
    if message.reply_to_message and (
        message.reply_to_message.video or message.reply_to_message.document
        or message.reply_to_message.audio or message.reply_to_message.animation
    ):
        return message.reply_to_message
    if message.video or message.document or message.audio or message.animation:
        return message
    return None


def _flags_for(message, mode, link, encode):
    _, raw = parse_args(message.text or message.caption or "")
    flags = {
        "name": raw.get("-n") or None,
        "extract": raw.get("-e") is True,
        "doc": bool(raw.get("-d")),
        "password": raw.get("-p") or None,
        "audio": bool(raw.get("-a")),
        "quality": raw.get("-q") or None,
        "encode": encode,
    }
    return flags


async def _resolve_jobs(message):
    """(mode, link) pairs for the media/link in this message."""
    from .ytdl import is_video_link

    text = message.text or message.caption or ""
    links = all_urls(text)
    if links:
        return [("ytdl" if is_video_link(link) else "direct", link) for link in links[:MAX_LINKS_PER_MESSAGE]]
    target = _reply_target(message)
    if target is not None:
        return [("telegram", "")]
    return []


@guarded
async def cmd_encode_quality(client, message):
    command = (message.command[0] or "").lower().lstrip("/")
    wanted = QUALITY_COMMANDS.get(command)
    if not wanted:
        return
    jobs = await _resolve_jobs(message)
    if not jobs:
        sent = await message.reply_text(
            f"{title('🎚', 'send a video', 'reply to a video/document or add a link')}\n"
            "<blockquote>"
            f"<code>/{command}</code> &lt;link&gt;\n"
            f"<i>or reply to a video with</i> <code>/{command}</code>"
            "</blockquote>"
        )
        autodelete(sent)
        return
    settings = dict(esettings.get(message.from_user.id))
    settings["resolution"] = wanted  # one-off: does not change the saved default
    tasks = []
    for mode, link in jobs:
        flags = _flags_for(message, mode, link, settings)
        tasks.append(_spawn(client, message, mode, flags, link))
    await BOARD.restart(client, message.chat.id)
    return tasks


@guarded
async def cmd_encode(client, message):
    """`/encode` - encode with the user's saved settings; flags: -r 720p -c h265 -crf 22."""
    args = list(message.command[1:])
    changes = {}
    i = 0
    while i < len(args):
        arg = args[i].lower()
        if arg == "-r" and i + 1 < len(args):
            changes["resolution"] = args[i + 1]
            i += 2
        elif arg == "-c" and i + 1 < len(args):
            changes["codec"] = "h265" if args[i + 1].lower() in ("h265", "hevc", "x265") else "h264"
            i += 2
        elif arg == "-crf" and i + 1 < len(args):
            try:
                changes["crf"] = max(0, min(int(args[i + 1]), 51))
            except ValueError:
                pass
            i += 2
        elif arg == "-preset" and i + 1 < len(args):
            changes["preset"] = args[i + 1]
            i += 2
        elif arg == "-a" and i + 1 < len(args):
            changes["audio_codec"] = args[i + 1]
            i += 2
        else:
            i += 1
    if changes:
        esettings.update(message.from_user.id, **changes)
    jobs = await _resolve_jobs(message)
    if not jobs:
        sent = await message.reply_text(
            f"{title('🎬', 'encoder', 'reply to a video or send a link')}\n"
            "<blockquote>"
            "<code>/encode &lt;link&gt;</code>\n"
            "<code>/encode -r 720p -c h265 -crf 22</code>\n"
            "<i>reply to a video and run /encode</i>"
            "</blockquote>"
        )
        autodelete(sent)
        return
    settings = esettings.get(message.from_user.id)
    for mode, link in jobs:
        flags = _flags_for(message, mode, link, settings)
        _spawn(client, message, mode, flags, link)
    await BOARD.restart(client, message.chat.id)


@guarded
async def cmd_codec(client, message):
    command = (message.command[0] or "").lower().lstrip("/")
    if command == "265h":
        esettings.update(message.from_user.id, codec="h265")
        text = title("🎞", "codec: H.265 (HEVC)", "smaller files, needs a capable player")
    else:
        esettings.update(message.from_user.id, codec="h264", ten_bit=False)
        text = title("🎞", "codec: H.264 (x264)", "maximum compatibility")
    sent = await message.reply_text(text)
    autodelete(sent)


@guarded
async def cmd_enc_settings(client, message):
    s = esettings.get(message.from_user.id)
    rows = [
        ("Codec", str(s["codec"]).upper()),
        ("Preset", str(s["preset"])),
        ("CRF", str(s["crf"])),
        ("Resolution", str(s["resolution"])),
        ("Audio", f"{s['audio_codec']} {s['audio_bitrate']}k"),
        ("Container", str(s["container"])),
    ]
    body = "\n".join(f"{k}: <code>{esc(v)}</code>" for k, v in rows)
    sent = await message.reply_text(
        f"{title('⚙️', 'encoder settings', 'per-user defaults')}\n<blockquote>{body}</blockquote>\n"
        "<i>Change with</i> <code>/encode -r 720p -c h265 -crf 22 -preset fast</code>\n"
        "<i>Reset with</i> <code>/reset</code>",
        reply_markup=markup([btn("♻️ Reset", "enc:reset", "DANGER")]),
    )
    autodelete(sent)


@guarded
async def cmd_enc_reset(client, message):
    esettings.reset(message.from_user.id)
    sent = await message.reply_text(title("♻️", "encoder settings reset", "defaults restored"))
    autodelete(sent)


@guarded
async def cmd_sync_commands(client, message):
    from .bot import COMMAND_MENU, sync_commands

    ok, detail = await sync_commands(client)
    sent = await message.reply_text(
        f"{title('🔄', 'command menu synced' if ok else 'sync failed', detail)}\n"
        f"<blockquote><i>{len(COMMAND_MENU)} commands registered</i></blockquote>"
    )
    autodelete(sent)


async def cb_enc(client, query):
    data = query.data or ""
    if data == "enc:reset":
        uid = query.from_user.id if query.from_user else 0
        esettings.reset(uid)
        await query.answer("Encoder settings reset to defaults.", show_alert=True)
        s = esettings.get(uid)
        rows = [
            ("Codec", str(s["codec"]).upper()),
            ("Preset", str(s["preset"])),
            ("CRF", str(s["crf"])),
            ("Resolution", str(s["resolution"])),
            ("Audio", f"{s['audio_codec']} {s['audio_bitrate']}k"),
            ("Container", str(s["container"])),
        ]
        body = "\n".join(f"{k}: <code>{esc(v)}</code>" for k, v in rows)
        text = (
            f"{title('⚙️', 'encoder settings', 'per-user defaults')}\n<blockquote>{body}</blockquote>\n"
            "<i>Change with</i> <code>/encode -r 720p -c h265 -crf 22 -preset fast</code>\n"
            "<i>Reset with</i> <code>/reset</code>"
        )
        try:
            await query.message.edit_text(text, reply_markup=markup([btn("♻️ Reset", "enc:reset", "DANGER")]))
        except Exception:
            pass
    else:
        await query.answer()


def register_encoder(client):
    from pyrogram.handlers import CallbackQueryHandler, MessageHandler

    cmd = filters.command
    for name in QUALITY_COMMANDS:
        client.add_handler(MessageHandler(cmd_encode_quality, cmd(name)))

    client.add_handler(MessageHandler(cmd_encode, cmd(["encode", "enc"])))
    client.add_handler(MessageHandler(cmd_codec, cmd(["264h", "265h"])))
    client.add_handler(MessageHandler(cmd_enc_settings, cmd(["settings", "encsettings"])))
    client.add_handler(MessageHandler(cmd_enc_reset, cmd("reset")))
    client.add_handler(MessageHandler(cmd_sync_commands, cmd("synccommands")))
    client.add_handler(CallbackQueryHandler(cb_enc, filters.regex(r"^enc:")))
