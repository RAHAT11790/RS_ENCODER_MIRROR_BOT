"""Per-user encoder preferences (small JSON store, no database server needed)."""

import json
import os
import threading

from .presets import DEFAULT_SETTINGS

_LOCK = threading.Lock()
FILE = os.path.join("data", "encoder.json")


def _read():
    try:
        with open(FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(data):
    os.makedirs(os.path.dirname(FILE) or ".", exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, FILE)


def get(user_id):
    """Settings for *user_id* merged over the defaults."""
    with _LOCK:
        stored = _read().get(str(int(user_id)), {})
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        for key, value in stored.items():
            if key in merged:
                merged[key] = value
    return merged


def update(user_id, **changes):
    with _LOCK:
        data = _read()
        key = str(int(user_id))
        current = data.get(key) if isinstance(data.get(key), dict) else {}
        for name, value in changes.items():
            if name in DEFAULT_SETTINGS:
                current[name] = value
        data[key] = current
        _write(data)
    return get(user_id)


def reset(user_id):
    with _LOCK:
        data = _read()
        data.pop(str(int(user_id)), None)
        _write(data)
    return get(user_id)
