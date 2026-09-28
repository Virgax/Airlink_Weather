---
title: Weather Banner Airlink DR
emoji: 🌤️
colorFrom: blue
colorTo: yellow
sdk: docker
pinned: false
license: mit
---

# Weather Banner Generator — Airlink Distribution DR

## API

**GET** `/health` → `{"status": "ok"}`

**POST** `/generate`
```json
{
  "condition_id": 800,
  "temp": "29.5",
  "feels": "32.1",
  "humidity": "64",
  "wind": "4.1",
  "cloud": "4",
  "date_es": "Martes, 14 de abril de 2026",
  "date_en": "Tuesday, April 14, 2026"
}
```

**Response:**
```json
{"image_b64": "iVBORw0KGgo...", "template": "Sunny.png", "status": "ok"}
```
