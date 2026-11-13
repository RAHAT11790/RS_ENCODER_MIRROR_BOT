#!/usr/bin/env bash
# ============================================================================
# RS LEECH LITE - ROOTLESS PORTABLE DEPENDENCY INSTALLER
#   * no root / no sudo required
#   * every tool lands in ./bin and is used by main.py through PATH
#   * Android Termux + Linux ARM64 + Linux AMD64
# Official sources only:
#   yt-dlp   -> github.com/yt-dlp/yt-dlp releases
#   ffmpeg   -> github.com/BtbN/FFmpeg-Builds releases
#   7-Zip    -> www.7-zip.org official tarballs
# ============================================================================
set +e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="$APP_DIR/bin"
TMP_DIR="$APP_DIR/.install_tmp"
mkdir -p "$BIN_DIR" "$TMP_DIR"

ARCH="$(uname -m)"
OS="$(uname -s)"
case "$ARCH" in
    aarch64|arm64) ARCH="arm64" ;;
    x86_64|amd64)  ARCH="amd64" ;;
    *) echo "[ERROR] Unsupported architecture: $ARCH"; exit 1 ;;
esac

IS_TERMUX=0
case "${PREFIX:-}" in
    */com.termux/files/usr) IS_TERMUX=1 ;;
esac

log() { printf '[install] %s\n' "$*"; }

download_file() {
    URL="$1"; OUTPUT="$2"
    rm -f "$OUTPUT"
    if command -v curl >/dev/null 2>&1; then
        if curl -fLsS --retry 2 --connect-timeout 20 "$URL" -o "$OUTPUT" && [ -s "$OUTPUT" ]; then
            return 0
        fi
    fi
    if command -v wget >/dev/null 2>&1; then
        if wget -q --tries=2 --timeout=20 "$URL" -O "$OUTPUT" && [ -s "$OUTPUT" ]; then
            return 0
        fi
    fi
    echo "[FAILED] download: $URL"
    rm -f "$OUTPUT"
    return 1
}

extract_binary() {
    ARCHIVE="$1"; TARGET="$2"; NAMES="$3"
    python3 - "$ARCHIVE" "$TARGET" "$NAMES" <<'PY'
import os, sys, tarfile, shutil
archive, target, names = sys.argv[1:4]
wanted = set(names.split(","))
try:
    os.makedirs(target, exist_ok=True)
    with tarfile.open(archive, "r:xz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = os.path.basename(member.name)
            if name not in wanted:
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            destination = os.path.join(target, name)
            with source, open(destination, "wb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(destination, 0o755)
            print("[extracted]", name)
    for name in wanted:
        if not os.path.isfile(os.path.join(target, name)):
            raise RuntimeError("missing binary: " + name)
except Exception as exc:
    print("[extraction error]", exc)
    sys.exit(1)
PY
}

has_command() { command -v "$1" >/dev/null 2>&1; }

install_termux_packages() {
    echo "[android] checking Termux packages"
    has_command pkg || { echo "[ERROR] pkg unavailable"; return 1; }
    MISSING=""
    has_command ffmpeg || MISSING="$MISSING ffmpeg"
    has_command 7zz || has_command 7z || MISSING="$MISSING 7zip"
    if [ -n "$MISSING" ]; then
        log "Termux packages:$MISSING"
        pkg update -y || true
        pkg install -y $MISSING
    fi
}

install_ytdlp() {
    if [ -x "$BIN_DIR/yt-dlp" ] && "$BIN_DIR/yt-dlp" --version >/dev/null 2>&1; then
        log "yt-dlp already installed"
        return 0
    fi
    if has_command yt-dlp; then
        log "system yt-dlp available"
        return 0
    fi
    log "installing yt-dlp"
    URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    if download_file "$URL" "$BIN_DIR/yt-dlp"; then
        chmod +x "$BIN_DIR/yt-dlp"
        if "$BIN_DIR/yt-dlp" --version >/dev/null 2>&1; then
            log "yt-dlp installed"
            return 0
        fi
        rm -f "$BIN_DIR/yt-dlp"
    fi
    echo "[FAILED] yt-dlp"
    return 1
}

install_ffmpeg_linux() {
    if has_command ffmpeg && has_command ffprobe; then
        log "system ffmpeg available"
        return 0
    fi
    if [ -x "$BIN_DIR/ffmpeg" ] && "$BIN_DIR/ffmpeg" -version >/dev/null 2>&1; then
        log "portable ffmpeg already installed"
        return 0
    fi
    log "installing portable ffmpeg ($ARCH)"
    API="https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
    JSON="$TMP_DIR/ffmpeg-release.json"
    download_file "$API" "$JSON" || return 1
    ASSET_URL="$(python3 - "$JSON" "$ARCH" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    expected = {
        "amd64": "ffmpeg-master-latest-linux64-gpl.tar.xz",
        "arm64": "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
    }[sys.argv[2]]
    for asset in data.get("assets", []):
        if asset.get("name") == expected:
            print(asset.get("browser_download_url", ""))
            break
except Exception:
    pass
PY
)"
    [ -z "$ASSET_URL" ] && { echo "[FAILED] no compatible ffmpeg release"; return 1; }
    ARCHIVE="$TMP_DIR/ffmpeg.tar.xz"
    download_file "$ASSET_URL" "$ARCHIVE" || return 1
    EXTRACT_DIR="$TMP_DIR/ffmpeg"; mkdir -p "$EXTRACT_DIR"
    extract_binary "$ARCHIVE" "$EXTRACT_DIR" "ffmpeg,ffprobe" || return 1
    cp "$EXTRACT_DIR/ffmpeg" "$BIN_DIR/ffmpeg"
    cp "$EXTRACT_DIR/ffprobe" "$BIN_DIR/ffprobe"
    chmod +x "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe"
    if "$BIN_DIR/ffmpeg" -version >/dev/null 2>&1 && "$BIN_DIR/ffprobe" -version >/dev/null 2>&1; then
        log "ffmpeg installed"
        return 0
    fi
    rm -f "$BIN_DIR/ffmpeg" "$BIN_DIR/ffprobe"
    echo "[FAILED] ffmpeg execution test"
    return 1
}

