"""RS Leech Lite entry point:  python main.py

1. picks a supported interpreter (Python 3.10-3.13) and uses .venv when present
2. pre-flight: pip packages from requirements.txt + ffmpeg/7-Zip when available
3. runs the bot in a child process and restarts it after a crash (bounded: it gives up after
   8 quick crashes in a row; there are no keep-alive loops and no other background workers)
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHILD = "RS_LITE_CHILD"
PID_FILE = HERE / ".rs_main.pid"
VENV_PY = HERE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


# ------------------------------------------------------------------ process checks
def _win_process(pid):
    """(alive, image_path) on Windows without ever signalling the process."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False, ""
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return False, ""
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return True, buf.value
        return True, ""
    finally:
        kernel32.CloseHandle(handle)


def _cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="ignore").replace("\0", " ")
    except Exception:  # noqa: BLE001
        return ""


def _is_our_instance(pid):
    if os.name == "nt":
        alive, image = _win_process(pid)
        if not alive:
            return False
        try:
            import psutil

            return "main.py" in " ".join(psutil.Process(pid).cmdline())
        except Exception:  # noqa: BLE001
            return "python" in image.lower()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except Exception:  # noqa: BLE001
        return True
    return "main.py" in _cmdline(pid)


def single_instance():
    try:
        old = int(PID_FILE.read_text().strip())
    except Exception:  # noqa: BLE001
        old = 0
    if old and old != os.getpid() and _is_our_instance(old):
        print(f"[main] another instance is running (PID {old}). Stop it first.", flush=True)
        raise SystemExit(1)
    PID_FILE.write_text(str(os.getpid()))


def _supported_python():
    """wzgram/warpcrypto ship wheels for CPython 3.10-3.13; reuse the venv on newer Pythons."""
    if (3, 10) <= sys.version_info[:2] <= (3, 13):
        return
    if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
        print("[main] switching to the project's Python 3.13 environment ...", flush=True)
        os.execv(str(VENV_PY), [str(VENV_PY), str(HERE / "main.py"), *sys.argv[1:]])
    print(
        "[main] Python %s is not supported by the Telegram library wheels.\n"
        "       Install Python 3.13 and create the environment once:\n"
        "         py -3.13 -m venv .venv\n"
        "         .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        "       Then start with:  .venv\\Scripts\\python.exe main.py" % sys.version.split()[0],
        flush=True,
    )
    raise SystemExit(1)


# ------------------------------------------------------------------ supervisor
def supervise(cmd=None, max_quick_crashes=8, sleep=time.sleep):
    cmd = cmd or [sys.executable, "-u", "-m", "lite"]
    env = dict(os.environ, **{CHILD: "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    quick = 0
    child = {"p": None}

    def stop(*_):
        p = child["p"]
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=15)
            except Exception:  # noqa: BLE001
                p.kill()
        PID_FILE.unlink(missing_ok=True)
        raise SystemExit(0)

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for sig in signals:
        try:
            signal.signal(sig, stop)
        except Exception:  # noqa: BLE001
            pass

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    try:
        while True:
            started = time.time()
            child["p"] = subprocess.Popen(cmd, cwd=str(HERE), env=env, creationflags=flags)
            code = child["p"].wait()
            if code == 0:
                return 0
            if code == 2:
                print("[main] configuration problem - fix config.py / environment variables and start again.", flush=True)
                return 2
            quick = quick + 1 if time.time() - started < 30 else 0
            if quick >= max_quick_crashes:
                print(f"[main] crashed {quick} times in a row (exit code {code}); not restarting. Check log.txt.", flush=True)
                return code or 1
            if code in (-9, 137):
                print("[main] the bot was killed by the system (out of memory?). Lower MAX_CONCURRENT_TASKS.", flush=True)
            delay = min(5 * max(quick, 1), 60)
            print(f"[main] bot stopped (exit code {code}); restarting in {delay}s ...", flush=True)
            sleep(delay)
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    _supported_python()
    single_instance()
    if os.environ.get("RS_SKIP_SETUP", "").strip().lower() not in ("1", "true", "yes"):
        try:
            # attach <project>/bin FIRST: every child process (ffmpeg, 7z, yt-dlp)
            # must resolve the portable tools that install.sh put in that folder
            from bin_bootstrap import attach_bin

            BIN = attach_bin()
            print(f"[setup] runtime tools: {BIN}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[setup] bin/ attach skipped: {exc}", flush=True)
        try:
            from bin_bootstrap import install_system_packages

            # quick PATH check first; the download only runs when a tool is really missing
            install_system_packages()
        except Exception as exc:  # noqa: BLE001
            print(f"[setup] system packages skipped: {exc}", flush=True)
        try:
            from rs_setup import ensure_everything

            ensure_everything()
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[setup] pre-flight skipped: {exc}", flush=True)
    raise SystemExit(supervise())
