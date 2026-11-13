"""Tiny local JSON store (no database, no network): authorized ids and per-user thumbnails."""

import json
import os
import threading

_LOCK = threading.Lock()
DATA_DIR = "data"
FILE = os.path.join(DATA_DIR, "settings.json")
THUMB_DIR = os.path.join(DATA_DIR, "thumbs")


def _read():
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ids(data, key):
    """int-only ids: a hand-edited or corrupted file must never break authorization."""
    out = set()
    for value in data.get(key, []) or []:
        try:
            out.add(int(value))
        except (TypeError, ValueError):
            continue
    return out


def _write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, FILE)


def get_ids(key):
    with _LOCK:
        return _ids(_read(), key)


def add_id(key, value):
    with _LOCK:
        data = _read()
        ids = _ids(data, key)
        ids.add(int(value))
        data[key] = sorted(ids)
        _write(data)


def remove_id(key, value):
    with _LOCK:
        data = _read()
        ids = _ids(data, key)
        ids.discard(int(value))
        data[key] = sorted(ids)
        _write(data)


def user_thumb_path(user_id):
    path = os.path.join(THUMB_DIR, f"{int(user_id)}.jpg")
    return path if os.path.isfile(path) else None


def thumb_target(user_id):
    os.makedirs(THUMB_DIR, exist_ok=True)
    return os.path.join(THUMB_DIR, f"{int(user_id)}.jpg")


def delete_user_thumb(user_id):
    path = user_thumb_path(user_id)
    if path:
        os.remove(path)
        return True
    return False
