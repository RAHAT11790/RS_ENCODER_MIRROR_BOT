"""Auto thumbnail from TMDb: the official backdrop and the official logo, composited into one
professional card (no text is invented, no image is downloaded twice by accident).

Pipeline
  1. search/multi          -> best title match (year aware)
  2. /{type}/{id}/images   -> best textless backdrop + best transparent logo (PNG)
  3. Pillow                -> 16:9 cover crop, soft vignette, logo centred over a blurred scrim
  4. save                  -> 320x180 JPEG (< 200 kB, Telegram's thumbnail limits)

One lookup per title; every file receives its OWN private copy of the finished JPEG, so
parallel uploads can never delete or overwrite each other's thumbnail."""

import io
import os
import re
import uuid
from asyncio import Lock, sleep, to_thread
from difflib import SequenceMatcher
from urllib.parse import unquote

from aiohttp import ClientSession, ClientTimeout

from . import LOGGER
from .config import Config

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"

COMPOSE_W, COMPOSE_H = 1280, 720
FINAL_W, FINAL_H = 320, 180
MAX_ART_BYTES = 12 * 1024 * 1024
MAX_LOGO_BYTES = 8 * 1024 * 1024

_NOISE = re.compile(
    r"\b(2160p|1080p|720p|480p|360p|4k|uhd|hdr10?|dv|bluray|bdrip|brrip|web[- .]?dl|webrip|hdtv|dvdrip|x26[45]|h\.?26[45]|"
    r"hevc|av1|10bit|8bit|aac|ac3|dd[p+]?\d?(\.\d)?|atmos|esub|msub|multi|dual|hindi|eng|english|jpn|japanese|tamil|telugu|"
    r"audio|sub|subs|subbed|dubbed|complete|season|proper|repack|extended|uncut|nf|amzn|dsnp|hmax|crunchyroll)\b",
    re.I,
)
_EPISODE = re.compile(r"\b(s\d{1,3}\s*e\d{1,4}|s\d{1,3}|e\d{1,4}|ep\.?\s*\d{1,4}|episode\s*\d{1,4}|\d{1,2}x\d{2,4})\b", re.I)

_locks = {}
_master = {}


def token():
    return (Config.TMDB_API_KEY or Config.TMDB_ACCESS_TOKEN or "").strip()


def clean_title(filename):
    """('Kaiju No 8', 2024) from a release name."""
    name = unquote(os.path.basename(filename))
    name = os.path.splitext(name)[0] if re.search(r"\.[a-z0-9]{2,4}$", name, re.I) else name
    year = None
    m = re.search(r"(?<![\d])(19|20)\d{2}(?![\d])", re.sub(r"\[[^\]]*\]", " ", name))
    if m:
        year = m.group(0)
    name = re.sub(r"\[[^\]]*\]|\([^)]*\)|\{[^}]*\}", " ", name)
    cut = _EPISODE.search(name)
    if cut:
        name = name[: cut.start()]
    name = re.sub(r"[._]+", " ", name)
    name = _NOISE.sub(" ", name)
    if year:
        name = name.replace(year, " ")
    name = re.sub(r"[^\w\s']+", " ", name)
    return re.sub(r"\s+", " ", name).strip(), year


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _score(query, candidates):
    q = _norm(query)
    best = 0.0
    for c in candidates:
        c = _norm(c)
        if not c or not q:
            continue
        if q == c:
            return 1.0
        if min(len(q), len(c)) >= 4 and (q in c or c in q):
            best = max(best, 0.9)
        best = max(best, SequenceMatcher(None, q, c).ratio())
    return best


def _auth():
    t = token()
    if len(t) > 50:  # v4 read access token
        return {"Authorization": f"Bearer {t}"}, {}
    return {}, {"api_key": t}


