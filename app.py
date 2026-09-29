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

def select_template(condition_id: int, vertical: bool = False) -> str:
    cid = int(condition_id)
    suffix = "_Vertical" if vertical else ""
    if 200 <= cid < 300:                     return f"Thunderstorm{suffix}.png"
    if 300 <= cid < 400 or 500 <= cid < 600: return f"Rainny{suffix}.png"
    if cid in [731, 751, 761, 762]:           return f"Sahara{suffix}.png"
    if cid == 800:                            return f"Sunny{suffix}.png"
    return f"Cloudy{suffix}.png"

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

# ── Vertical weather template boxes (per-template, calibrated on 941×1672 native) ──
# ALL coordinates (dates + stats) derived from the dates PPTX (a7648314) text box
# positions — ground truth.  Each template has its own layout: Rainny's stat
# ellipses sit ~29 px lower than the other four, and Sahara is shifted ~5 px right.
# Scale: 941 px / 10.721 cm = 87.77 px/cm  (native 941×1672 template space).
BOXES_V_PER_TEMPLATE = {
    "Sunny": {             # image6, Slide 6 Panel A
        "date_es":    ( 68,  878, 458,  923),
        "date_en":    (483,  878, 873,  923),
        "stat_temp":  ( 80, 1057, 278, 1111),
        "stat_feels": (372, 1057, 570, 1111),
        "stat_hum":   (664, 1057, 862, 1111),
        "stat_wind":  (179, 1311, 377, 1365),
        "stat_cloud": (565, 1311, 763, 1365),
    },
    "Cloudy": {            # image7, Slide 6 Panel C
        "date_es":    ( 68,  871, 458,  916),
        "date_en":    (483,  871, 873,  916),
        "stat_temp":  ( 79, 1057, 277, 1111),
        "stat_feels": (371, 1057, 569, 1111),
        "stat_hum":   (663, 1057, 861, 1111),
        "stat_wind":  (178, 1311, 376, 1365),
        "stat_cloud": (564, 1311, 762, 1365),
    },
    "Rainny": {            # image8, Slide 6 Panel B — stats are LOWER on this template
        "date_es":    ( 68,  905, 458,  950),
        "date_en":    (483,  905, 873,  950),
        "stat_temp":  ( 79, 1085, 277, 1139),
        "stat_feels": (371, 1085, 569, 1139),
        "stat_hum":   (663, 1085, 861, 1139),
        "stat_wind":  (178, 1339, 376, 1393),
        "stat_cloud": (564, 1339, 762, 1393),
    },
    "Thunderstorm": {      # image9, Slide 7 Panel D
        "date_es":    ( 68,  872, 458,  917),
        "date_en":    (482,  872, 872,  917),
        "stat_temp":  ( 79, 1056, 277, 1110),
        "stat_feels": (371, 1056, 569, 1110),
        "stat_hum":   (663, 1056, 861, 1110),
        "stat_wind":  (178, 1310, 376, 1364),
        "stat_cloud": (564, 1310, 762, 1364),
    },
    "Sahara": {            # image10, Slide 7 Panel E
        "date_es":    ( 71,  875, 461,  920),
        "date_en":    (486,  875, 876,  920),
        "stat_temp":  ( 85, 1056, 283, 1110),
        "stat_feels": (377, 1056, 575, 1110),
        "stat_hum":   (669, 1056, 867, 1110),
        "stat_wind":  (184, 1310, 382, 1364),
        "stat_cloud": (570, 1310, 768, 1364),
    },
}

def _get_boxes_v(condition_id: int) -> dict:
    """Return per-template BOXES_V for the given condition_id."""
    cid = int(condition_id)
    if 200 <= cid < 300:                     return BOXES_V_PER_TEMPLATE["Thunderstorm"]
    if 300 <= cid < 400 or 500 <= cid < 600: return BOXES_V_PER_TEMPLATE["Rainny"]
    if cid in [731, 751, 761, 762]:           return BOXES_V_PER_TEMPLATE["Sahara"]
    if cid == 800:                            return BOXES_V_PER_TEMPLATE["Sunny"]
    return BOXES_V_PER_TEMPLATE["Cloudy"]

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

