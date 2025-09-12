from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    question: str
    digest: Dict[str, Any]

class ChatReply(BaseModel):
    reply: str

SYSTEM_PROMPT = """You are a flight-data analyst for ArduPilot/PX4 MAVLink telemetry.

You will receive:
- a natural-language question, and
- a compact JSON "digest" of one flight with arrays:
  alt: [{t, alt_m}]
  gps: [{t, fix, sats}]
  gpos: [{t, lat, lon, rel_alt_m}]
  events: [{t, severity, text}]
  meta: {…} (optional start/end timestamps or other notes)

Conventions:
- t is milliseconds (ms). Use it as the timeline reference. If you convert to seconds, say so.
- Units: altitude[m], rel_alt_m[m], speed[m/s] (if present), voltage[V] (if present).
- GPS fix: fix < 3 ⇒ no 3D fix; 3 ⇒ 3D; 5/6 ⇒ RTK float/fixed.
- STATUSTEXT severity: 0–3 are critical (treat as "critical").
- Use only data present in the digest. If a value isn't available, say "Not available".
- Be crisp and cite times using t (ms). 1 decimal place where useful.

Reasoning recipes (use flexibly, not rigid rules):
- Highest altitude = max of alt[].alt_m; else max of gpos[].rel_alt_m.
- Flight time = meta.end_ms - meta.start_ms if provided; else (max t - min t across streams).
- First GPS loss = first t where gps.fix < 3.
- Critical errors = events with severity ≤ 3 OR text containing FAILSAFE, GPS, EKF, BATTERY, CRASH, VIBRATION.
- Anomalies to notice: long gaps (>2000 ms) in gps/gpos; sudden rel_alt_m jumps (>10 m between successive samples); noisy fix oscillation; clusters of WARN/ERROR.

Output format (must follow exactly):
1) A short natural-language answer (2–6 sentences), direct and specific.
2) A fenced JSON block with this schema (include only keys you can support; use null when unknown):
{
  "metrics": {
    "max_altitude_m": number|null,
    "max_altitude_t_ms": number|null,
    "flight_time_s": number|null,
    "first_gps_loss_t_ms": number|null
  },
  "events": {
    "critical": [{"t_ms": number, "severity": number, "text": string}],
    "gps_loss_windows": [{"start_t_ms": number, "end_t_ms": number|null}]
  },
  "anomalies": [
    {"t_ms": number, "type": "gap"|"altitude_jump"|"gps_instability"|"other", "detail": string}
  ],
  "notes": string
}
No extra prose outside those two sections.
"""

@app.post("/chat", response_model=ChatReply)
def chat(req: ChatRequest):
    try:
        user_content = f"Question: {req.question}\n\nDigest JSON:\n{req.digest}"
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=900,
        )
        text = resp.choices[0].message.content.strip()
        return {"reply": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))