"""
Weather Banner Generator — Airlink Distribution DR
FastAPI backend for Railway
Generates both HORIZONTAL and VERTICAL banners
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont
import base64, io, os, logging, traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
BASE = os.path.dirname(os.path.abspath(__file__))

# ── TEMPLATE SELECTION ────────────────────────────────────────────────────────
def select_template(condition_id: int, orientation: str = "horizontal") -> str:
    cid = int(condition_id)
    if 200 <= cid < 300:                       name = "Thunderstorm"
    elif 300 <= cid < 400 or 500 <= cid < 600: name = "Rainny"
    elif cid in [731,751,761,762]:             name = "Sahara"
    elif cid == 800:                           name = "Sunny"
    else:                                      name = "Cloudy"
    suffix = "_Vertical" if orientation == "vertical" else ""
    return f"{name}{suffix}.png"

# ── BOX COORDINATES ───────────────────────────────────────────────────────────
sx, sy = 1672/960, 941/540
def sc(x1,y1,x2,y2): return int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)

BOXES_H = {
    "date_es":    sc(130.42,232.48,364.08,257.23),
    "date_en":    sc(428.33,232.48,661.99,257.23),
    "stat_temp":  sc(72.91, 378.49,189.29,408.60),
    "stat_feels": sc(247.70,378.49,364.08,408.60),
    "stat_hum":   sc(437.89,378.49,520.30,408.60),
    "stat_wind":  sc(589.13,378.49,714.56,408.60),
    "stat_cloud": sc(791.32,379.17,873.73,408.60),
}

BOXES_V = {
    "date_es":    ( 42,  878, 470,  928),
    "date_en":    (470,  878, 899,  928),
    "stat_temp":  ( 50, 1040, 310, 1135),
    "stat_feels": (350, 1040, 600, 1135),
    "stat_hum":   (630, 1040, 900, 1135),
    "stat_wind":  (120, 1295, 440, 1375),
    "stat_cloud": (500, 1295, 840, 1375),
}

# ── FONTS ─────────────────────────────────────────────────────────────────────
def get_font(size):
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        os.path.join(BASE, "DejaVuSans-Bold.ttf"),
    ]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def draw_centered(draw, box, text, font, color):
    x1,y1,x2,y2 = box
    bb = draw.textbbox((0,0), text, font=font)
    tw,th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text((x1+(x2-x1-tw)//2, y1+(y2-y1-th)//2), text, font=font, fill=color)

def draw_fitted(draw, box, text, max_size, min_size, color):
    """Auto-shrink font until text fits in box."""
    x1,y1,x2,y2 = box
    bw,bh = x2-x1, y2-y1
    for size in range(max_size, min_size-1, -1):
        font = get_font(size)
        bb = draw.textbbox((0,0), text, font=font)
        tw,th = bb[2]-bb[0], bb[3]-bb[1]
        if tw <= bw-8:
            draw.text((x1+(bw-tw)//2, y1+(bh-th)//2), text, font=font, fill=color)
            return
    font = get_font(min_size)
    bb = draw.textbbox((0,0), text, font=font)
    tw,th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text((x1+(bw-tw)//2, y1+(bh-th)//2), text, font=font, fill=color)

# ── BANNER GENERATOR ──────────────────────────────────────────────────────────
def generate_banner(data: dict, orientation: str) -> str:
    tpl = select_template(int(data.get("condition_id", 800)), orientation)
    path = os.path.join(BASE, tpl)
    logger.info(f"[{orientation}] Template: {tpl} exists={os.path.exists(path)}")

    if not os.path.exists(path):
        files = os.listdir(BASE)
        raise FileNotFoundError(f"Template not found: {path}. Available: {files}")

    img = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    BLUE  = (37, 92, 170, 255)
    WHITE = (255,255,255,255)

    if orientation == "horizontal":
        boxes    = BOXES_H
        f_stat   = get_font(38)
        f_date_max, f_date_min = 27, 14
    else:
        boxes    = BOXES_V
        f_stat   = get_font(42)
        f_date_max, f_date_min = 24, 13

    # Dates — auto-fit
    draw_fitted(draw, boxes["date_es"], data.get("date_es",""), f_date_max, f_date_min, WHITE)
    draw_fitted(draw, boxes["date_en"], data.get("date_en",""), f_date_max, f_date_min, WHITE)

    # Stats — fixed size
    draw_centered(draw, boxes["stat_temp"],  f"{data.get('temp','--')}°C",    f_stat, BLUE)
    draw_centered(draw, boxes["stat_feels"], f"{data.get('feels','--')}°C",   f_stat, BLUE)
    draw_centered(draw, boxes["stat_hum"],   f"{data.get('humidity','--')}%", f_stat, BLUE)
    draw_centered(draw, boxes["stat_wind"],  f"{data.get('wind','--')} m/s",  f_stat, BLUE)
    draw_centered(draw, boxes["stat_cloud"], f"{data.get('cloud','--')}%",    f_stat, BLUE)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Weather Banner Generator — Airlink DR"}

@app.get("/health")
def health():
    files = os.listdir(BASE)
    pngs = [f for f in files if f.endswith(".png")]
    return {"status": "ok", "templates": pngs}

@app.post("/generate")
async def generate(request: Request):
    """
    POST /generate
    {
      "condition_id": 800,
      "temp": "29.5", "feels": "32.1",
      "humidity": "64", "wind": "4.1", "cloud": "4",
      "date_es": "Lunes, 28 de septiembre de 2026",
      "date_en": "Monday, September 28, 2026"
    }
    Returns: { "horizontal": "base64...", "vertical": "base64...",
               "template": "Sunny", "status": "ok" }
    """
    try:
        data = await request.json()
        logger.info(f"Request: condition_id={data.get('condition_id')}")

        h_b64 = generate_banner(data, "horizontal")
        v_b64 = generate_banner(data, "vertical")

        cid = int(data.get("condition_id", 800))
        tpl = select_template(cid).replace(".png","")

        return JSONResponse({
            "horizontal": h_b64,
            "vertical":   v_b64,
            "template":   tpl,
            "status":     "ok"
        })
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Error: {e}\n{tb}")
        return JSONResponse({"horizontal":"","vertical":"","template":"",
                             "status":f"error: {str(e)}","traceback":tb}, status_code=500)
