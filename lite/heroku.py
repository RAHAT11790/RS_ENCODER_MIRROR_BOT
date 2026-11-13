"""Heroku / web-host support.

* ``start_web()``  - tiny HTTP server on ``$PORT`` (status page + ``/health``).
  A Heroku *web* dyno must bind its port within 60 seconds or it is killed (error R10),
  so the bot starts this server BEFORE it connects to Telegram.
* ``write_cookies_from_env()`` - the dyno disk is wiped on every restart, so yt-dlp
  cookies can be stored in the ``YT_COOKIES`` config var instead of a file.

Outside Heroku (no ``PORT`` variable) nothing is started and nothing changes.
"""

import html
import os
import shutil
import time

from aiohttp import web

from . import LOGGER, START_TIME, VERSION
from .config import Config

try:  # optional: memory / CPU figures on the status page
    import psutil
except Exception:  # noqa: BLE001
    psutil = None


def _uptime():
    seconds = int(time.time() - START_TIME)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    return (f"{days}d " if days else "") + f"{hours:02d}h {minutes:02d}m {secs:02d}s"


def _tools():
    """{tool: bool} - never exposes file paths."""
    try:
        import rsbin

        return {name: bool(rsbin.resolve(name)) for name in ("ffmpeg", "ffprobe", "yt-dlp", "7z")}
    except Exception:  # noqa: BLE001
        return {}


def _metrics():
    data = {"uptime": _uptime(), "version": VERSION}
    try:
        free = shutil.disk_usage(Config.DOWNLOAD_DIR if os.path.isdir(Config.DOWNLOAD_DIR) else ".").free
        data["disk_free_gb"] = round(free / 1024 ** 3, 2)
    except Exception:  # noqa: BLE001
        pass
    if psutil is not None:
        try:
            data["memory_percent"] = psutil.virtual_memory().percent
            data["cpu_percent"] = psutil.cpu_percent(interval=None)
        except Exception:  # noqa: BLE001
            pass
    return data


async def _health(request):
    return web.json_response({"status": "ok", **_metrics(), "tools": _tools()})


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RS ENCODER MIRROR BOT</title>
<style>
:root{{--bg:#f4f7fb;--card:#fff;--text:#0f172a;--muted:#64748b;--line:#e2e8f0;--accent:#0891b2;--ok:#16a34a;--bad:#dc2626}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--card:#111a2e;--text:#e5edf8;--muted:#8da2bf;--line:#22304a;--accent:#22d3ee;--ok:#4ade80;--bad:#f87171}}}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{width:100%;max-width:560px;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:28px}}
h1{{margin:0 0 4px;font-size:1.35rem;letter-spacing:.04em;color:var(--accent)}}
p.sub{{margin:0 0 20px;color:var(--muted);font-size:.92rem}}
.status{{display:inline-flex;align-items:center;gap:8px;font-weight:600;margin-bottom:18px}}
.dot{{width:10px;height:10px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 4px color-mix(in srgb,var(--ok) 25%,transparent)}}
dl{{display:grid;grid-template-columns:auto 1fr;gap:10px 18px;margin:0}}
dt{{color:var(--muted)}} dd{{margin:0;text-align:right;font-variant-numeric:tabular-nums}}
h2{{margin:22px 0 10px;font-size:.8rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
.tools{{display:flex;flex-wrap:wrap;gap:8px}}
.tool{{padding:4px 12px;border-radius:999px;border:1px solid var(--line);font-size:.85rem}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad)}}
footer{{margin-top:22px;color:var(--muted);font-size:.8rem;text-align:center}}
</style></head><body><main>
<h1>RS ENCODER MIRROR BOT</h1>
<p class="sub">Download &bull; Mirror &bull; Encode &bull; Upload</p>
<div class="status"><span class="dot"></span>Online</div>
<dl>{rows}</dl>
<h2>Tools</h2>
<div class="tools">{tools}</div>
<footer>Use the bot inside Telegram &middot; <a href="/health" style="color:inherit">/health</a></footer>
</main></body></html>"""


async def _index(request):
    m = _metrics()
    labels = [
        ("Version", f"v{m['version']}"),
        ("Uptime", m["uptime"]),
        ("Free disk", f"{m['disk_free_gb']} GB" if "disk_free_gb" in m else "n/a"),
        ("Memory", f"{m['memory_percent']}%" if "memory_percent" in m else "n/a"),
        ("CPU", f"{m['cpu_percent']}%" if "cpu_percent" in m else "n/a"),
    ]
    rows = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(str(v))}</dd>" for k, v in labels)
    tools = "".join(
        f'<span class="tool {"ok" if ok else "bad"}">{"✔" if ok else "✖"} {html.escape(name)}</span>'
        for name, ok in _tools().items()
    )
    return web.Response(text=PAGE.format(rows=rows, tools=tools), content_type="text/html")


async def start_web():
    """Bind ``$PORT`` and return the runner (``None`` when not running on a web host)."""
    raw = os.environ.get("PORT", "").strip()
    if not raw.isdigit():
        return None
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/healthz", _health)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(raw)).start()
    LOGGER.info(f"web status page listening on port {raw}")
    return runner


def write_cookies_from_env():
    """Save the ``YT_COOKIES`` variable (Netscape format) to the cookie file yt-dlp reads."""
    content = os.environ.get("YT_COOKIES", "")
    if not content.strip():
        return False
    path = Config.YT_COOKIES_FILE or "cookies.txt"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content.replace("\\n", "\n").strip() + "\n")
        os.chmod(path, 0o600)
        LOGGER.info(f"yt-dlp cookies written to {path} from the YT_COOKIES variable")
        return True
    except OSError as exc:
        LOGGER.warning(f"could not write the cookies file: {exc}")
        return False
