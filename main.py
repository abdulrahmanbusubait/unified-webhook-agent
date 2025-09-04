# ================== Webhook (Production) ==================
from typing import Dict, Any
import json
import httpx
import os
from fastapi import HTTPException

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"  # سريع ورخيص نسبيًا

# الأسماء الشائعة لرمز SPC (حتى نظهر سطر "سعر SPC الحالي")
SPC_ALIASES = {"SPC", "SPCUSD", "SPCUSD/US DOLLAR", "SPCUSD/US DOLLAR - E" }

async def _openai_safe_decision(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    يطلب من ChatGPT تحليل آمن ويُرجع JSON مُهيكلًا يحتوي على (safe / action / levels ...)
    لا تُغيّر صيغة الـ JSON لكي يسهل فحصها لاحقًا.
    """
    sys = (
        "أنت خبير تداول احترافي. المطلوب منك فقط تقييم مدى أمان الصفقة وفق شروط صارمة: "
        "الصفقة الآمنة هي التي يتوافق فيها الاتجاه العام مع إشارة الدخول الحالية، مع وقف خسارة منطقي "
        "ومخاطرة لا تتجاوز 1% من رأس المال ونسبة عائد/مخاطرة ≥ 1.5. "
        "أخرج دائمًا استجابة JSON فقط بدون أي نص إضافي."
    )

    usr = f"""
المعطيات:
- الرمز: {payload.get('symbol')}
- السعر الحالي: {payload.get('price')}
- الفاصل الزمني: {payload.get('interval')}
- الوقت: {payload.get('time')}

أعد كائن JSON بهذه الصيغة فقط:
{{
  "safe": true|false,
  "action": "buy"|"sell"|"wait",
  "confidence": 0-100,
  "reason": "سبب مختصر",
  "levels": {{
    "entry": [أرقام دخول مقترحة],
    "stop": رقم,
    "targets": [أهداف ربح]
  }}
}}
    """.strip()

    headers = {
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }

    body = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": usr},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(OPENAI_URL, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)


def _format_telegram_message(symbol: str, price: Any, interval: str, result: Dict[str, Any]) -> str:
    action_map = {"buy": "شراء", "sell": "بيع", "wait": "انتظار"}
    action_ar = action_map.get(result.get("action"), "غير محدد")
    levels = result.get("levels", {})
    entry = levels.get("entry", [])
    stop = levels.get("stop")
    targets = levels.get("targets", [])

    lines = [
        "⚡️ *توصية آمنة* (Auto-Agent)",
        f"• الرمز: *{symbol}*",
        f"• الفاصل الزمني: *{interval}*",
        f"• السعر الحالي: *{price}*",
        f"• الإجراء: *{action_ar}*",
        f"• الثقة: *{result.get('confidence', 0)}%*",
        f"• السبب: {result.get('reason', '—')}",
    ]
    if entry:
        lines.append(f"• دخول: `{', '.join(str(x) for x in entry)}`")
    if stop is not None:
        lines.append(f"• وقف خسارة: `{stop}`")
    if targets:
        lines.append(f"• أهداف: `{', '.join(str(x) for x in targets)}`")

    # إذا كان الرمز من SPC نضيف سطر توضيحي صغير (اختياري)
    if (symbol or "").upper() in SPC_ALIASES:
        lines.append("• ملاحظة: السعر أعلاه مأخوذ مباشرة من شارت *SPC* (قيمة التنبيه).")

    return "\n".join(lines)


@app.post("/webhook")
async def webhook(alert: Alert, request: Request):
    # 1) حماية بالتوكن
    token = request.query_params.get("token")
    if token != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2) قراءة بيانات التنبيه (السعر من الشارت المرسل عبر TradingView)
    payload = {
        "symbol": (alert.symbol or "").strip(),
        "price": alert.price,
        "interval": (alert.interval or "").strip(),
        "time": alert.time,
    }

    # 3) طلب قرار آمن من ChatGPT (JSON صارم)
    try:
        result = await _openai_safe_decision(payload)
    except Exception as e:
        # سجل ولا توقف — نعيد حالة ok لكن بدون إرسال
        return {"status": "error", "step": "openai", "detail": str(e)}

    # 4) الشروط التي نعتبرها "توصية آمنة" لإرسال التنبيه
    is_safe = bool(result.get("safe"))
    action = (result.get("action") or "").lower()
    confidence = int(result.get("confidence") or 0)

    # نجعلها مشددة: آمنة + (شراء/بيع) + ثقة ≥ 60
    if is_safe and action in {"buy", "sell"} and confidence >= 60:
        text = _format_telegram_message(
            symbol=payload["symbol"],
            price=payload["price"],
            interval=payload["interval"],
            result=result,
        )
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                tg_url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            )
        return {"status": "ok", "sent": True, "action": action, "confidence": confidence}
    else:
        # تم تجاهل التنبيه لأنه غير آمن (أو انتظار)
        return {
            "status": "ok",
            "sent": False,
            "reason": "not_safe_or_low_confidence_or_wait",
            "decision": result,
        }
# ==========================================================
