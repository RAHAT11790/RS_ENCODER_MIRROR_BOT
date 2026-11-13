"""Archive extraction (7-Zip when installed, pure-Python zip/tar fallback) and big-file splitting."""

import asyncio
import os
import re
import shutil
import tarfile
import time
import zipfile
from asyncio import create_subprocess_exec, gather, get_running_loop, wait_for
from asyncio.subprocess import DEVNULL, PIPE
from contextlib import suppress

from . import LOGGER
from .fmt import readable_size
from .task import Cancelled

ARCHIVE_EXT = (
    ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    ".gz", ".bz2", ".xz", ".zst", ".iso", ".001",
)


class PasswordRequired(Exception):
    """The archive is encrypted and needs the (correct) password."""


_PASSWORD_HINTS = (
    "wrong password", "password required", "passphrase", "enter password", "bad password",
    "can not open encrypted", "cannot open encrypted", "data error in encrypted",
    "encrypted file", "crc failed in encrypted", "incorrect passphrase",
)


def _needs_password(text):
    low = (text or "").lower()
    return any(hint in low for hint in _PASSWORD_HINTS)


def is_archive(path):
    low = path.lower()
    return low.endswith(ARCHIVE_EXT) or low.rsplit(".", 1)[-1].startswith("part1") or ".part01." in low


def find_bsdtar():
    """bsdtar (libarchive) reads RAR too; on Windows it ships as System32\\tar.exe."""
    if os.name == "nt":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        exe = os.path.join(root, "System32", "tar.exe")
        return exe if os.path.isfile(exe) else None
    return shutil.which("bsdtar")


def find_7z():
    """7-Zip from rsbin (bin/ first), then PATH, then the usual Windows install folders."""
    try:
        import rsbin
        resolved = rsbin.resolve("7z")
        if resolved:
            return resolved
    except Exception:
        pass
    for name in ("7z", "7zz", "7za"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        folders = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]
        for folder in folders:
            if folder:
                for sub in ("7-Zip", os.path.join("Programs", "7-Zip")):
                    exe = os.path.join(folder, sub, "7z.exe")
                    if os.path.isfile(exe):
                        return exe
    return None


def _has_files(dest):
    for _root, _dirs, files in os.walk(dest):
        if files:
            return True
    return False


def _safe_target(dest, name):
    """Reject archive members that would escape the extraction folder (Zip Slip)."""
    target = os.path.realpath(os.path.join(dest, name))
    root = os.path.realpath(dest)
    if os.path.commonpath([root, target]) != root:
        raise ValueError(f"unsafe archive member: {name}")
    return target


def _py_extract(path, dest, password=None, task=None):
    os.makedirs(dest, exist_ok=True)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            members = z.infolist()
            total_size = sum(m.file_size for m in members) or 1
            encrypted = any(member.flag_bits & 0x1 for member in members)
            for member in members:
                _safe_target(dest, member.filename)
            if encrypted and not password:
                raise PasswordRequired()
            extracted = 0
            t0 = time.time()
            last_up = 0.0
            for idx, member in enumerate(members, 1):
                if task and getattr(task, "cancelled", False):
                    raise Cancelled()
                try:
                    z.extract(member, dest, pwd=password.encode() if password else None)
                except RuntimeError as e:
                    if encrypted or _needs_password(str(e)):
                        raise PasswordRequired() from e
                    raise
                extracted += member.file_size
                now = time.time()
                if task and (now - last_up) >= 0.5:
                    last_up = now
                    pct = min(extracted / total_size * 100.0, 99.9)
                    el = now - t0
                    spd = extracted / el if el > 0.5 else 0
                    eta_v = (total_size - extracted) / spd if spd > 0 else None
                    task.set_phase(
                        "extracting",
                        percent=pct,
                        speed=f"{readable_size(spd)}/s" if spd else None,
                        eta=eta_v,
                        size=f"{readable_size(extracted)} / {readable_size(total_size)}",
                    )
        if task:
            task.set_phase("extracting", 100.0)
        return True

    if tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            members = t.getmembers()
            total_size = sum(m.size for m in members) or 1
            extracted = 0
            t0 = time.time()
            last_up = 0.0
            for idx, member in enumerate(members, 1):
                if task and getattr(task, "cancelled", False):
                    raise Cancelled()
                _safe_target(dest, member.name)
                try:
                    t.extract(member, dest, filter="data")
                except TypeError:
                    t.extract(member, dest)
                extracted += member.size
                now = time.time()
                if task and (now - last_up) >= 0.5:
                    last_up = now
                    pct = min(extracted / total_size * 100.0, 100.0)
                    el = now - t0
                    spd = extracted / el if el > 0.5 else 0
                    eta_v = (total_size - extracted) / spd if spd > 0 else None
                    task.set_phase(
                        "extracting",
                        percent=pct,
                        speed=f"{readable_size(spd)}/s" if spd else None,
                        eta=eta_v,
                        size=f"{readable_size(extracted)} / {readable_size(total_size)}",
                    )
        if task:
            task.set_phase("extracting", 100.0)
        return True

    if path.lower().endswith(".7z"):
        try:
            import py7zr
        except ImportError:
            return False
        try:
            with py7zr.SevenZipFile(path, mode="r", password=password) as z:
                for name in z.getnames():
                    _safe_target(dest, name)
                if task:
                    task.set_phase("extracting 7z", percent=50.0)
                z.extractall(path=dest)
        except Exception as e:  # noqa: BLE001 - py7zr reports wrong/missing passwords in several ways
            if password or _needs_password(str(e)) or type(e).__name__ in ("PasswordRequired", "CrcError"):
                raise PasswordRequired() from e
            raise
        if task:
            task.set_phase("extracting", 100.0)
        return True

    return False


