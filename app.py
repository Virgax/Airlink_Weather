"""
Weather Banner Generator — Airlink Distribution DR
FastAPI — Railway deployment
Horizontal (1672x941) + Vertical (941x1672) per-template coordinates
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
def select_name(condition_id: int) -> str:
    cid = int(condition_id)
    if 200 <= cid < 300:                       return "Thunderstorm"
    if 300 <= cid < 400 or 500 <= cid < 600:  return "Rainny"
    if cid in [731,751,761,762]:               return "Sahara"
    if cid == 800:                             return "Sunny"
    return "Cloudy"

# ── HORIZONTAL BOXES (1672x941, same for all templates) ───────────────────────
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

# ── VERTICAL BOXES (941x1672, per-template calibrated) ───────────────────────
BOXES_V = {
    "Sunny": {
        "date_es":    ( 42,  873, 470,  929),
        "date_en":    (470,  873, 899,  929),
        "stat_temp":  ( 40, 1047, 320, 1123),
        "stat_feels": (340, 1047, 610, 1123),
        "stat_hum":   (620, 1047, 900, 1123),
        "stat_wind":  (120, 1295, 440, 1375),
        "stat_cloud": (500, 1295, 840, 1375),
    },
    "Cloudy": {
        "date_es":    ( 42,  867, 470,  925),
        "date_en":    (470,  867, 899,  925),
        "stat_temp":  ( 40, 1042, 320, 1120),
        "stat_feels": (340, 1042, 610, 1120),
        "stat_hum":   (620, 1042, 900, 1120),
        "stat_wind":  (120, 1290, 440, 1370),
        "stat_cloud": (500, 1290, 840, 1370),
    },
    "Rainny": {
        "date_es":    ( 42,  901, 470,  956),
        "date_en":    (470,  901, 899,  956),
        "stat_temp":  ( 40, 1074, 320, 1149),
        "stat_feels": (340, 1074, 610, 1149),
        "stat_hum":   (620, 1074, 900, 1149),
        "stat_wind":  (120, 1310, 440, 1390),
        "stat_cloud": (500, 1310, 840, 1390),
    },
    "Thunderstorm": {
        "date_es":    ( 42,  865, 470,  924),
        "date_en":    (470,  865, 899,  924),
        "stat_temp":  ( 40, 1047, 320, 1120),
        "stat_feels": (340, 1047, 610, 1120),
        "stat_hum":   (620, 1047, 900, 1120),
        "stat_wind":  (120, 1290, 440, 1370),
        "stat_cloud": (500, 1290, 840, 1370),
    },
    "Sahara": {
        "date_es":    ( 42,  868, 470,  927),
        "date_en":    (470,  868, 899,  927),
        "stat_temp":  ( 40, 1050, 320, 1125),
        "stat_feels": (340, 1050, 610, 1125),
        "stat_hum":   (620, 1050, 900, 1125),
        "stat_wind":  (100, 1295, 450, 1380),
        "stat_cloud": (490, 1295, 850, 1380),
    },
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
    name = select_name(int(data.get("condition_id", 800)))
    suffix = "_Vertical" if orientation == "vertical" else ""
    tpl = f"{name}{suffix}.png"
    path = os.path.join(BASE, tpl)

    logger.info(f"[{orientation}] {tpl} exists={os.path.exists(path)}")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}. Files: {os.listdir(BASE)}")

    img  = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    BLUE  = (37, 92, 170, 255)
    WHITE = (255,255,255,255)

    if orientation == "horizontal":
        boxes = BOXES_H
        fs    = get_font(38)
        dm, dn = 27, 14
    else:
        boxes = BOXES_V[name]
        fs    = get_font(42)
        dm, dn = 24, 13

    draw_fitted (draw, boxes["date_es"],    data.get("date_es",""),          dm, dn, WHITE)
    draw_fitted (draw, boxes["date_en"],    data.get("date_en",""),          dm, dn, WHITE)
    draw_centered(draw, boxes["stat_temp"],  f"{data.get('temp','--')}°C",   fs, BLUE)
    draw_centered(draw, boxes["stat_feels"], f"{data.get('feels','--')}°C",  fs, BLUE)
    draw_centered(draw, boxes["stat_hum"],   f"{data.get('humidity','--')}%",fs, BLUE)
    draw_centered(draw, boxes["stat_wind"],  f"{data.get('wind','--')} m/s", fs, BLUE)
    draw_centered(draw, boxes["stat_cloud"], f"{data.get('cloud','--')}%",   fs, BLUE)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Weather Banner Generator — Airlink DR"}

@app.get("/health")
def health():
    pngs = [f for f in os.listdir(BASE) if f.endswith(".png")]
    return {"status": "ok", "templates": sorted(pngs)}

@app.post("/generate")
async def generate(request: Request):
    try:
        data = await request.json()
        logger.info(f"condition_id={data.get('condition_id')}")
        h = generate_banner(data, "horizontal")
        v = generate_banner(data, "vertical")
        name = select_name(int(data.get("condition_id", 800)))
        return JSONResponse({"horizontal": h, "vertical": v,
                             "template": name, "status": "ok"})
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"{e}\n{tb}")
        return JSONResponse({"horizontal":"","vertical":"","template":"",
                             "status":f"error: {str(e)}","traceback":tb}, status_code=500)
