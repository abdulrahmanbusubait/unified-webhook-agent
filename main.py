# ================= Webhook (Production) =================
from typing import Optional, Dict, Any
import os
import json
import httpx
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel

# --- إعدادات خارجية ---
OPENAI_URL   = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"  # سريع ورخيص نسبياً

# حتى نظهر سعر "SPC" (المؤشر الذي تعتمد عليه) بصورة موحّدة:
SPC_ALIASES = {"SPC", "SPCUSD", "SPCUSD/US DOLLAR", "SPCUSD/US DOLLAR - E"}

# --- متغيرات البيئة ---
SHARED_TOKEN      = os.getenv("SHARED_TOKEN", "")
TELEGRAM_BOT_TOKEN= os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")

app = FastAPI()

# للصحة
@app.get("/health")
async def health():
    return {"status": "ok"}

# نموذج التنبيه القادم من TradingView
class Alert(BaseModel):
    symbol: Optional[str] = None
    price: Optional[float] = None
    interval: Optional[str] = None
    time: Optional[str] = None

def normalize_symbol(sym: Optional[str]) -> str:
    if not sym:
        return "UNKNOWN"
    s = sym.strip().upper()
    # لو أحد الاشتقاقات المعروفة لـ SPC
    if s in SPC_ALIASES or s.startswith("SPCUSD"):
        return "SPC"
    return s

def build_prompt(alert: Alert) -> str:
    """
    نُلزم ChatGPT أن يرجّع JSON منظّم فقط.
    يعتمد على السعر المرسل من TradingView (وهو نفس الذي يظهر على الشارت).
    """
    sym = normalize_symbol(alert.symbol)
    price = alert.price if alert.price is not None else "NA"
    interval = alert.interval or "NA"
    t = alert.time or "NA"

    return f"""
أنت محلل أسواق محترف. قيم الوضع الحالي بدقة واعطِ توصية "آمنة فقط" إن وُجدت.
أعد الإجابة في صيغة JSON **فقط** (لا تضف نصاً خارج JSON) بالشكل التالي تماماً:

{{
  "send": true|false,            // هل نرسل توصية الآن؟
  "reason": "لماذا/ملخص قصير",
  "trend": "صاعد|هابط|عرضي",
  "action": "BUY|SELL|WAIT",
  "entry":  {{"min": number, "max": number}},   // نطاق دخول آمن
  "sl":     number,                              // وقف خسارة
  "tp1":    number,                              // هدف 1
  "tp2":    number,                              // هدف 2 (اختياري)
  "confidence": 0-100                            // ثقة القرار
}}

شروط الأمان:
- لا توصي إن كان الاتجاه غير واضح أو المخاطر مرتفعة (اجعل send=false).
- إن كانت التوصية آمنة فعلاً (send=true) ضع نطاق دخول معقول SL/TP مناسبين.
- لا تخرج عن هيكل JSON المذكور.

المدخلات:
- الرمز: {sym}
- السعر الحالي: {price}
- الإطار الزمني: {interval}
- الوقت: {t}
    """.strip()

async def call_openai(prompt: str) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        # نضمن رجوع JSON فقط
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "أنت خبير تحليل أسواق مالية."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(OPENAI_URL, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        # المحتوى يعود JSON نصي؛ نحوله لقاموس
        return json.loads(content)

def format_telegram_message(alert: Alert, res: Dict[str, Any]) -> str:
    sym = normalize_symbol(alert.symbol)
    price = alert.price if alert.price is not None else "NA"
    interval = alert.interval or "NA"
    trend = res.get("trend", "-")
    action = res.get("action", "WAIT")
    entry = res.get("entry", {})
    entry_min = entry.get("min", "-")
    entry_max = entry.get("max", "-")
    sl = res.get("sl", "-")
    tp1 = res.get("tp1", "-")
    tp2 = res.get("tp2", "-")
    conf = res.get("confidence", "-")
    reason = res.get("reason", "-")

    return (
        f"📊 *Unified Signal*\n"
        f"• Symbol: *{sym}*    | Frame: *{interval}*\n"
        f"• Price: *{price}*\n"
        f"• Trend: *{trend}*\n"
        f"• Action: *{action}*\n"
        f"• Entry: *{entry_min} - {entry_max}*\n"
        f"• SL: *{sl}*   | TP1: *{tp1}*   | TP2: *{tp2}*\n"
        f"• Confidence: *{conf}%*\n"
        f"• Note: {reason}"
    )

async def send_telegram(text: str):
    if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(url, json=payload)

@app.post("/webhook")
async def webhook(alert: Alert, request: Request):
    # التحقق من التوكِن
    token = request.query_params.get("token")
    if token != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # نبني مُدخل التحليل
    prompt = build_prompt(alert)

    # استدعاء ChatGPT مع JSON إلزامي
    try:
        ai = await call_openai(prompt)
    except Exception as e:
        # لا نُسقط الخادم — نعيد ردّاً مفيداً
        return {"status": "error", "where": "openai", "detail": str(e)}

    # نرسل للتيليجرام فقط لو send=true
    send_flag = bool(ai.get("send", False))
    if send_flag:
        msg = format_telegram_message(alert, ai)
        try:
            await send_telegram(msg)
        except Exception as e:
            return {"status": "error", "where": "telegram", "detail": str(e)}

    # استجابة الـ webhook
    return {
        "status": "ok",
        "normalized_symbol": normalize_symbol(alert.symbol),
        "sent": send_flag,
        "ai": ai,   # مفيد للفحص
    }