install_7zip_linux() {
    if has_command 7zz || has_command 7z; then
        log "system 7-Zip available"
        return 0
    fi
    if [ -x "$BIN_DIR/7zz" ] && "$BIN_DIR/7zz" i >/dev/null 2>&1; then
        log "portable 7-Zip already installed"
        return 0
    fi
    log "installing portable 7-Zip ($ARCH)"
    case "$ARCH" in
        amd64) URL="https://www.7-zip.org/a/7z2501-linux-x64.tar.xz" ;;
        arm64) URL="https://www.7-zip.org/a/7z2501-linux-arm64.tar.xz" ;;
    esac
    ARCHIVE="$TMP_DIR/7zip.tar.xz"
    download_file "$URL" "$ARCHIVE" || return 1
    EXTRACT_DIR="$TMP_DIR/7zip"; mkdir -p "$EXTRACT_DIR"
    extract_binary "$ARCHIVE" "$EXTRACT_DIR" "7zz,7zzs" || return 1
    SOURCE="$EXTRACT_DIR/7zz"
    [ -f "$SOURCE" ] || SOURCE="$EXTRACT_DIR/7zzs"
    cp "$SOURCE" "$BIN_DIR/7zz"
    cp "$SOURCE" "$BIN_DIR/7z"
    cp "$SOURCE" "$BIN_DIR/7za"
    chmod +x "$BIN_DIR/7zz" "$BIN_DIR/7z" "$BIN_DIR/7za"
    if "$BIN_DIR/7zz" i >/dev/null 2>&1; then
        log "7-Zip installed (7zz, 7z, 7za -> bin/)"
        return 0
    fi
    rm -f "$BIN_DIR/7zz" "$BIN_DIR/7z" "$BIN_DIR/7za"
    echo "[FAILED] 7-Zip execution test"
    return 1
}

YTDLP_STATUS=0
FFMPEG_STATUS=0
ZIP_STATUS=0

install_ytdlp || YTDLP_STATUS=1

if [ "$IS_TERMUX" -eq 1 ]; then
    install_termux_packages || true
else
    install_ffmpeg_linux || FFMPEG_STATUS=1
    install_7zip_linux || ZIP_STATUS=1
fi

# Persist the runtime path so the bot and every child process use ./bin first.
printf '%s\n' "$BIN_DIR" > "$APP_DIR/.bin_path"
export PATH="$BIN_DIR:$PATH"

echo
echo "================================================"
echo " DEPENDENCY REPORT  ($OS / $ARCH)"
echo "================================================"
for ITEM in ffmpeg ffprobe 7zz yt-dlp; do
    if [ -x "$BIN_DIR/$ITEM" ]; then
        echo "[portable] $ITEM"
    elif has_command "$ITEM"; then
        echo "[system]   $ITEM"
    elif [ "$ITEM" = "7zz" ] && has_command 7z; then
        echo "[system]   7z (alternative)"
    else
        echo "[missing]  $ITEM"
    fi
done
echo "================================================"
[ "$YTDLP_STATUS" -ne 0 ] && echo "[WARNING] yt-dlp unavailable"
echo "[DONE] runtime tools live in $BIN_DIR"
rm -rf "$TMP_DIR"
exit 0
