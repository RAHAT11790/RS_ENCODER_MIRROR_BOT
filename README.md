<div align="center"><a href="#">
  <img src="https://readme-typing-svg.demolab.com?font=Orbitron&weight=800&size=34&duration=2500&pause=900&color=00E5FF&center=true&vCenter=true&width=850&lines=RS+ENCODER+MIRROR+BOT;DOWNLOAD+%E2%80%A2+ENCODE+%E2%80%A2+UPLOAD;YOUR+ALL-IN-ONE+TELEGRAM+MEDIA+ENGINE" alt="RS ENCODER MIRROR BOT" />
</a><p>
  <img src="https://img.shields.io/badge/PROJECT-RS_ENCODER_MIRROR_BOT-00D9FF?style=for-the-badge&logo=telegram&logoColor=white" />
  <img src="https://img.shields.io/badge/PYTHON-3.10--3.13-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FFMPEG-POWERED-00A86B?style=for-the-badge&logo=ffmpeg&logoColor=white" />
</p><p>
  <img src="https://img.shields.io/badge/ENGINE-MEDIA_PROCESSING-8A2BE2?style=flat-square" />
  <img src="https://img.shields.io/badge/PLATFORM-TELEGRAM-26A5E4?style=flat-square&logo=telegram" />
  <img src="https://img.shields.io/badge/STATUS-SELF_HOSTED-00C853?style=flat-square" />
</p>⚡ THE ULTIMATE TELEGRAM MIRROR & VIDEO ENCODER

Download • Mirror • Extract • Convert • Encode • Upload

A powerful Telegram-based media automation system combining direct downloads, yt-dlp extraction, archive processing, FFmpeg video encoding, automatic thumbnails, and intelligent file delivery.

</div>---

<div align="center">◈ PROJECT OVERVIEW ◈

</div>RS ENCODER MIRROR BOT is an advanced Telegram media-processing bot designed to make downloading, mirroring, extracting, converting, and uploading files easier through a single Telegram interface.

Built with Python and asynchronous task processing, this project integrates multiple media tools into one streamlined workflow.

Whether you want to download a direct video URL, extract media from supported websites, process Telegram videos, extract protected archives, or encode videos into your preferred resolution, this bot brings everything together.

✨ What makes it powerful?

- Advanced mirror and leech engine.
- Integrated FFmpeg video encoder.
- H.264 and H.265 video compression.
- Multiple video resolution presets.
- yt-dlp media extraction.
- Automatic thumbnail generation.
- Archive extraction with password handling.
- Live task progress monitoring.
- Concurrent download and upload processing.
- Automatic temporary-file cleanup.
- Per-user encoder preferences.
- Owner and administrator management.

---

<div align="center">◈ CORE FEATURES ◈

</div><table>
<tr>
<td width="50%" valign="top">📥 ADVANCED MIRROR ENGINE

- Direct HTTP/HTTPS downloads.
- Telegram media downloading.
- Multiple URL processing.
- yt-dlp integration.
- YouTube media extraction.
- HLS / M3U8 support through yt-dlp.
- Custom output filenames.
- Optional download headers.

</td>
<td width="50%" valign="top">🎬 PROFESSIONAL VIDEO ENCODER

- FFmpeg-based encoding.
- H.264 (AVC) support.
- H.265 (HEVC) support.
- CRF quality configuration.
- Multiple encoding presets.
- Resolution selection.
- Audio codec configuration.
- MP4, MKV and AVI containers.

</td>
</tr>
<tr>
<td valign="top">📦 SMART ARCHIVE PROCESSOR

- ZIP archive extraction.
- RAR and 7Z through compatible 7-Zip tools.
- TAR, GZIP, BZIP2 and XZ support.
- Password-protected archive handling.
- Interactive password requests.
- Automatic extraction directory management.
- Safe extraction path checks.

</td>
<td valign="top">🖼️ INTELLIGENT THUMBNAIL SYSTEM

- Automatic video thumbnails.
- TMDb artwork integration.
- Backdrop and logo composition.
- FFmpeg frame-sheet generation.
- Custom personal thumbnails.
- Configurable thumbnail layouts.
- Automatic thumbnail selection.

</td>
</tr>
<tr>
<td valign="top">⚡ HIGH-PERFORMANCE TASK SYSTEM

- Asynchronous task management.
- Configurable concurrent pipelines.
- Parallel upload management.
- Separate FFmpeg concurrency controls.
- Live progress updates.
- Task cancellation.
- Disk-space protection.
- Automatic workspace cleanup.

