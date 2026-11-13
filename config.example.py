# ============================================================================
#  RS ENCODER MIRROR BOT · configuration template
#  Local run: copy this file to config.py and fill in your own values. Never commit config.py.
#  Heroku: do NOT use a file - set the same names as Config Vars in the dashboard.
#  Edit this file, then start the bot with  start.bat  (or .venv\Scripts\python.exe main.py)
#  Every value can also be supplied as an environment variable with the same name.
# ============================================================================

# ── Telegram credentials ────────────────────────────────────────────────────
BOT_TOKEN = ""                                       # from @BotFather
TELEGRAM_API = 0                                                 # api_id from my.telegram.org
TELEGRAM_HASH = ""                                    # api_hash from my.telegram.org
OWNER_ID = 0                                                     # your numeric Telegram user id
SUDO_USERS = ""                                                 # extra admins, ids separated by space/comma
AUTHORIZED_CHATS = ""                                          # groups/users allowed to use the bot

# ── Speed & resources ───────────────────────────────────────────────────────
DOWNLOAD_DIR = "downloads"
MAX_CONCURRENT_TASKS = 2       # pipelines (download+extract+upload) running at once
MAX_CONCURRENT_UPLOADS = 2     # files uploading to Telegram at the same time (1-4)
MAX_PARALLEL_FFMPEG = 2        # ffmpeg/ffprobe processes at once
DOWNLOAD_CONNECTIONS = 8      # parallel connections per direct download (1-8) → fastest setting
MIN_FREE_DISK_GB = 2.0         # refuse new tasks below this free space
MAX_FILE_SIZE_GB = 0           # 0 = unlimited
SPLIT_SIZE = 2097152000        # bytes; bigger files are split into numbered parts (Telegram limit)

# ── Delivery ────────────────────────────────────────────────────────────────
LEECH_TO_PM = True             # files requested in a group are delivered to the user's private chat
AS_DOCUMENT = False            # False: videos are sent as videos (with streaming + thumbnail)

# ── Thumbnails ──────────────────────────────────────────────────────────────
AUTO_THUMBNAIL = True          # TMDb backdrop + official logo, composited into a thumbnail
THUMBNAIL_LAYOUT = "2x2"       # ffmpeg frame sheet (2x2, 3x3 ...); "" = single frame
TMDB_API_KEY = ""                                     # optional, for automatic artwork
TMDB_ACCESS_TOKEN = ""                                # optional

# ── Downloads ───────────────────────────────────────────────────────────────
YT_COOKIES_FILE = "cookies.txt"  # paste Netscape cookies here (file lives next to main.py)
TG_PROXY = ""                    # OUTBOUND proxy for the bot itself, e.g. socks5://127.0.0.1:1080
ALLOW_INSECURE_SSL = False       # True only for broken/self-signed download servers

# ── Interface ───────────────────────────────────────────────────────────────
STATUS_UPDATE_INTERVAL = 10     # seconds between live status edits (fixed timer, no progress spam)
SET_COMMANDS = True            # refresh the Telegram command menu on every start
AUTO_DELETE_MESSAGES = True    # delete bot cards automatically to keep the chat clean
START_MESSAGE_TTL = 30         # /start card lifetime (seconds)
INFO_MESSAGE_TTL = 30          # usage / cancel hint cards
RESULT_MESSAGE_TTL = 60        # completion and failure cards
CLEAN_USER_MESSAGES = True     # delete the /l or /yl command message when the task ends
