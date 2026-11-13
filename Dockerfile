# ============================================================================
#  RS ENCODER MIRROR BOT - Heroku (container stack) / any Docker host
#  Root is available while the image is BUILT, so every system package is
#  installed here once. Nothing has to be downloaded when the dyno starts.
# ============================================================================
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    HOME=/app \
    XDG_CACHE_HOME=/tmp/.cache \
    RS_SKIP_SETUP=1 \
    AUTO_INSTALL_SYSTEM=0 \
    MAX_CONCURRENT_TASKS=1 \
    MAX_PARALLEL_FFMPEG=1 \
    MAX_CONCURRENT_UPLOADS=2 \
    MIN_FREE_DISK_GB=1

# ── System packages (ffmpeg + ffprobe, 7-Zip, bsdtar for RAR fallback) ───────
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg p7zip-full libarchive-tools curl xz-utils ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# ── Official 7-Zip build (adds RAR support). Optional: if the download fails the
#    build still succeeds and the apt p7zip-full above is used instead. ─────────
RUN ( curl -fsSL https://www.7-zip.org/a/7z2501-linux-x64.tar.xz -o /tmp/7z.tar.xz \
      && mkdir -p /tmp/7z && tar -xJf /tmp/7z.tar.xz -C /tmp/7z \
      && install -m 0755 /tmp/7z/7zz /usr/local/bin/7zz \
      && ln -sf /usr/local/bin/7zz /usr/local/bin/7z \
      && ln -sf /usr/local/bin/7zz /usr/local/bin/7za \
    ) || echo "[warn] official 7-Zip download skipped - using apt p7zip-full"; \
    rm -rf /tmp/7z /tmp/7z.tar.xz

WORKDIR /app

# ── Python dependencies (cached layer) ───────────────────────────────────────
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── Application ──────────────────────────────────────────────────────────────
COPY . .

# Heroku runs containers as an unprivileged user: make the working folders writable.
RUN mkdir -p /app/data /app/downloads /app/bin \
 && chmod -R a+rwX /app

# Heroku injects $PORT; the bot binds it (status page) before connecting to Telegram.
CMD ["python", "main.py"]