</td>
<td valign="top">🛡️ ADMINISTRATION & ACCESS CONTROL

- Owner-only administration.
- Sudo-user configuration.
- Authorized chat management.
- User banning and unbanning.
- Premium user management.
- Bot restart command.
- Log retrieval.
- Telegram command-menu synchronization.

</td>
</tr>
</table>---

<div align="center">◈ SYSTEM ARCHITECTURE ◈

</div>flowchart TD
    A["Telegram User"] --> B["Bot Interface"]
    B --> C{"Identify Input"}
    C --> D["Direct HTTP"]
    C --> E["yt-dlp"]
    C --> F["Telegram Media"]

    D --> G["Download Manager"]
    E --> G
    F --> G

    G --> H{"Archive Extraction?"}
    H -->|Yes| I["7-Zip / Archive Engine"]
    H -->|No| J{"Video Encoding?"}
    I --> J

    J -->|Yes| K["FFmpeg Encoder"]
    J -->|No| L["Output Manager"]
    K --> L

    L --> M["File Splitter"]
    M --> N["Telegram Uploader"]
    N --> O["Completion Report"]
    O --> P["Workspace Cleanup"]

Processing Workflow

1. A user submits a media URL or Telegram media message.
2. The bot identifies the input source.
3. The appropriate download engine retrieves the file.
4. Archive extraction runs if requested.
5. FFmpeg encoding runs if enabled.
6. Output files are collected and checked.
7. Oversized files are split according to configuration.
8. Files are uploaded to Telegram.
9. The bot reports completion or failure.
10. Temporary task files are automatically removed.

---

<div align="center">◈ ENCODER TECHNOLOGY ◈

</div>🎞️ Supported Video Codecs

Codec| Technology| Description
H.264| libx264| Broad compatibility
H.265| libx265| Better compression efficiency

📐 Resolution Presets

Preset| Resolution
360p| 640 × 360 (typical 16:9)
480p| 854 × 480 (typical 16:9)
560p| 576p output height
720p| 1280 × 720 (typical 16:9)
1080p| 1920 × 1080 (typical 16:9)
1440p / 2K| 2560 × 1440 (typical 16:9)
2160p / 4K| 3840 × 2160 (typical 16:9)
OG| Original source height

🔊 Audio Options

- AAC
- Copy original audio
- AC3
- Opus

⚙️ Encoding Presets

"ultrafast" · "superfast" · "veryfast" · "fast" · "medium" · "slow"

📁 Supported Containers

"MP4" · "MKV" · "AVI"

---

<div align="center">◈ TELEGRAM COMMAND CENTER ◈

</div>📥 Download Commands

Command| Function
"/start"| Open the main interface
"/help"| Display help information
"/leech"| Download a direct URL or replied media
"/l"| Short alias for leech
"/ytdlleech"| Download through yt-dlp
"/yl"| Short alias for yt-dlp
"/status"| Display active tasks
"/cancel"| Cancel running tasks
"/stats"| View bot/server statistics
"/ping"| Check bot latency
"/cookies"| Show cookie-file information
"/setthumb"| Set personal thumbnail
"/delthumb"| Delete personal thumbnail

🎬 Encoder Commands

Command| Function
"/encode"| Encode using saved settings
"/360p"| Encode at 360p
"/480p"| Encode at 480p
"/560p"| Encode at 576p
"/576p"| Encode at 576p
"/720p"| Encode at 720p
"/1080p"| Encode at 1080p
"/1440p"| Encode at 1440p
"/2k"| Encode at 1440p
"/4k"| Encode at 2160p
"/264h"| Set H.264 codec
"/265h"| Set H.265 codec
"/settings"| View encoder settings
"/reset"| Reset encoder settings

👑 Administration Commands

Command| Function
"/authorize"| Authorize a user or chat
"/unauthorize"| Remove authorization
"/ban"| Ban a user or chat
"/unban"| Remove a ban
"/premium"| Manage premium users
"/addpremium"| Add a premium user
"/removepremium"| Remove a premium user
"/restart"| Restart the bot
"/log"| Retrieve bot logs
"/synccommands"| Synchronize Telegram commands

---

<div align="center">◈ USAGE EXAMPLES ◈

</div>1. Direct URL Download

/leech https://example.com/video.mp4

2. Short Leech Command

