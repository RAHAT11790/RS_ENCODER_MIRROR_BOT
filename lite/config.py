"""Central configuration: defaults < config.py (next to main.py) < environment variables."""

import importlib.util
import os


class Config:
    BOT_TOKEN = ""
    TELEGRAM_API = 0
    TELEGRAM_HASH = ""
    OWNER_ID = 0
    SUDO_USERS = ""           # extra admins, space/comma separated user ids
    AUTHORIZED_CHATS = ""     # groups/users allowed to use the bot (space/comma separated ids)
    DOWNLOAD_DIR = "downloads"
    MAX_CONCURRENT_TASKS = 4  # pipelines (download+extract+upload) running at once
    MAX_CONCURRENT_UPLOADS = 2  # files uploading to Telegram at the same time
    MAX_PARALLEL_FFMPEG = 2   # ffmpeg/ffprobe processes at once
    DOWNLOAD_CONNECTIONS = 8  # parallel connections per direct download (1-8)
    MIN_FREE_DISK_GB = 2.0    # refuse new tasks when less than this is free
    MAX_FILE_SIZE_GB = 0.0    # 0 = no limit
    SPLIT_SIZE = 2097152000   # bytes; files above this are split before upload
    LEECH_TO_PM = True        # files from groups are delivered to the user's private chat
    AS_DOCUMENT = False       # False: videos are sent as videos
    AUTO_THUMBNAIL = True
    THUMBNAIL_LAYOUT = "2x2"  # frames tiled into the video thumbnail ("" = single frame)
    TMDB_API_KEY = ""         # TMDb v3 key (or use TMDB_ACCESS_TOKEN)
    TMDB_ACCESS_TOKEN = ""
    YT_COOKIES_FILE = "cookies.txt"
    TG_PROXY = ""             # optional OUTBOUND proxy for the bot itself, e.g. socks5://127.0.0.1:1080
    ALLOW_INSECURE_SSL = False
    STATUS_UPDATE_INTERVAL = 5    # seconds between live status edits (3-60); fixed timer, no progress spam
    SET_COMMANDS = True       # update the Telegram command menu at every start
    AUTO_DELETE_MESSAGES = True   # clean the chat automatically
    START_MESSAGE_TTL = 30        # seconds before the /start card is deleted
    INFO_MESSAGE_TTL = 30         # usage / cancel / status hint cards
    RESULT_MESSAGE_TTL = 60       # completion and failure cards
    CLEAN_USER_MESSAGES = True    # delete the /l or /yl command when the task ends
    TIMEZONE = "UTC"


_DEFAULTS = {k: v for k, v in vars(Config).items() if k.isupper()}


def _cast(default, raw):
    if isinstance(default, bool):
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(float(raw))
    if isinstance(default, float):
        return float(raw)
    return str(raw)


def load(path="config.py"):
    for k, v in _DEFAULTS.items():
        setattr(Config, k, v)
    if os.path.isfile(path):
        spec = importlib.util.spec_from_file_location("rs_user_config", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for k, default in _DEFAULTS.items():
            if hasattr(mod, k):
                try:
                    setattr(Config, k, _cast(default, getattr(mod, k)) if not isinstance(getattr(mod, k), type(default)) else getattr(mod, k))
                except (TypeError, ValueError):
                    pass
    for k, default in _DEFAULTS.items():
        raw = os.environ.get(k)
        if raw not in (None, ""):
            try:
                setattr(Config, k, _cast(default, raw))
            except ValueError:
                pass
    Config.DOWNLOAD_DIR = os.path.abspath(Config.DOWNLOAD_DIR)
    Config.DOWNLOAD_CONNECTIONS = max(1, min(int(Config.DOWNLOAD_CONNECTIONS), 8))
    Config.MAX_CONCURRENT_TASKS = max(1, int(Config.MAX_CONCURRENT_TASKS))
    Config.MAX_CONCURRENT_UPLOADS = max(1, min(int(Config.MAX_CONCURRENT_UPLOADS), 4))
    Config.MAX_PARALLEL_FFMPEG = max(1, int(Config.MAX_PARALLEL_FFMPEG))
    Config.STATUS_UPDATE_INTERVAL = max(3, min(int(Config.STATUS_UPDATE_INTERVAL), 60))
    return Config


def id_list(raw):
    out = set()
    for part in str(raw or "").replace(",", " ").split():
        try:
            out.add(int(part))
        except ValueError:
            pass
    return out
