"""Encoder commands integrated into the mirror-leech bot.

Every command queues the normal download pipeline and adds one extra stage:
``download -> encode -> upload``.  Settings live per user in ``encoder.settings``.
"""

import os
from contextlib import suppress

from pyrogram import filters

from . import LOGGER
from .bot import (
    BOARD,
    MAX_LINKS_PER_MESSAGE,
    _admin_uid,
    _cb_allowed,
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
from encoder.presets import AUDIO_CODECS, PRESETS, height_for

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


# --------------------------------------------------------------------------
#  Interactive /settings panel
#  callback data:  enc:<owner id>:<action>[:<field>[:<value>]]   (always < 64 bytes)
# --------------------------------------------------------------------------
PANEL_TTL = 600  # seconds the panel stays in the chat (the old 30 s card vanished too fast)

CODEC_CHOICES = [("h264", "H.264"), ("h265", "H.265")]
RESOLUTION_CHOICES = [
    ("OG", "Original"), ("360p", "360p"), ("480p", "480p"), ("576p", "576p"),
    ("720p", "720p"), ("1080p", "1080p"), ("1440p", "1440p"), ("4k", "4K"),
]
PRESET_CHOICES = [(p, p) for p in PRESETS]
AUDIO_CODEC_CHOICES = [("aac", "AAC"), ("copy", "Copy"), ("ac3", "AC3"), ("opus", "Opus")]
AUDIO_BITRATE_CHOICES = [(b, f"{b}k") for b in ("64", "96", "128", "160", "192", "256")]
CONTAINER_CHOICES = [("mp4", "MP4"), ("mkv", "MKV"), ("avi", "AVI")]
SUBTITLE_CHOICES = [("copy", "Keep"), ("none", "Remove")]
TUNE_CHOICES = [("none", "None"), ("film", "Film"), ("animation", "Animation"), ("grain", "Grain")]
CRF_CHOICES = (18, 20, 22, 24, 26, 28, 30, 32)
TOGGLES = {"watermark": ("🏷", "Watermark", False), "faststart": ("🚀", "Faststart", True)}

# menu key -> (icon, heading, hint, [(setting field, choices, buttons per row), ...])
MENUS = {
    "codec": ("🎞", "video codec", "H.265 = smaller files · H.264 = plays everywhere",
              [("codec", CODEC_CHOICES, 2)]),
    "resolution": ("📐", "resolution", "original keeps the source size · never upscales",
                   [("resolution", RESOLUTION_CHOICES, 4)]),
    "preset": ("⚡", "speed preset", "slower = smaller file, longer encode",
               [("preset", PRESET_CHOICES, 3)]),
    "audio": ("🔊", "audio", "codec first, bitrate below (ignored for Copy)",
              [("audio_codec", AUDIO_CODEC_CHOICES, 4), ("audio_bitrate", AUDIO_BITRATE_CHOICES, 3)]),
    "container": ("📦", "container", "MP4 for sharing · MKV for subtitles and extras",
                  [("container", CONTAINER_CHOICES, 3)]),
    "subtitles": ("💬", "subtitles", "keep or strip embedded subtitle tracks",
                  [("subtitles", SUBTITLE_CHOICES, 2)]),
    "tune": ("🎨", "tune", "Film is H.264 only · Animation suits anime",
             [("tune", TUNE_CHOICES, 2)]),
}
ALLOWED = {
    field: {value for value, _ in choices}
    for _, _, _, groups in MENUS.values()
    for field, choices, _ in groups
}
FIELD_LABEL = {
    "codec": "Codec", "resolution": "Resolution", "preset": "Preset", "audio_codec": "Audio codec",
    "audio_bitrate": "Audio bitrate", "container": "Container", "subtitles": "Subtitles", "tune": "Tune",
}


def _norm_res(value):
    text = str(value or "").strip().lower()
    if text in ("", "og", "source", "original"):
        return "OG"
    if text in ("2160p", "4k"):
        return "4k"
    if text == "2k":
        return "1440p"
    if text == "560p":
        return "576p"
    return text if text.endswith("p") else text + "p"


def _current(settings, field):
    """The stored value of *field* in the same spelling the buttons use."""
    if field == "resolution":
        return _norm_res(settings.get("resolution"))
    if field == "tune":
        return str(settings.get("tune") or "none")
    if field == "audio_bitrate":
        return str(settings.get("audio_bitrate") or "128")
    return str(settings.get(field) or "")


def _label(field, value):
    for key, text in {
        "codec": CODEC_CHOICES, "resolution": RESOLUTION_CHOICES, "audio_codec": AUDIO_CODEC_CHOICES,
        "container": CONTAINER_CHOICES, "subtitles": SUBTITLE_CHOICES, "tune": TUNE_CHOICES,
    }.items():
        if key == field:
            for v, label in text:
                if v == value:
                    return label
    return str(value)


def _summary(settings):
    audio = "Copy" if settings.get("audio_codec") == "copy" else (
        f"{_label('audio_codec', settings.get('audio_codec'))} · {settings.get('audio_bitrate')}k"
    )
    rows = [
        ("Codec", _label("codec", _current(settings, "codec"))),
        ("Resolution", _label("resolution", _current(settings, "resolution"))),
        ("Preset", _current(settings, "preset")),
        ("CRF", str(settings.get("crf"))),
        ("Audio", audio),
        ("Container", _label("container", _current(settings, "container"))),
        ("Subtitles", _label("subtitles", _current(settings, "subtitles"))),
        ("Tune", _label("tune", _current(settings, "tune"))),
        ("Watermark", "on" if settings.get("watermark") else "off"),
        ("Faststart", "on" if settings.get("faststart", True) else "off"),
    ]
    return "\n".join(f"{k}: <code>{esc(v)}</code>" for k, v in rows)


def _cb(uid, *parts):
    return ":".join(["enc", str(uid), *[str(p) for p in parts]])


def _chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def _main_view(uid):
    s = esettings.get(uid)
    text = (
        f"{title('⚙️', 'encoder settings', 'tap a button to change · saved instantly')}\n"
        f"<blockquote>{_summary(s)}</blockquote>\n"
        "<i>Reply to a video (or send a link) with</i> <code>/encode</code> <i>to use these settings.</i>"
    )
    crf_label = f"🎚 CRF · {s.get('crf')}"
    wm_icon, wm_name, wm_default = TOGGLES["watermark"]
    fs_icon, fs_name, fs_default = TOGGLES["faststart"]
    wm_on = bool(s.get("watermark", wm_default))
    fs_on = bool(s.get("faststart", fs_default))
    keyboard = markup(
        [
            btn(f"🎞 Codec · {_label('codec', _current(s, 'codec'))}", _cb(uid, "menu", "codec"), "PRIMARY"),
            btn(f"📐 Res · {_label('resolution', _current(s, 'resolution'))}", _cb(uid, "menu", "resolution"), "PRIMARY"),
        ],
        [
            btn(f"⚡ Preset · {_current(s, 'preset')}", _cb(uid, "menu", "preset"), "PRIMARY"),
            btn(crf_label, _cb(uid, "menu", "crf"), "PRIMARY"),
        ],
        [
            btn("🔊 Audio · Copy" if s.get("audio_codec") == "copy" else f"🔊 Audio · {s.get('audio_bitrate')}k",
                _cb(uid, "menu", "audio"), "PRIMARY"),
            btn(f"📦 Format · {_label('container', _current(s, 'container'))}", _cb(uid, "menu", "container"), "PRIMARY"),
        ],
        [
            btn(f"💬 Subs · {_label('subtitles', _current(s, 'subtitles'))}", _cb(uid, "menu", "subtitles"), "PRIMARY"),
            btn(f"🎨 Tune · {_label('tune', _current(s, 'tune'))}", _cb(uid, "menu", "tune"), "PRIMARY"),
        ],
        [
            btn(f"{wm_icon} {wm_name}: {'ON' if wm_on else 'OFF'}", _cb(uid, "tog", "watermark"),
                "SUCCESS" if wm_on else "PRIMARY"),
            btn(f"{fs_icon} {fs_name}: {'ON' if fs_on else 'OFF'}", _cb(uid, "tog", "faststart"),
                "SUCCESS" if fs_on else "PRIMARY"),
        ],
        [btn("♻️ Reset", _cb(uid, "reset"), "DANGER"), btn("✖️ Close", _cb(uid, "close"), "DANGER")],
    )
    return text, keyboard


def _menu_view(uid, key):
    s = esettings.get(uid)
    back = [btn("⬅️ Back", _cb(uid, "home"), "PRIMARY")]
    if key == "crf":
        crf = int(s.get("crf") or 26)
        text = (
            f"{title('🎚', 'quality (crf)', 'lower = better quality + bigger file')}\n"
            f"<blockquote>Current CRF: <code>{crf}</code>\n"
            "<i>H.264: 18-28 is the useful range · H.265: 20-30</i></blockquote>"
        )
        rows = [
            [btn(("✅ " if crf == v else "") + str(v), _cb(uid, "set", "crf", v), "SUCCESS" if crf == v else "PRIMARY")
             for v in chunk]
            for chunk in _chunks(CRF_CHOICES, 4)
        ]
        rows.append([
            btn("➖ 1", _cb(uid, "crf", -1), "PRIMARY"),
            btn(f"CRF {crf}", _cb(uid, "noop"), "PRIMARY"),
            btn("➕ 1", _cb(uid, "crf", 1), "PRIMARY"),
        ])
        rows.append(back)
        return text, markup(*rows)
    icon, heading, hint, groups = MENUS[key]
    text = (
        f"{title(icon, heading, hint)}\n"
        f"<blockquote>{_summary(s)}</blockquote>"
    )
    rows = []
    for field, choices, per_row in groups:
        current = _current(s, field)
        buttons = [
            btn(("✅ " if value == current else "") + label, _cb(uid, "set", field, value),
                "SUCCESS" if value == current else "PRIMARY")
            for value, label in choices
        ]
        rows.extend(_chunks(buttons, per_row))
    rows.append(back)
    return text, markup(*rows)


def _apply(uid, field, value):
    """Validate and store one button choice -> (ok, toast text)."""
    if field == "crf":
        try:
            number = max(0, min(int(value), 51))
        except ValueError:
            return False, "Invalid CRF value."
        esettings.update(uid, crf=number)
        return True, f"✅ CRF: {number}"
    if field not in ALLOWED or value not in ALLOWED[field]:
        return False, "That option is not available."
    if field == "tune":
        esettings.update(uid, tune="" if value == "none" else value)
    elif field == "codec":
        if value == "h264":
            esettings.update(uid, codec="h264", ten_bit=False)
        else:
            esettings.update(uid, codec="h265")
    else:
        esettings.update(uid, **{field: value})
    return True, f"✅ {FIELD_LABEL.get(field, field)}: {_label(field, value) if field != 'preset' else value}"


async def _show(query, text, keyboard):
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except Exception as exc:  # noqa: BLE001
        if "NOT_MODIFIED" not in str(exc).upper():
            LOGGER.warning(f"settings panel could not be updated: {exc}")


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
    ignored = []
    i = 0
    while i < len(args):
        arg = args[i].lower()
        value = args[i + 1] if i + 1 < len(args) else None
        if arg == "-r" and value is not None:
            if _norm_res(value) == "OG" or height_for(value):
                changes["resolution"] = _norm_res(value)
            else:
                ignored.append(f"-r {value}")
            i += 2
        elif arg == "-c" and value is not None:
            changes["codec"] = "h265" if value.lower() in ("h265", "hevc", "x265") else "h264"
            i += 2
        elif arg == "-crf" and value is not None:
            try:
                changes["crf"] = max(0, min(int(value), 51))
            except ValueError:
                ignored.append(f"-crf {value}")
            i += 2
        elif arg == "-preset" and value is not None:
            if value.lower() in PRESETS:
                changes["preset"] = value.lower()
            else:
                ignored.append(f"-preset {value}")
            i += 2
        elif arg == "-a" and value is not None:
            if value.lower() in AUDIO_CODECS:
                changes["audio_codec"] = value.lower()
            else:
                ignored.append(f"-a {value}")
            i += 2
        else:
            i += 1
    if ignored:
        warn = await message.reply_text(
            f"{title('⚠️', 'ignored values', 'not a valid option')}\n"
            f"<blockquote><code>{esc(', '.join(ignored))}</code></blockquote>\n"
            "<i>Open</i> <code>/settings</code> <i>to pick valid options with buttons.</i>"
        )
        autodelete(warn)
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
            "</blockquote>\n"
            "<i>Tune everything with buttons:</i> <code>/settings</code>"
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
    """`/settings` - the interactive panel: every option is a button."""
    if not message.from_user:
        return
    text, keyboard = _main_view(message.from_user.id)
    sent = await message.reply_text(text, reply_markup=keyboard)
    autodelete(sent, ttl=PANEL_TTL)


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
    if not _cb_allowed(query):
        await query.answer("🔒 Not authorized.", show_alert=True)
        return
    parts = (query.data or "").split(":")
    # enc:<owner id>:<action>[:<field>[:<value>]]
    if len(parts) < 3 or not parts[1].isdigit():
        await query.answer("⌛ This panel is outdated - send /settings again.", show_alert=True)
        return
    owner = int(parts[1])
    clicker = query.from_user.id if query.from_user else 0
    if clicker != owner and not _admin_uid(clicker):
        await query.answer("🔒 This panel belongs to another user. Send /settings for your own.", show_alert=True)
        return
    action = parts[2]
    arg1 = parts[3] if len(parts) > 3 else ""
    arg2 = parts[4] if len(parts) > 4 else ""

    if action == "noop":
        await query.answer()
    elif action == "home":
        await query.answer()
        await _show(query, *_main_view(owner))
    elif action == "menu":
        if arg1 != "crf" and arg1 not in MENUS:
            await query.answer("Unknown menu.", show_alert=True)
            return
        await query.answer()
        await _show(query, *_menu_view(owner, arg1))
    elif action == "set":
        ok, toast = _apply(owner, arg1, arg2)
        await query.answer(toast, show_alert=not ok)
        if ok:
            await _show(query, *_menu_view(owner, "crf" if arg1 == "crf" else _menu_for_field(arg1)))
    elif action == "crf":
        try:
            delta = int(arg1)
        except ValueError:
            await query.answer()
            return
        current = int(esettings.get(owner).get("crf") or 26)
        ok, toast = _apply(owner, "crf", current + delta)
        await query.answer(toast)
        await _show(query, *_menu_view(owner, "crf"))
    elif action == "tog":
        if arg1 not in TOGGLES:
            await query.answer()
            return
        default = TOGGLES[arg1][2]
        now = not bool(esettings.get(owner).get(arg1, default))
        esettings.update(owner, **{arg1: now})
        await query.answer(f"{TOGGLES[arg1][1]}: {'ON' if now else 'OFF'}")
        await _show(query, *_main_view(owner))
    elif action == "reset":
        esettings.reset(owner)
        await query.answer("♻️ Encoder settings reset to defaults.")
        await _show(query, *_main_view(owner))
    elif action == "close":
        await query.answer("Closed")
        with suppress(Exception):
            await query.message.delete()
    else:
        await query.answer()


def _menu_for_field(field):
    """Which submenu a setting field belongs to (audio_codec and audio_bitrate share one)."""
    for key, (_, _, _, groups) in MENUS.items():
        if any(group[0] == field for group in groups):
            return key
    return "codec"


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
