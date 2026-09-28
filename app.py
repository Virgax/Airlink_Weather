"""
Weather Banner Generator — Airlink Distribution DR
Hugging Face Space — FastAPI backend
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw, ImageFont
import base64, io, os, json

app = FastAPI()

# ── TEMPLATE SELECTION ────────────────────────────────────────────────────────
def select_template(condition_id: int) -> str:
    cid = int(condition_id)
    if 200 <= cid < 300:   return "Thunderstorm.png"
    if 300 <= cid < 400 or 500 <= cid < 600: return "Rainny.png"
    if cid in [731,751,761,762]: return "Sahara.png"
    if cid == 800:         return "Sunny.png"
    return "Cloudy.png"

# ── BOX COORDINATES (PDF annotations → 1672x941) ─────────────────────────────
sx, sy = 1672/960, 941/540
def sc(x1,y1,x2,y2): return int(x1*sx),int(y1*sy),int(x2*sx),int(y2*sy)

BOXES = {
    "date_es":    sc(130.42,232.48,364.08,257.23),
    "date_en":    sc(428.33,232.48,661.99,257.23),
    "stat_temp":  sc(72.91, 378.49,189.29,408.60),
    "stat_feels": sc(247.70,378.49,364.08,408.60),
    "stat_hum":   sc(437.89,378.49,520.30,408.60),
    "stat_wind":  sc(589.13,378.49,714.56,408.60),
    "stat_cloud": sc(791.32,379.17,873.73,408.60),
}

def get_font(size):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
              "DejaVuSans-Bold.ttf"]:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

def draw_centered(draw, box, text, font, color):
    x1,y1,x2,y2 = box
    bb = draw.textbbox((0,0), text, font=font)
    tw,th = bb[2]-bb[0], bb[3]-bb[1]
    draw.text((x1+(x2-x1-tw)//2, y1+(y2-y1-th)//2), text, font=font, fill=color)

def generate_banner(data: dict) -> str:
    tpl = select_template(int(data.get("condition_id", 800)))
    path = os.path.join(os.path.dirname(__file__), tpl)
    img = Image.open(path).convert("RGBA")
    draw = ImageDraw.Draw(img)
    BLUE  = (37,92,170,255)
    WHITE = (255,255,255,255)
    f27, f38 = get_font(27), get_font(38)
    draw_centered(draw, BOXES["date_es"],    data.get("date_es",""),           f27, WHITE)
    draw_centered(draw, BOXES["date_en"],    data.get("date_en",""),           f27, WHITE)
    draw_centered(draw, BOXES["stat_temp"],  f"{data.get('temp','--')}°C",     f38, BLUE)
    draw_centered(draw, BOXES["stat_feels"], f"{data.get('feels','--')}°C",    f38, BLUE)
    draw_centered(draw, BOXES["stat_hum"],   f"{data.get('humidity','--')}%",  f38, BLUE)
    draw_centered(draw, BOXES["stat_wind"],  f"{data.get('wind','--')} m/s",   f38, BLUE)
    draw_centered(draw, BOXES["stat_cloud"], f"{data.get('cloud','--')}%",     f38, BLUE)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()

# ── ENDPOINTS ─────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "Weather Banner Generator — Airlink DR"}

@app.post("/generate")
async def generate(request: Request):
    try:
        data = await request.json()
        b64 = generate_banner(data)
        return JSONResponse({"image_b64": b64,
                             "template": select_template(int(data.get("condition_id",800))),
                             "status": "ok"})
    except Exception as e:
        return JSONResponse({"image_b64":"","template":"","status":f"error: {e}"}, status_code=500)

@app.get("/health")
def health():
    return {"status": "ok"}
