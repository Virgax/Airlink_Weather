"""
Airlink Distribution DR — Banner Generator
Railway FastAPI service
  • /generate              → Weather banners (original)
  • /birthday/generate     → Birthday banners (new)
  • /birthday/clear        → Clear birthday cache
  • /birthday/horizontal   → Serve latest H banner (NoviSign)
  • /birthday/vertical     → Serve latest V banner (NoviSign)
  • /birthday/status       → How many birthdays loaded today
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageDraw, ImageFont
import base64, io, os, json, threading

app = FastAPI()

# ═══════════════════════════════════════════════════════════════
#  WEATHER — original code
# ═══════════════════════════════════════════════════════════════

def select_template(condition_id: int) -> str:
    cid = int(condition_id)
    if 200 <= cid < 300:                   return "Thunderstorm.png"
    if 300 <= cid < 400 or 500 <= cid < 600: return "Rainny.png"
    if cid in [731, 751, 761, 762]:         return "Sahara.png"
    if cid == 800:                          return "Sunny.png"
    return "Cloudy.png"

sx, sy = 1672/960, 941/540
def sc(x1, y1, x2, y2):
    return int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy)

BOXES = {
    "date_es":    sc(130.42, 232.48, 364.08, 257.23),
    "date_en":    sc(428.33, 232.48, 661.99, 257.23),
    "stat_temp":  sc(72.91,  378.49, 189.29, 408.60),
    "stat_feels": sc(247.70, 378.49, 364.08, 408.60),
    "stat_hum":   sc(437.89, 378.49, 520.30, 408.60),
    "stat_wind":  sc(589.13, 378.49, 714.56, 408.60),
    "stat_cloud": sc(791.32, 379.17, 873.73, 408.60),
}

def _base_dir():
    return os.path.dirname(os.path.abspath(__file__))

def get_font(size):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_centered(draw, box, text, font, color):
    x1, y1, x2, y2 = box
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    draw.text((x1 + (x2-x1-tw)//2, y1 + (y2-y1-th)//2), text, font=font, fill=color)

def draw_fitted(draw, box, text, font_size, color, min_size=10):
    """Draw text centered in box, shrinking font if it doesn't fit."""
    x1, y1, x2, y2 = box
    bw, bh = x2-x1, y2-y1
    size = font_size
    while size >= min_size:
        font = get_font(size)
        bb = draw.textbbox((0, 0), text, font=font)
        tw, th = bb[2]-bb[0], bb[3]-bb[1]
        if tw <= bw and th <= bh:
            draw.text((x1 + (bw-tw)//2, y1 + (bh-th)//2), text, font=font, fill=color)
            return
        size -= 1
    font = get_font(min_size)
    bb = draw.textbbox((0, 0), text, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text((x1 + max(0,(bw-tw)//2), y1 + max(0,(bh-th)//2)), text, font=font, fill=color)

def generate_banner(data: dict) -> str:
    tpl = select_template(int(data.get("condition_id", 800)))
    path = os.path.join(_base_dir(), tpl)
    img = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    BLUE  = (37, 92, 170, 255)
    WHITE = (255, 255, 255, 255)
    draw_fitted(draw, BOXES["date_es"],    data.get("date_es", ""),          27, WHITE)
    draw_fitted(draw, BOXES["date_en"],    data.get("date_en", ""),          27, WHITE)
    draw_fitted(draw, BOXES["stat_temp"],  f"{data.get('temp','--')}°C",     38, BLUE)
    draw_fitted(draw, BOXES["stat_feels"], f"{data.get('feels','--')}°C",    38, BLUE)
    draw_fitted(draw, BOXES["stat_hum"],   f"{data.get('humidity','--')}%",  38, BLUE)
    draw_fitted(draw, BOXES["stat_wind"],  f"{data.get('wind','--')} m/s",   38, BLUE)
    draw_fitted(draw, BOXES["stat_cloud"], f"{data.get('cloud','--')}%",     38, BLUE)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


# ── Weather in-memory + disk cache ────────────────────────────
_weather_png: bytes | None = None

def _weather_disk_path():
    p = os.path.join(_base_dir(), "weather_cache")
    os.makedirs(p, exist_ok=True)
    return os.path.join(p, "current.png")

def _get_weather_png() -> bytes | None:
    global _weather_png
    if _weather_png:
        return _weather_png
    # fallback: reload from disk after container restart
    path = _weather_disk_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            _weather_png = f.read()
    return _weather_png


# ═══════════════════════════════════════════════════════════════
#  BIRTHDAY — new code
# ═══════════════════════════════════════════════════════════════

# Thread-safe in-memory cache
_bday_lock = threading.Lock()
_bday_list: list[dict] = []   # [{h: bytes, v: bytes, nombre: str}, ...]
_bday_idx: int = 0            # round-robin pointer

MESES_ABREV = ["ENE-JAN","FEB","MAR","ABR-APR","MAY","JUN",
               "JUL","AGO-AUG","SEP","OCT","NOV","DIC-DEC"]

# ── Zone coordinates (native template pixels) ──────────────────
# HORIZONTAL template: 1671 × 941
H_PHOTO  = (113, 142, 703, 729)    # gray rounded frame interior
H_NAME   = (840, 365, 1440, 440)   # red-bordered name box interior
H_DATE   = (960, 477, 1400, 538)   # green date bar text zone

# VERTICAL template: 941 × 1672
V_PHOTO  = (197, 440, 742, 958)    # gray frame interior
V_NAME   = (115, 1020, 775, 1085)  # red-bordered name box
V_DATE   = (275, 1122, 770, 1176)  # green date bar text zone

def _placeholder_photo(w: int, h: int) -> Image.Image:
    """Gray silhouette placeholder when no employee photo available."""
    img = Image.new("RGB", (w, h), (200, 200, 200))
    d = ImageDraw.Draw(img)
    cx, cy = w // 2, h // 3
    r = min(w, h) // 5
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(150, 150, 150))
    body_top = cy + r
    body_bot = cy + r * 4
    d.rounded_rectangle([cx - r, body_top, cx + r, body_bot],
                        radius=r//2, fill=(150, 150, 150))
    return _round_corners(img, radius=40)

def _round_corners(img: Image.Image, radius: int) -> Image.Image:
    """Apply rounded-corner mask to an RGB image, returns RGBA."""
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([(0, 0), img.size], radius=radius, fill=255)
    img.putalpha(mask)
    return img

def _decode_photo(b64: str | None, w: int, h: int) -> Image.Image:
    """Decode base64 JPEG/PNG from SQL, crop to fill zone, apply rounded corners."""
    if not b64:
        return _placeholder_photo(w, h)
    try:
        raw = base64.b64decode(b64)
        photo = Image.open(io.BytesIO(raw)).convert("RGB")
        # crop-to-fill: scale so shortest side fills the zone, then center-crop
        scale = max(w / photo.width, h / photo.height)
        new_w = int(photo.width  * scale)
        new_h = int(photo.height * scale)
        photo = photo.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - w) // 2
        top  = (new_h - h) // 2
        photo = photo.crop((left, top, left + w, top + h))
        return _round_corners(photo, radius=40)
    except Exception:
        return _placeholder_photo(w, h)

def _format_date(day: int, month: int) -> str:
    """Return short date string for the banner date bar. E.g. '01 OCT'"""
    return f"{day:02d}  {MESES_ABREV[month-1]}"

def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def _generate_birthday_pair(
    foto_b64: str | None,
    nombre: str,
    apellido1: str,
    apellido2: str,
    day: int,
    month: int,
) -> tuple[bytes, bytes]:
    """Build (horizontal_png, vertical_png) for one employee."""
    primer_nombre = nombre.split()[0] if nombre else nombre
    nombre_completo = f"{primer_nombre} {apellido1}".strip().upper()
    date_text = _format_date(day, month)

    BLACK = (0, 0, 0, 255)
    WHITE = (255, 255, 255, 255)

    # ── HORIZONTAL ───────────────────────────────────────────
    h_tpl = Image.open(os.path.join(_base_dir(), "Cumpleanos_Horizontal.png")).convert("RGBA")
    hd = ImageDraw.Draw(h_tpl)

    x1, y1, x2, y2 = H_PHOTO
    photo_h = _decode_photo(foto_b64, x2-x1, y2-y1)
    h_tpl.paste(photo_h, (x1, y1), photo_h if photo_h.mode == "RGBA" else None)

    draw_fitted(hd, H_NAME, nombre_completo, 120, BLACK, min_size=20)
    draw_fitted(hd, H_DATE, date_text,         60, WHITE, min_size=60)

    # ── VERTICAL ─────────────────────────────────────────────
    v_tpl = Image.open(os.path.join(_base_dir(), "Cumpleanos_Vertical.png")).convert("RGBA")
    vd = ImageDraw.Draw(v_tpl)

    x1, y1, x2, y2 = V_PHOTO
    photo_v = _decode_photo(foto_b64, x2-x1, y2-y1)
    v_tpl.paste(photo_v, (x1, y1), photo_v if photo_v.mode == "RGBA" else None)

    draw_fitted(vd, V_NAME, nombre_completo, 120, BLACK, min_size=20)
    draw_fitted(vd, V_DATE, date_text,         60, WHITE, min_size=60)

    # Resize to standard digital-signage resolution for NoviSign
    h_tpl = h_tpl.resize((1920, 1080), Image.LANCZOS)
    v_tpl = v_tpl.resize((1080, 1920), Image.LANCZOS)

    return _png_bytes(h_tpl), _png_bytes(v_tpl)


# ── Birthday endpoints ─────────────────────────────────────────

@app.post("/birthday/generate")
async def birthday_generate(request: Request):
    """
    Power Automate calls this once per employee who has a birthday today.
    Body (JSON):
        {
          "foto_b64":  "...",        # base64 photo from SP (null OK)
          "nombre":    "JUAN",
          "apellido1": "PEREZ",
          "apellido2": "GARCIA",    # can be ""
          "dia":       15,           # integer day
          "mes":       6             # integer month (1-12)
        }
    """
    global _bday_idx
    try:
        data = await request.json()
        foto_b64  = data.get("foto_b64")   # may be None
        nombre    = data.get("nombre",    "").strip()
        apellido1 = data.get("apellido1", "").strip()
        apellido2 = data.get("apellido2", "").strip()
        dia       = int(data.get("dia", 1))
        mes       = int(data.get("mes", 1))
        primer_nombre = nombre.split()[0] if nombre else nombre

        h_png, v_png = _generate_birthday_pair(
            foto_b64, nombre, apellido1, apellido2, dia, mes
        )

        # Persist to disk so images survive a container restart
        _disk_dir = os.path.join(_base_dir(), "birthday_cache")
        os.makedirs(_disk_dir, exist_ok=True)
        idx_on_disk = len(_bday_list)  # before append
        with open(os.path.join(_disk_dir, f"h_{idx_on_disk}.png"), "wb") as f:
            f.write(h_png)
        with open(os.path.join(_disk_dir, f"v_{idx_on_disk}.png"), "wb") as f:
            f.write(v_png)

        with _bday_lock:
            _bday_list.append({
                "h":      h_png,
                "v":      v_png,
                "nombre": f"{primer_nombre} {apellido1}",
            })
            _bday_idx = 0  # reset rotation pointer on each new add

        return JSONResponse({
            "status":           "ok",
            "nombre":           f"{primer_nombre} {apellido1}",
            "total_birthdays":  len(_bday_list),
            "h_b64":            base64.b64encode(h_png).decode(),
            "v_b64":            base64.b64encode(v_png).decode(),
        })
    except Exception as e:
        return JSONResponse({"status": f"error: {e}"}, status_code=500)


@app.post("/birthday/clear")
async def birthday_clear(request: Request):
    """
    Power Automate calls this when 0 employees have a birthday today.
    Wipes the in-memory cache so NoviSign shows nothing.
    """
    global _bday_idx
    with _bday_lock:
        _bday_list.clear()
        _bday_idx = 0
    # Wipe disk cache so yesterday's images don't come back on restart
    _disk_dir = os.path.join(_base_dir(), "birthday_cache")
    if os.path.isdir(_disk_dir):
        import glob
        for f in glob.glob(os.path.join(_disk_dir, "*.png")):
            os.remove(f)
    return JSONResponse({"status": "ok", "cleared": True})


def _reload_from_disk():
    """Reload birthday images from disk cache (called after a container restart)."""
    global _bday_idx
    _disk_dir = os.path.join(_base_dir(), "birthday_cache")
    if not os.path.isdir(_disk_dir):
        return
    import glob, re
    pairs = {}
    for path in glob.glob(os.path.join(_disk_dir, "*.png")):
        m = re.match(r"([hv])_(\d+)\.png$", os.path.basename(path))
        if m:
            orientation, idx = m.group(1), int(m.group(2))
            pairs.setdefault(idx, {})[orientation] = open(path, "rb").read()
    for idx in sorted(pairs):
        entry = pairs[idx]
        if "h" in entry and "v" in entry:
            _bday_list.append({"h": entry["h"], "v": entry["v"], "nombre": f"employee_{idx}"})
    _bday_idx = 0

def _next_banner(orientation: str) -> bytes | None:
    """Round-robin through the birthday list. Reloads from disk if memory is empty."""
    global _bday_idx
    with _bday_lock:
        if not _bday_list:
            _reload_from_disk()
        if not _bday_list:
            return None
        entry = _bday_list[_bday_idx % len(_bday_list)]
        _bday_idx = (_bday_idx + 1) % len(_bday_list)
        return entry[orientation]


@app.get("/birthday/horizontal")
def birthday_horizontal():
    """
    NoviSign polls this fixed URL.
    Returns the current horizontal birthday banner as image/png.
    Cycles through multiple employees on each request.
    Returns 204 No Content when no birthdays today.
    """
    png = _next_banner("h")
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/birthday/vertical")
def birthday_vertical():
    """
    NoviSign polls this fixed URL (for portrait TVs).
    Returns 204 No Content when no birthdays today.
    """
    png = _next_banner("v")
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/birthday/status")
def birthday_status():
    """Debug: shows how many birthday banners are loaded."""
    with _bday_lock:
        names = [e["nombre"] for e in _bday_list]
    return JSONResponse({"total": len(names), "employees": names})


# ═══════════════════════════════════════════════════════════════
#  SHARED ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "ok", "service": "Airlink DR Banner Generator"}

@app.post("/generate")
async def generate(request: Request):
    global _weather_png
    try:
        data = await request.json()
        b64 = generate_banner(data)
        # Cache PNG in memory and on disk for NoviSign polling
        raw = base64.b64decode(b64)
        _weather_png = raw
        with open(_weather_disk_path(), "wb") as f:
            f.write(raw)
        return JSONResponse({
            "image_b64": b64,
            "template":  select_template(int(data.get("condition_id", 800))),
            "status":    "ok",
        })
    except Exception as e:
        return JSONResponse(
            {"image_b64": "", "template": "", "status": f"error: {e}"},
            status_code=500,
        )

@app.get("/weather/current")
def weather_current():
    """
    NoviSign polls this fixed URL for the latest weather banner.
    Returns 204 if no banner has been generated yet today.
    """
    png = _get_weather_png()
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})

@app.get("/health")
def health():
    return {"status": "ok"}
