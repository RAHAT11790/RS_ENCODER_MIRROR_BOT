"""Direct http/https downloader (aiohttp): redirects, resume, retries, optional multi-connection.

Outbound connections only, to the exact URL the user supplied. No listeners, no helper processes."""

import os
import re
from asyncio import TimeoutError as AsyncTimeout, gather, sleep
from urllib.parse import unquote, urlparse

import aiofiles
from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector

from . import LOGGER
from .config import Config
from .task import Cancelled

CHUNK = 2 * 1024 * 1024   # larger reads keep a fast server link saturated with fewer awaits
MIN_SPLIT = 8 * 1024 * 1024
MAX_TRIES = 5
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class DownloadError(Exception):
    pass


def clean_name(name):
    name = unquote(name or "").strip().replace("\\", "_").replace("/", "_").strip(". ")
    return name[:200]


def name_from_disposition(value):
    if not value:
        return ""
    m = re.search(r"filename\*\s*=\s*[^']*'[^']*'([^;]+)", value, re.I)
    if m:
        return clean_name(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"([^"]+)"', value, re.I) or re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    return clean_name(m.group(1).strip()) if m else ""


def _session():
    return ClientSession(
        connector=TCPConnector(
            limit=0,
            ssl=None if not Config.ALLOW_INSECURE_SSL else False,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        ),
        timeout=ClientTimeout(total=None, sock_connect=25, sock_read=120),
        headers={"User-Agent": UA, "Accept-Encoding": "identity"},
    )


async def fetch(url, dest_dir, task, headers=None, out_name=None):
    """Download *url* into *dest_dir*; returns the file path. Progress goes to *task*."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise DownloadError("Only http/https links are supported here.")
    os.makedirs(dest_dir, exist_ok=True)
    fallback = clean_name(urlparse(url).path.rsplit("/", 1)[-1]) or "download"
    state = {"name": clean_name(out_name) or fallback, "range": False, "single": False}
    async with _session() as session:
        resume_from = 0
        last_error = None
        for attempt in range(1, MAX_TRIES + 1):
            task.check_cancel()
            path = os.path.join(dest_dir, state["name"])
            if attempt > 1 or os.path.isfile(path):
                resume_from = os.path.getsize(path) if os.path.isfile(path) and state["range"] else 0
            try:
                extra = {"Range": f"bytes={resume_from}-"} if resume_from else {}
                async with session.get(url, headers={**(headers or {}), **extra}) as resp:
                    if resp.status == 416 and resume_from:
                        task.update(resume_from, resume_from)
                        return path
                    if resp.status in (429, 503) and attempt < MAX_TRIES:
                        retry_after = int(resp.headers.get("Retry-After", "0") or 0)
                        wait = min(retry_after or 3 * attempt, 20)
                        LOGGER.warning(f"HTTP {resp.status}: waiting {wait}s before retry {attempt + 1}/{MAX_TRIES}")
                        last_error = f"HTTP {resp.status}"
                        await sleep(wait)
                        continue
                    if resp.status >= 400:
                        raise DownloadError(f"HTTP {resp.status} {resp.reason}")
                    partial = resp.status == 206
                    if not partial:
                        resume_from = 0
                    state["range"] = partial or resp.headers.get("Accept-Ranges", "").lower() == "bytes"
                    length = int(resp.headers.get("Content-Length", "0") or 0)
                    total = resume_from + length if length else 0
                    if not out_name:
                        disp = name_from_disposition(resp.headers.get("Content-Disposition", ""))
                        if disp:
                            state["name"] = disp
                    path = os.path.join(dest_dir, state["name"])
                    task.name = task.name or state["name"]
                    task.reset_progress(total)
                    task.update(resume_from, total)
                    use_parallel = (
                        Config.DOWNLOAD_CONNECTIONS > 1 and not partial and not resume_from
                        and state["range"] and total >= MIN_SPLIT and not state["single"]
                    )
                    if not use_parallel:
                        await _stream(resp, path, task, resume_from, total)
                        return path
                # ranges are supported: use a few connections for big files
                try:
                    await _parallel(session, url, path, task, headers or {}, total)
                except DownloadError as e:
                    # a CDN may answer range requests with 429/403: fall back to one clean stream
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    state["range"] = False
                    state["single"] = True
                    if attempt >= MAX_TRIES:
                        raise
                    LOGGER.warning(f"parallel download unavailable ({e}); using one connection")
                    await sleep(min(2 * attempt, 8))
                    continue
                except BaseException:
                    # the file was preallocated to its full size: never let a retry believe it is complete
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    raise
                return path
            except Cancelled:
                raise
            except DownloadError:
                raise
            except (ClientError, AsyncTimeout, OSError) as e:
                last_error = e
                LOGGER.warning(f"download retry {attempt}/{MAX_TRIES}: {e}")
                await sleep(min(2 * attempt, 10))
        raise DownloadError(f"Download failed after {MAX_TRIES} tries: {last_error}")


async def _stream(resp, path, task, resume_from, total):
    mode = "ab" if resume_from else "wb"
    done = resume_from
    async with aiofiles.open(path, mode) as f:
        async for chunk in resp.content.iter_chunked(CHUNK):
            task.check_cancel()
            await f.write(chunk)
            done += len(chunk)
            task.update(done, total or None)
    if total and done < total:
        raise ClientError("connection closed before the file was complete")
    if not total:
        if done <= 0:
            raise ClientError("the server returned an empty file")
        task.update(done, done)


async def _parallel(session, url, path, task, headers, total):
    # do not open 8 connections for a file that is only 10 MB: one segment per 4 MB
    parts = max(2, min(Config.DOWNLOAD_CONNECTIONS, max(total // (4 * 1024 * 1024), 2)))
    step = total // parts
    ranges = [(i * step, total - 1 if i == parts - 1 else (i + 1) * step - 1) for i in range(parts)]
    async with aiofiles.open(path, "wb") as f:
        await f.truncate(total)
    state = {"done": 0}
    task.reset_progress(total)

    async def worker(start, end):
        pos, tries = start, 0
        while pos <= end:
            task.check_cancel()
            before = pos
            try:
                async with session.get(url, headers={**headers, "Range": f"bytes={pos}-{end}"}) as resp:
                    if resp.status != 206:
                        if resp.status in (429, 503):
                            raise ClientError(f"HTTP {resp.status}")
                        raise DownloadError(f"server ignored the Range request (HTTP {resp.status})")
                    async with aiofiles.open(path, "r+b") as f:
                        await f.seek(pos)
                        async for chunk in resp.content.iter_chunked(CHUNK):
                            task.check_cancel()
                            if pos + len(chunk) > end + 1:
                                chunk = chunk[: end + 1 - pos]
                            await f.write(chunk)
                            pos += len(chunk)
                            state["done"] += len(chunk)
                            task.update(state["done"], total)
                            if pos > end:
                                break
            except (ClientError, AsyncTimeout, OSError) as e:
                tries += 1
                if tries >= MAX_TRIES:
                    raise DownloadError(f"segment failed: {e}") from e
                await sleep(min(2 * tries, 10))
                continue
            if pos == before:  # 206 with an empty body: retry instead of spinning forever
                tries += 1
                if tries >= MAX_TRIES:
                    raise DownloadError("segment stalled: the server sent no data")
                await sleep(min(2 * tries, 10))

    results = await gather(*(worker(s, e) for s, e in ranges), return_exceptions=True)
    for r in results:
        if isinstance(r, Cancelled):
            raise r
        if isinstance(r, BaseException):
            raise r if isinstance(r, DownloadError) else DownloadError(str(r))
