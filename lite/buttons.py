"""Coloured inline buttons (same ButtonStyle colours as the original bot)."""

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

try:
    from pyrogram.enums import ButtonStyle
except Exception:  # noqa: BLE001
    ButtonStyle = None


def _style(name):
    return getattr(ButtonStyle, name, None) if ButtonStyle is not None else None


def btn(text, data=None, style=None, url=None):
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = data
    style_value = _style(style) if style else None
    if style_value is not None:
        try:
            return InlineKeyboardButton(**kwargs, style=style_value)
        except TypeError:  # library without coloured buttons
            pass
    return InlineKeyboardButton(**kwargs)


def markup(*rows):
    rows = [list(r) for r in rows if r]
    return InlineKeyboardMarkup(rows) if rows else None