/l https://example.com/video.mp4

3. Archive Extraction

/l https://example.com/archive.zip -e

4. Download with yt-dlp

/yl https://youtu.be/VIDEO_ID

5. Select Video Quality

/yl https://youtu.be/VIDEO_ID -q 720

6. Download Audio

/yl https://youtu.be/VIDEO_ID -a

7. Custom Output Filename

/yl https://youtu.be/VIDEO_ID -n My_Video

8. Encode a Replied Video

Reply to a Telegram video and send:

/encode

9. Custom Encoding Configuration

/encode -r 720p -c h265 -crf 22 -preset fast

10. Change Video Codec

/265h

Or:

/264h

Note: Archive extraction is optional. Use "-e" to enable extraction. Without this flag, archives are delivered without extraction.

---

<div align="center">◈ INSTALLATION GUIDE ◈

</div>📋 Requirements

- Python 3.10–3.13
- Telegram Bot Token
- Telegram API ID
- Telegram API Hash
- FFmpeg and FFprobe
- 7-Zip compatible utility
- Internet connection
- Sufficient disk space

1. Clone the Repository

git clone https://github.com/rahadcodes228/RS_ENCODER_MIRROR_BOT.git

cd RS_ENCODER_MIRROR_BOT

2. Create a Virtual Environment

Linux / VPS / Termux

python -m venv .venv

Activate it:

source .venv/bin/activate

Windows

py -3.13 -m venv .venv

.venv\Scripts\activate

3. Install Python Dependencies

python -m pip install --upgrade pip

pip install -r requirements.txt

4. Configure the Bot

Open:

config.py

Set your own Telegram credentials and owner configuration.

BOT_TOKEN = "YOUR_BOT_TOKEN"

TELEGRAM_API = YOUR_API_ID

TELEGRAM_HASH = "YOUR_API_HASH"

OWNER_ID = YOUR_TELEGRAM_USER_ID

SUDO_USERS = ""

AUTHORIZED_CHATS = ""

Configure the TMDb credentials if you want automatic artwork integration:

TMDB_API_KEY = "YOUR_TMDB_API_KEY"

Never publish real tokens, API credentials, cookies or private configuration files.

5. Start the Bot

python main.py

The launcher includes a setup routine for Python dependencies and supported portable runtime tools. It also starts the bot through a supervised child process.

---

<div align="center">◈ CONFIGURATION REFERENCE ◈

</div>The main configuration is managed through "config.py". Environment variables with matching names can also override configuration values.

Variable| Purpose
"BOT_TOKEN"| Telegram bot token
"TELEGRAM_API"| Telegram API ID
"TELEGRAM_HASH"| Telegram API hash
"OWNER_ID"| Bot owner ID
"SUDO_USERS"| Additional administrator IDs
"AUTHORIZED_CHATS"| Authorized user/chat IDs
"DOWNLOAD_DIR"| Download workspace
"MAX_CONCURRENT_TASKS"| Maximum concurrent pipelines
"MAX_CONCURRENT_UPLOADS"| Concurrent file uploads
"MAX_PARALLEL_FFMPEG"| Parallel FFmpeg operations
"DOWNLOAD_CONNECTIONS"| Direct download connections
"MIN_FREE_DISK_GB"| Minimum free disk requirement
"MAX_FILE_SIZE_GB"| Maximum output size; zero means unlimited
"SPLIT_SIZE"| File splitting threshold
"LEECH_TO_PM"| Deliver group-requested files privately
"AS_DOCUMENT"| Upload files as documents
"AUTO_THUMBNAIL"| Enable automatic thumbnails
"THUMBNAIL_LAYOUT"| Video frame-sheet layout
"TMDB_API_KEY"| TMDb API key
"TMDB_ACCESS_TOKEN"| TMDb access token
"YT_COOKIES_FILE"| yt-dlp cookies file
"TG_PROXY"| Optional Telegram outbound proxy
"STATUS_UPDATE_INTERVAL"| Task progress update interval
"AUTO_DELETE_MESSAGES"| Automatic message cleanup
"TIMEZONE"| Configured timezone

Default Encoder Profile

Option| Default
Codec| H.264
Preset| veryfast
CRF| 26
Resolution| Original
Audio| AAC
Audio bitrate| 128 kbps
Container| MP4
Faststart| Enabled
Subtitles| Copy

Per-user encoder preferences are stored in:

data/encoder.json