async def _get_json(session, url, params):
    """GET with two polite retries for 429/5xx; every failure returns None (never raises)."""
    headers, extra = _auth()
    for attempt in range(3):
        try:
            async with session.get(url, params={**params, **extra}, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                if resp.status in (429, 500, 502, 503, 504) and attempt < 2:
                    wait = int(resp.headers.get("Retry-After", "0") or 0) or 2 * (attempt + 1)
                    LOGGER.info(f"TMDb {resp.status}: retrying in {wait}s")
                    await sleep(min(wait, 10))
                    continue
                LOGGER.warning(f"TMDb HTTP {resp.status}")
                return None
        except Exception as e:  # noqa: BLE001 (network / JSON)
            if attempt >= 2:
                LOGGER.warning(f"TMDb request failed: {type(e).__name__}: {e}")
                return None
            await sleep(1.5 * (attempt + 1))
    return None


async def _match(session, title, year):
    data = await _get_json(
        session,
        f"{API}/search/multi",
        {"query": title, "include_adult": "false", "language": "en-US", "page": "1"},
    )
    results = [r for r in (data or {}).get("results", []) if r.get("media_type") in ("tv", "movie") and r.get("id")]
    if not results:
        return None
    first = results[0]
    if year:
        for r in results:
            if (r.get("first_air_date") or r.get("release_date") or "").startswith(year):
                first = r
                break
    else:  # no year in the name: prefer the closest title among the first results
        scored = sorted(
            results[:5],
            key=lambda r: -_score(title, [r.get("name"), r.get("title"), r.get("original_name"), r.get("original_title")]),
        )
        best = _score(
            title,
            [scored[0].get("name"), scored[0].get("title"), scored[0].get("original_name"), scored[0].get("original_title")],
        )
        if best >= 0.6:
            first = scored[0]
    return first


def _best(items):
    return sorted(items, key=lambda i: (-(i.get("vote_average") or 0), -(i.get("width") or 0)))[0]


def _pick_backdrop(images):
    """Textless artwork first (our own logo goes on top), then English, then anything."""
    backdrops = [i for i in images.get("backdrops") or [] if i.get("file_path")]
    if not backdrops:
        return None
    for language in (None, "en"):
        group = [i for i in backdrops if i.get("iso_639_1") == language]
        if group:
            return _best(group)["file_path"]
    return _best(backdrops)["file_path"]


def _pick_logo(images):
    """English PNG logos first, wide ones preferred, then any language."""
    logos = [i for i in images.get("logos") or [] if i.get("file_path")]
    if not logos:
        return None

    def rank(item):
        language = item.get("iso_639_1")
        lang_rank = 0 if language == "en" else (1 if language in (None, "") else 2)
        path = str(item.get("file_path") or "").lower()
        png = 0 if path.endswith(".png") else 1
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        ratio = (width / height) if height else 0
        shape = 0 if 1.0 <= ratio <= 7 else 1
        return (lang_rank, png, shape, -(item.get("vote_average") or 0), -width)

    return sorted(logos, key=rank)[0]["file_path"]


async def _artwork(session, first):
    """(backdrop path, logo path) - falls back to the search result when /images is empty."""
    media_type = first.get("media_type") or "movie"
    images = await _get_json(
        session,
        f"{API}/{media_type}/{first['id']}/images",
        {"include_image_language": "en,null"},
    ) or {}
    backdrop = _pick_backdrop(images) or first.get("backdrop_path") or first.get("poster_path")
    logo = _pick_logo(images)
    return backdrop, logo


async def _download(session, url, limit):
    async with session.get(url) as resp:
        if resp.status != 200:
            LOGGER.warning(f"TMDb image HTTP {resp.status}")
            return None
        data = await resp.read()  # read(n) can return a partial chunk: always read the full body
    if not data or len(data) > limit:
        LOGGER.warning(f"TMDb image rejected ({len(data or b'')} bytes)")
        return None
    return data


def _cover(img, size):
    from PIL import Image, ImageOps

    return ImageOps.fit(img.convert("RGB"), size, Image.LANCZOS, centering=(0.5, 0.42))


def _readable_logo(mark):
    """TMDb also stores black-only logos; on dark artwork those would vanish, so invert them."""
    from PIL import Image, ImageStat

    alpha = mark.split()[-1]
    if not alpha.getbbox():
        return mark
    r, g, b = ImageStat.Stat(mark.convert("RGB"), mask=alpha).mean
    if max(r, g, b) < 70:  # monochrome black: draw it as light grey and keep the shape
        light = Image.new("RGBA", mark.size, (246, 246, 246, 0))
        light.putalpha(alpha)
        return light
    return mark


def _compose(backdrop, logo, target):
    """Backdrop + official logo -> one 16:9 JPEG thumbnail (never raises past this point)."""
    from PIL import Image, ImageDraw, ImageFile, ImageFilter

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    base = Image.open(io.BytesIO(backdrop))
    portrait = base.height > base.width * 1.1

    if portrait:  # poster fallback: blurred 16:9 canvas with the poster in the middle
        canvas = _cover(base, (COMPOSE_W, COMPOSE_H)).filter(ImageFilter.GaussianBlur(34))
        poster = base.convert("RGB")
        poster.thumbnail((int(COMPOSE_W * 0.72), COMPOSE_H), Image.LANCZOS)
        canvas.paste(poster, ((COMPOSE_W - poster.width) // 2, (COMPOSE_H - poster.height) // 2))
        logo = None  # a logo over a poster would cover the artwork
    else:
        canvas = _cover(base, (COMPOSE_W, COMPOSE_H))

    canvas = Image.eval(canvas, lambda v: int(v * 0.92))

    if logo:
        try:
            mark = Image.open(io.BytesIO(logo)).convert("RGBA")
            mark = _readable_logo(mark)
            mark.thumbnail((int(COMPOSE_W * 0.56), int(COMPOSE_H * 0.42)), Image.LANCZOS)
            x = (COMPOSE_W - mark.width) // 2
            y = int(COMPOSE_H * 0.45) - mark.height // 2
            # soft dark scrim behind the logo so bright artwork never swallows it
            scrim = Image.new("L", (COMPOSE_W, COMPOSE_H), 0)
            box = (
                max(0, x - 55),
                max(0, y - 35),
                min(COMPOSE_W, x + mark.width + 55),
                min(COMPOSE_H, y + mark.height + 35),
            )
            if box[2] > box[0] and box[3] > box[1]:
                ImageDraw.Draw(scrim).rounded_rectangle(box, radius=90, fill=130)
            scrim = scrim.filter(ImageFilter.GaussianBlur(55))
            dark = Image.new("RGBA", (COMPOSE_W, COMPOSE_H), (0, 0, 0, 255))
            dark.putalpha(scrim)
            canvas = Image.alpha_composite(canvas.convert("RGBA"), dark)
            # dark halo hugging the letter strokes: keeps thin white logos readable
            thick = mark.split()[-1].filter(ImageFilter.MaxFilter(7))
            halo = Image.new("RGBA", mark.size, (0, 0, 0, 0))
            halo.putalpha(thick.point(lambda a: int(a * 0.9)))
            halo = halo.filter(ImageFilter.GaussianBlur(3))
            layer = Image.new("RGBA", (COMPOSE_W, COMPOSE_H), (0, 0, 0, 0))
            layer.paste(halo, (x, y), halo)
            canvas = Image.alpha_composite(canvas, layer)
            # soft drop shadow under the logo
            alpha = mark.split()[-1].point(lambda a: int(a * 0.7))
            shadow = Image.new("RGBA", (COMPOSE_W, COMPOSE_H), (0, 0, 0, 0))
            shadow.paste(Image.new("RGBA", mark.size, (0, 0, 0, 255)), (x, y + 10), alpha)
            shadow = shadow.filter(ImageFilter.GaussianBlur(12))
            canvas = Image.alpha_composite(canvas, shadow)
            canvas.paste(mark, (x, y), mark)
            canvas = canvas.convert("RGB")
        except Exception as e:  # noqa: BLE001 (broken PNG / exotic mode)
            LOGGER.warning(f"TMDb logo skipped: {type(e).__name__}: {e}")
            canvas = canvas.convert("RGB")

    # gentle vignette so the card looks graded, not like a raw screenshot
    mask = Image.new("L", (COMPOSE_W, COMPOSE_H), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((0, 0, COMPOSE_W, COMPOSE_H), fill=72)
    draw.ellipse((-COMPOSE_W * 0.25, -COMPOSE_H * 0.35, COMPOSE_W * 1.25, COMPOSE_H * 1.35), fill=0)
    mask = mask.filter(ImageFilter.GaussianBlur(120))
    canvas = Image.composite(Image.new("RGB", (COMPOSE_W, COMPOSE_H), (0, 0, 0)), canvas, mask)

    canvas.resize((FINAL_W, FINAL_H), Image.LANCZOS).save(target, "JPEG", quality=90, optimize=True)


async def _build_master(session, title, year, work_dir):
    first = await _match(session, title, year)
    if not first:
        return None, None
    backdrop_path, logo_path = await _artwork(session, first)
    if not backdrop_path:
        return None, None
    backdrop = await _download(session, f"{IMG}/w1280{backdrop_path}", MAX_ART_BYTES)
    if not backdrop:
        return None, None
    logo = await _download(session, f"{IMG}/original{logo_path}", MAX_LOGO_BYTES) if logo_path else None
    os.makedirs(os.path.join(work_dir, "_tmdb"), exist_ok=True)
    master = os.path.join(work_dir, "_tmdb", f"{uuid.uuid4().hex[:12]}.jpg")
    try:
        await to_thread(_compose, backdrop, logo, master)
    except Exception as e:  # noqa: BLE001 (corrupt image data): report once, cache as "no artwork"
        try:
            os.remove(master)
        except OSError:
            pass
        LOGGER.warning(f"TMDb composition failed: {type(e).__name__}: {e}")
        return None, None
    return master, {"backdrop": backdrop_path, "logo": logo_path}


async def auto_thumbnail(filename, work_dir):
    """Path of a private thumbnail copy for *filename*, or None. Never raises."""
    if not Config.AUTO_THUMBNAIL or not token():
        return None
    try:
        title, year = clean_title(filename)
        if len(title) < 2:
            return None
        key = (title.lower(), year)
        lock = _locks.setdefault(key, Lock())
        async with lock:  # single flight: other episodes of the same series wait for this one
            master = _master.get(key)
            if master is False:
                return None
            if not (master and os.path.isfile(master)):
                timeout = ClientTimeout(total=40, sock_connect=10)
                async with ClientSession(timeout=timeout) as session:
                    master, art = await _build_master(session, title, year, work_dir)
                if not master:
                    _master[key] = False
                    LOGGER.info(f"TMDb: no artwork for '{title}'")
                    return None
                if len(_master) > 200:
                    _master.clear()
                if len(_locks) > 400:  # keep the single-flight table bounded too
                    for old in [k for k, lock in _locks.items() if not lock.locked()]:
                        _locks.pop(old, None)
                _master[key] = master
                LOGGER.info(
                    f"TMDb thumbnail for '{title}': "
                    + ("backdrop + logo" if art and art.get("logo") else "backdrop")
                )
            private = os.path.join(work_dir, f"thumb_{uuid.uuid4().hex[:12]}.jpg")

            def _copy():
                with open(master, "rb") as src, open(private, "wb") as dst:
                    dst.write(src.read())

            await to_thread(_copy)
            return private
    except Exception as e:  # noqa: BLE001 (never break an upload because of a thumbnail)
        LOGGER.warning(f"TMDb thumbnail failed for {os.path.basename(filename)!r}: {type(e).__name__}: {e}")
        return None
