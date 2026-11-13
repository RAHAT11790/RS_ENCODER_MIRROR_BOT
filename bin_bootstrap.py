"""Rootless runtime setup for RS Leech Lite.

The user never needs root:  ``install.sh`` downloads portable binaries into ``./bin``
(yt-dlp, ffmpeg/ffprobe, 7-Zip).  This module

1. puts ``<project>/bin`` at the FRONT of ``PATH`` for the bot and every child
   process (ffmpeg, 7z, yt-dlp), so the tools that live in that folder are the ones
   the bot actually runs;
2. runs ``install.sh`` once when a tool is still missing (network permitting).

Nothing here opens a listener, starts a service, or downloads a random binary:
the installer only pulls the three official upstream releases documented in
COMPLIANCE.md.
"""

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
INSTALLER = ROOT / "install.sh"
MARK = ROOT / ".install_done"


def _log(msg):
    print(f"[bootstrap] {msg}", flush=True)


def _bin_dir():
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    return BIN_DIR


def attach_bin():
    """Make <project>/bin the first PATH entry (idempotent, inherited by children)."""
    target = str(_bin_dir())
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if not parts or parts[0] != target:
        os.environ["PATH"] = os.pathsep.join([target] + [p for p in parts if p != target])
    try:
        (ROOT / ".bin_path").write_text(target + "\n", encoding="utf-8")
    except OSError:
        pass
    return target


def have(name):
    """True when the tool exists either in ./bin or anywhere on PATH."""
    attach_bin()
    if (BIN_DIR / name).is_file() and os.access(BIN_DIR / name, os.X_OK):
        return True
    return shutil.which(name) is not None


def _have_7z():
    if have("7zz") or have("7z") or have("7za"):
        return True
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                for sub in ("7-Zip", os.path.join("Programs", "7-Zip")):
                    if os.path.isfile(os.path.join(base, sub, "7z.exe")):
                        return True
    return False


def missing_tools():
    missing = []
    if not (have("ffmpeg") and have("ffprobe")):
        missing.append("ffmpeg")
    if not _have_7z():
        missing.append("7zip")
    if not have("yt-dlp"):
        missing.append("yt-dlp")
    return missing


def run_installer(timeout=900):
    """Run install.sh without root; returns True when it finished successfully."""
    if os.name == "nt" or not INSTALLER.is_file():
        return False
    bash = shutil.which("bash")
    if not bash:
        return False
    _log("running install.sh (rootless portable tools -> ./bin)")
    try:
        proc = subprocess.run(
            [bash, str(INSTALLER)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        _log(f"install.sh could not run: {exc}")
        return False
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    if tail:
        print(tail, flush=True)
    attach_bin()
    return proc.returncode == 0


def sync_7z_aliases():
    """Ensure bin/7z and bin/7za exist if bin/7zz (or system 7z) is available."""
    target = None
    for name in ("7zz", "7z", "7za"):
        p = BIN_DIR / name
        if p.is_file() and os.access(p, os.X_OK):
            target = p
            break
    if not target:
        for name in ("7zz", "7z", "7za"):
            found = shutil.which(name)
            if found:
                for alias in ("7z", "7zz", "7za"):
                    dst = BIN_DIR / alias
                    if not dst.exists():
                        try:
                            shutil.copy2(found, dst)
                            os.chmod(dst, 0o755)
                        except Exception:
                            pass
                return True
        return False
    for alias in ("7z", "7za", "7zz"):
        dst = BIN_DIR / alias
        if not dst.exists() and target.exists():
            try:
                shutil.copy2(target, dst)
                os.chmod(dst, 0o755)
            except Exception:
                pass
    return True


def download_portable_7z():
    """Download portable 7-Zip directly via Python without root or bash."""
    import platform
    import urllib.request
    import tarfile

    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        url = "https://www.7-zip.org/a/7z2501-linux-x64.tar.xz"
    elif arch in ("aarch64", "arm64"):
        url = "https://www.7-zip.org/a/7z2501-linux-arm64.tar.xz"
    elif os.name == "nt":
        url = "https://www.7-zip.org/a/7zr.exe"
    else:
        return False

    _bin_dir()
    _log(f"downloading rootless portable 7-Zip ({arch}) from {url} ...")
    if os.name == "nt":
        dst = BIN_DIR / "7z.exe"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dst, "wb") as out:
                shutil.copyfileobj(resp, out)
            return True
        except Exception as exc:
            _log(f"7-Zip download error: {exc}")
            return False

    tmp_tar = BIN_DIR / "7z_tmp.tar.xz"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_tar, "wb") as out:
            shutil.copyfileobj(resp, out)

        with tarfile.open(tmp_tar, "r:xz") as tar:
            for member in tar.getmembers():
                base = os.path.basename(member.name)
                if base in ("7zz", "7zzs"):
                    src = tar.extractfile(member)
                    if src:
                        dest = BIN_DIR / "7zz"
                        with src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
                        os.chmod(dest, 0o755)
                        break
        sync_7z_aliases()
        _log("portable 7-Zip installed into bin/ successfully")
        return True
    except Exception as exc:
        _log(f"portable 7-Zip download error: {exc}")
        return False
    finally:
        try:
            tmp_tar.unlink(missing_ok=True)
        except Exception:
            pass


def install_system_packages():
    """Attach ./bin and (when needed) run the rootless installer once."""
    attach_bin()
    sync_7z_aliases()
    if os.getenv("AUTO_INSTALL_SYSTEM", "1").strip().lower() in ("0", "false", "no"):
        _log("AUTO_INSTALL_SYSTEM=0 -> skipping tool check")
        return
    missing = missing_tools()
    if not missing:
        _log("runtime tools found (bin/ or PATH)")
        return
    _log("missing: " + ", ".join(missing))
    if "7zip" in missing:
        if download_portable_7z():
            sync_7z_aliases()
            missing = missing_tools()
            if not missing:
                _log("all tools now satisfied")
                return
    if os.name == "nt":
        _log("Windows: run install.sh in Git Bash/WSL or install ffmpeg, 7-Zip and yt-dlp manually")
        return
    if MARK.exists() and not os.getenv("FORCE_INSTALL"):
        _log("install.sh already ran once; run it manually if a tool is still missing")
        return
    if run_installer():
        try:
            MARK.write_text("ok\n", encoding="utf-8")
        except OSError:
            pass
        sync_7z_aliases()
        still = missing_tools()
        if still:
            _log("still missing after install: " + ", ".join(still))
    else:
        _log("install.sh failed; trying python download fallback")
        if "7zip" in missing:
            download_portable_7z()


if __name__ == "__main__":
    install_system_packages()