async def extract(path, dest, task=None, password=None):
    """Extract *path* into *dest* with live progress. Raises PasswordRequired when password is missing/wrong."""
    os.makedirs(dest, exist_ok=True)
    archive_size = os.path.getsize(path) if os.path.isfile(path) else 0
    t0 = time.time()

    if task is not None:
        task.set_status("Extract")
        task.set_phase("extracting", 0.0, size=f"0B / {readable_size(archive_size)}")

    exe = find_7z()
    if exe:
        # -bsp1 writes progress updates to stdout (percentages like 15%, 50%, etc.)
        # -bso0 suppresses file-by-file log spam so stdout is strictly the progress stream
        cmd = [exe, "x", path, f"-o{dest}", "-y", "-bsp1", "-bso0"]
        cmd.append(f"-p{password}" if password else "-p")
        proc = await create_subprocess_exec(*cmd, stdin=DEVNULL, stdout=PIPE, stderr=PIPE)

        cur_pct = 0.0
        last_update = 0.0

        async def pump_7z():
            nonlocal cur_pct, last_update
            buf = ""
            while True:
                chunk = await proc.stdout.read(128)
                if not chunk:
                    break
                text = chunk.decode(errors="ignore")
                # 7-Zip separates progress lines with \r or \n
                buf = (buf + text)[-256:]
                matches = re.findall(r"(\d+)%", buf)
                if matches:
                    try:
                        p = min(max(float(matches[-1]), 0.0), 100.0)
                        cur_pct = p
                        now = time.time()
                        if task and (now - last_update) >= 0.5:
                            last_update = now
                            elapsed = now - t0
                            done_bytes = int(archive_size * (p / 100.0))
                            spd = done_bytes / elapsed if elapsed > 0.5 else 0
                            rem = max(archive_size - done_bytes, 0)
                            eta = rem / spd if spd > 0 else None
                            spd_str = f"{readable_size(spd)}/s" if spd else ""
                            info_str = f"{readable_size(done_bytes)} / {readable_size(archive_size)}" if archive_size else f"{p:.0f}%"
                            task.set_phase("extracting", percent=p, speed=spd_str, eta=eta, size=info_str)
                    except Exception:
                        pass

        async def drain_err():
            return await proc.stderr.read()

        async def watch_cancel():
            while proc.returncode is None:
                if task and getattr(task, "cancelled", False):
                    proc.kill()
                    break
                await asyncio.sleep(0.5)
            return await proc.wait()

        try:
            _, err_bytes, _ = await wait_for(gather(pump_7z(), drain_err(), watch_cancel()), timeout=6 * 3600)
        except BaseException:
            with suppress(Exception):
                proc.kill()
                await proc.wait()
            raise

        if task and getattr(task, "cancelled", False):
            raise Cancelled()

        message = (err_bytes or b"").decode(errors="ignore")
        if proc.returncode == 0:
            if task:
                task.set_phase("extracting", 100.0)
            return True

        LOGGER.warning(f"7z failed ({proc.returncode}): {message[:200]}")
        if _needs_password(message):
            raise PasswordRequired()
        if _has_files(dest):
            LOGGER.warning("7z finished with errors (likely symlinks); keeping extracted files")
            if task:
                task.set_phase("extracting", 100.0)
            return True

    # Fallback to bsdtar if available
    tar = find_bsdtar()
    if tar and (path.lower().endswith(".rar") or not exe):
        cmd = [tar, "-xf", path, "-C", dest]
        if password:
            cmd += ["--passphrase", password]
        proc = await create_subprocess_exec(*cmd, stdin=DEVNULL, stdout=DEVNULL, stderr=PIPE)
        try:
            _, err = await wait_for(proc.communicate(), timeout=6 * 3600)
        except BaseException:
            with suppress(Exception):
                proc.kill()
                await proc.wait()
            raise
        if proc.returncode == 0:
            if task:
                task.set_phase("extracting", 100.0)
            return True
        message = err.decode(errors="ignore")
        LOGGER.warning(f"bsdtar failed ({proc.returncode}): {message[:200]}")
        if _needs_password(message):
            raise PasswordRequired()
        if _has_files(dest):
            LOGGER.warning("bsdtar finished with errors (likely symlinks); keeping extracted files")
            if task:
                task.set_phase("extracting", 100.0)
            return True
        if path.lower().endswith(".rar"):
            if "encrypted" in message.lower():
                raise RuntimeError("Encrypted RAR needs 7-Zip.")
            return False

    loop = get_running_loop()
    try:
        return await loop.run_in_executor(None, _py_extract, path, dest, password, task)
    except PasswordRequired:
        raise
    except Exception as e:  # noqa: BLE001
        LOGGER.error(f"python extract failed: {e}")
        return False


def split_file(path, part_size):
    """Split a big file into numbered parts (name.ext.001, .002 ...); returns the part paths."""
    parts = []
    with open(path, "rb") as src:
        index = 1
        while True:
            chunk_path = f"{path}.{index:03d}"
            written = 0
            with open(chunk_path, "wb") as out:
                while written < part_size:
                    data = src.read(min(8 * 1024 * 1024, part_size - written))
                    if not data:
                        break
                    out.write(data)
                    written += len(data)
            if written == 0:
                os.remove(chunk_path)
                break
            parts.append(chunk_path)
            index += 1
            if written < part_size:
                break
    return parts
