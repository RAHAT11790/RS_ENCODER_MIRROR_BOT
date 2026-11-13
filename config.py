# ============================================================================
#  RS LEECH LITE · configuration
#  Edit this file, then start the bot with  start.bat  (or .venv\Scripts\python.exe main.py)
#  Every value can also be supplied as an environment variable with the same name.
# ============================================================================

# ── Telegram credentials ────────────────────────────────────────────────────
BOT_TOKEN = "8963100948:AAGxCIvTa14NP-yVq88bk4g7qkkETbxLQxs"      # from @BotFather
TELEGRAM_API = 25976192                                           # api_id from my.telegram.org
TELEGRAM_HASH = "8ba23141980539b4896e5adbc4ffd2e2"                # api_hash from my.telegram.org
OWNER_ID = 6621572366                                             # your numeric Telegram user id
SUDO_USERS = "6621572366"                                         # extra admins, ids separated by space/comma
AUTHORIZED_CHATS = "-1004366562744"                               # groups/users allowed to use the bot

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
TMDB_API_KEY = "37f4b185e3dc487e4fd3e56e2fab2307"                 # TMDb v3 API key
TMDB_ACCESS_TOKEN = ""         # or the v4 read access token

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
