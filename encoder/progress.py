"""ffmpeg progress parsing shared by the encoder engine."""

import asyncio
import time
from asyncio.subprocess import PIPE

from lite.fmt import clock, readable_size


def _parse_time(val):
    """Parse FFmpeg out_time string (e.g. '00:01:54.816000') into total seconds."""
    try:
        parts = val.strip().split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
    except (TypeError, ValueError):
        pass
    return None


async def run_ffmpeg(cmd, duration=0, task=None, label="encoding", source_size=0):
    """Run *cmd*, feeding accurate video length, size, speed (e.g. 3x, 5x), and ETA into task."""
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)

    cur = {
        "seconds": 0.0,
        "speed_val": 0.0,
        "speed_str": "",
        "fps": "",
        "size": 0,
        "started": time.time(),
        "last_update": 0.0,
    }

    def _sync_task(force=False):
        if task is None:
            return
        now = time.time()
        # Throttle live updates to twice per second unless final force
        if not force and (now - cur["last_update"]) < 0.5:
            return
        cur["last_update"] = now

        sec = cur["seconds"]
        if duration > 0:
            current_sec = min(sec, duration)
            pct = min(max(current_sec / duration * 100.0, 0.0), 100.0)
            len_str = f"{clock(current_sec)} / {clock(duration)}"
            rem_sec = max(duration - current_sec, 0)
            if cur["speed_val"] > 0.05:
                eta_sec = rem_sec / cur["speed_val"]
            else:
                elapsed = now - cur["started"]
                if pct > 1.0:
                    total_est = elapsed / (pct / 100.0)
                    eta_sec = max(total_est - elapsed, 0)
                else:
                    eta_sec = None
        else:
            pct = 0.0
            len_str = clock(sec) if sec > 0 else ""
            eta_sec = None

        if source_size > 0 and cur["size"] > 0:
            size_str = f"{readable_size(cur['size'])} / {readable_size(source_size)}"
        elif source_size > 0:
            size_str = f"— / {readable_size(source_size)}"
        elif cur["size"] > 0:
            size_str = f"{readable_size(cur['size'])}"
        else:
            size_str = "—"

        if cur["speed_val"] > 0:
            speed_disp = f"{cur['speed_val']:.2f}x"
            if cur["fps"] and cur["fps"] not in ("0", "0.0"):
                speed_disp += f" ({cur['fps']} fps)"
        elif cur["speed_str"] and cur["speed_str"] != "N/A":
            speed_disp = cur["speed_str"]
        else:
            elapsed = now - cur["started"]
            if elapsed > 1 and sec > 0:
                speed_disp = f"{sec / elapsed:.2f}x"
            else:
                speed_disp = "—"

        task.set_phase(label, percent=pct, speed=speed_disp, eta=eta_sec, length=len_str, size=size_str)

    async def pump():
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            if key == "out_time":
                # Primary source of truth: accurate string e.g. "00:01:54.816000"
                parsed = _parse_time(value)
                if parsed is not None and parsed >= 0:
                    cur["seconds"] = parsed
            elif key == "out_time_us":
                # Fallback if out_time was not present
                if cur["seconds"] == 0:
                    try:
                        cur["seconds"] = max(int(value) / 1_000_000, 0.0)
                    except (TypeError, ValueError):
                        pass
            elif key == "speed":
                cur["speed_str"] = value
                try:
                    cur["speed_val"] = float(value.replace("x", "").strip())
                except (TypeError, ValueError):
                    pass
            elif key == "fps":
                cur["fps"] = value
            elif key == "total_size":
                try:
                    cur["size"] = int(value)
                except (TypeError, ValueError):
                    pass
            elif key == "progress":
                _sync_task()

    async def drain():
        return await proc.stderr.read()

    async def watch():
        while proc.returncode is None:
            if task is not None and getattr(task, "cancelled", False):
                proc.kill()
                break
            await asyncio.sleep(0.5)
        return await proc.wait()

    try:
        _, err, _ = await asyncio.gather(pump(), drain(), watch())
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise

    _sync_task(force=True)
    return proc.returncode, err.decode(errors="ignore")