Bot authorization settings and personal thumbnails are stored locally under:

data/

---

<div align="center">◈ PROJECT STRUCTURE ◈

</div>RS_ENCODER_MIRROR_BOT/
│
├── main.py
├── config.py
├── requirements.txt
├── install.sh
├── start.bat
├── rs_setup.py
├── rsbin.py
├── bin_bootstrap.py
├── Procfile
│
├── encoder/
│   ├── __init__.py
│   ├── engine.py
│   ├── presets.py
│   ├── progress.py
│   ├── settings.py
│   └── assets/
│       ├── font.ttf
│       └── watermark.ass
│
├── lite/
│   ├── __init__.py
│   ├── __main__.py
│   ├── bot.py
│   ├── buttons.py
│   ├── config.py
│   ├── encoder_commands.py
│   ├── archive.py
│   ├── engines.py
│   ├── fmt.py
│   ├── http_dl.py
│   ├── media.py
│   ├── pipeline.py
│   ├── store.py
│   ├── task.py
│   ├── tmdb.py
│   ├── uploader.py
│   └── ytdl.py
│
└── README.md

---

<div align="center">◈ TECHNOLOGY STACK ◈

</div><p align="center">
  <img src="https://skillicons.dev/icons?i=python,linux,bash,windows,git,github" alt="Technology stack" />
</p>Technology| Role
Python| Core application
Wzgram| Telegram bot client framework
asyncio| Asynchronous execution
aiohttp| HTTP networking
aiofiles| Asynchronous file operations
yt-dlp| Website media extraction
FFmpeg| Video/audio encoding
FFprobe| Media information analysis
Pillow| Thumbnail image processing
Py7zr| Archive handling
psutil| System monitoring

Dependencies

wzgram>=3.1.6,<4
aiohttp>=3.9.5
aiofiles>=23.2.1
yt-dlp[default]>=2024.6.9
pillow>=10.3.0
psutil>=5.9.8
py7zr>=0.22

---

<div align="center">◈ PERFORMANCE & RESOURCE MANAGEMENT ◈

</div>The application includes configurable controls to help manage system resources.

- Concurrent task limits.
- Separate upload concurrency.
- FFmpeg process limits.
- Direct download connection limits.
- Minimum free disk-space checks.
- Optional maximum output size.
- Automatic file splitting.
- Temporary task-folder cleanup.

Important: Actual speed depends on server CPU, RAM, storage performance, network bandwidth, source-server limitations and the selected encoding configuration.

---

<div align="center">◈ SECURITY & PRIVACY ◈

</div>Security recommendations for self-hosting:

- Keep your Telegram bot token private.
- Never commit "config.py" with real credentials.
- Never commit personal "cookies.txt".
- Keep TMDb and other API credentials private.
- Restrict owner and sudo commands.
- Use authorized chat settings when needed.
- Protect your server and download directories.
- Regularly update Python dependencies and external binaries.

If a bot token has been exposed, revoke it through BotFather and generate a replacement before deploying the repository publicly.

---

<div align="center">◈ IMPORTANT NOTES ◈

</div>- This project is designed for self-hosted deployment.
- External media services can change their extraction rules.
- yt-dlp support depends on the source website and available formats.
- Some archive formats require an installed 7-Zip-compatible binary.
- H.265 encoding may take longer than H.264.
- 4K encoding requires substantial CPU and storage resources.
- Telegram upload limits and account capabilities may affect delivery.
- Respect copyright, website terms, and applicable laws when downloading or sharing media.

---

<div align="center">◈ LICENSE ◈

</div>No explicit license file was identified in the supplied project package.

Before publishing this repository, add a "LICENSE" file and specify the terms under which others may use, modify and distribute the project.

---

<div align="center">◈ CONNECT WITH THE PROJECT ◈

RS ENCODER MIRROR BOT

Built for powerful media automation through Telegram.

<a href="https://github.com/rahadcodes228/RS_ENCODER_MIRROR_BOT">
  <img src="https://img.shields.io/badge/GITHUB-VIEW_REPOSITORY-181717?style=for-the-badge&logo=github&logoColor=white" />
</a><br><br>

<img src="https://img.shields.io/badge/RS-ENCODER_MIRROR_BOT-00D9FF?style=for-the-badge" />DOWNLOAD • MIRROR • ENCODE • DELIVER

<sub>© RS ENCODER MIRROR BOT · All rights reserved by their respective owners.</sub>

</div>
