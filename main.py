# main.py
import os
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import httpx

SHARED_TOKEN = os.getenv("SHARED_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

app = FastAPI()

class Alert(BaseModel):
    # الحقول الشائعة التي ترسلها TradingView (أي حقل إضافي سيتجاهله الموديل تلقائياً)
    symbol: str | None = None
    price: str | float | None = None
    time: str | None = None
    exchange: str | None = None
    interval: str | None = None
    kind: str | None = None
    type: str | None = None
    label: str | None = None
    v: int | None = None
    note: str | None = None
    # حقول اختيارية لأهداف/وقف إن أرسلتها لاحقاً
    sl: float | None = None
    tp1: float | None = None
    tp2: float | None = None

def format_message(a: Alert) -> str:
    dir_map = {"BUY": "شراء", "SELL": "بيع"}
    head = f"🚨 إشارة {dir_map.get(str(a.type).upper(), a.type)}" if a.type else "🚨 تنبيه"
    lines = [head]
    if a.symbol:   lines.append(f"📈 الرمز: {a.symbol}")
    if a.exchange: lines.append(f"🏦 السوق: {a.exchange}")
    if a.interval: lines.append(f"⏱ الإطار: {a.interval}")
    if a.price is not None: lines.append(f"💵 السعر: {a.price}")
    if a.time:     lines.append(f"🕒 الوقت: {a.time}")
    if a.note:     lines.append(f"📝 ملاحظة: {a.note}")
    # أهداف ووقف (اختياري)
    extras = []
    if a.sl is not None:  extras.append(f"⛔️ وقف: {a.sl}")
    if a.tp1 is not None: extras.append(f"🎯 هدف1: {a.tp1}")
    if a.tp2 is not None: extras.append(f"🎯 هدف2: {a.tp2}")
    if extras: lines.append(" — ".join(extras))
    return "\n".join(lines)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request, tok: str):
    # تحقق من التوكِن الممرَّر في رابط الويبهوك ?tok=
    if tok != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

    data = await request.json()
    try:
        alert = Alert(**data) if isinstance(data, dict) else Alert()
    except Exception:
        alert = Alert()

    text = format_message(alert)

    # إرسال إلى تيليجرام (إن كانت المتغيرات مضبوطة)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and text:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, data=payload)

    # استجابة نجاح لـ TradingView
    return {"ok": True}