def _render_weather(data: dict, boxes: dict, condition_id: int, vertical: bool) -> bytes:
    tpl = select_template(condition_id, vertical=vertical)
    path = os.path.join(_base_dir(), tpl)
    img = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    BLUE  = (37, 92, 170, 255)
    WHITE = (255, 255, 255, 255)
    # For vertical, use per-template calibrated boxes; for horizontal, use passed boxes
    b = _get_boxes_v(condition_id) if vertical else boxes
    draw_fitted(draw, b["date_es"],    data.get("date_es", ""),          27, WHITE)
    draw_fitted(draw, b["date_en"],    data.get("date_en", ""),          27, WHITE)
    draw_fitted(draw, b["stat_temp"],  f"{data.get('temp','--')}°C",     38, BLUE)
    draw_fitted(draw, b["stat_feels"], f"{data.get('feels','--')}°C",    38, BLUE)
    draw_fitted(draw, b["stat_hum"],   f"{data.get('humidity','--')}%",  38, BLUE)
    draw_fitted(draw, b["stat_wind"],  f"{data.get('wind','--')} m/s",   38, BLUE)
    draw_fitted(draw, b["stat_cloud"], f"{data.get('cloud','--')}%",     38, BLUE)
    # Resize to standard NoviSign resolution
    out_size = (1080, 1920) if vertical else (1920, 1080)
    img = img.resize(out_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def generate_banner(data: dict) -> str:
    cid = int(data.get("condition_id", 800))
    raw = _render_weather(data, BOXES, cid, vertical=False)
    return base64.b64encode(raw).decode()


# ── Weather in-memory + disk cache ────────────────────────────
_weather_h_png: bytes | None = None
_weather_v_png: bytes | None = None

def _weather_disk_path(orientation: str) -> str:
    p = os.path.join(_base_dir(), "weather_cache")
    os.makedirs(p, exist_ok=True)
    return os.path.join(p, f"current_{orientation}.png")

def _get_weather_png(orientation: str) -> bytes | None:
    global _weather_h_png, _weather_v_png
    cached = _weather_h_png if orientation == "h" else _weather_v_png
    if cached:
        return cached
    path = _weather_disk_path(orientation)
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        if orientation == "h":
            _weather_h_png = data
        else:
            _weather_v_png = data
        return data
    return None


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
    global _weather_h_png, _weather_v_png
    try:
        data = await request.json()
        cid  = int(data.get("condition_id", 800))

        # Generate H
        h_raw = _render_weather(data, BOXES, cid, vertical=False)
        _weather_h_png = h_raw
        with open(_weather_disk_path("h"), "wb") as f:
            f.write(h_raw)

        # Generate V (boxes auto-selected per template inside _render_weather)
        v_raw = _render_weather(data, {}, cid, vertical=True)
        _weather_v_png = v_raw
        with open(_weather_disk_path("v"), "wb") as f:
            f.write(v_raw)

        h_b64 = base64.b64encode(h_raw).decode()
        v_b64 = base64.b64encode(v_raw).decode()
        return JSONResponse({
            "image_b64":   h_b64,          # legacy key (horizontal)
            "image_b64_h": h_b64,
            "image_b64_v": v_b64,
            "template":    select_template(cid),
            "template_v":  select_template(cid, vertical=True),
            "status":      "ok",
        })
    except Exception as e:
        return JSONResponse(
            {"image_b64": "", "template": "", "status": f"error: {e}"},
            status_code=500,
        )

@app.get("/weather/horizontal")
def weather_horizontal():
    """NoviSign polls this for the latest horizontal weather banner."""
    png = _get_weather_png("h")
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})

@app.get("/weather/vertical")
def weather_vertical():
    """NoviSign polls this for the latest vertical weather banner."""
    png = _get_weather_png("v")
    if png is None:
        return Response(status_code=204)
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})

@app.get("/health")
def health():
    return {"status": "ok"}
