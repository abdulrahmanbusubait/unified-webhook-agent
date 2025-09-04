@app.post("/webhook")
async def webhook(alert: Alert, request: Request):
    # تحقق من التوكن لحماية الخادم
    token = request.query_params.get("token")
    if token != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # إعداد بيانات التنبيه
    data = {
        "symbol": alert.symbol,
        "price": alert.price,
        "interval": alert.interval,
        "time": alert.time
    }

    # إرسال البيانات إلى ChatGPT Agent لتحليلها
    analysis_prompt = f"""
    حلل السوق الآن للرمز {alert.symbol} بسعر {alert.price} وعلى فريم {alert.interval}.
    أعطني جدول توصيات آمن يحتوي على:
    - الاتجاه الحالي
    - مناطق الدخول المقترحة
    - وقف الخسارة
    - أهداف جني الأرباح
    - الإجراء الحالي (شراء/بيع/انتظار).
    """

    # الاتصال بـ OpenAI Agent (ChatGPT)
    response = await httpx.AsyncClient().post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json"
        },
        json={
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "أنت خبير تحليل أسواق مالية"},
                {"role": "user", "content": analysis_prompt}
            ]
        }
    )

    result = response.json()
    recommendation = result["choices"][0]["message"]["content"]

    # إرسال التوصية تلقائياً إلى تيليجرام
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    await httpx.AsyncClient().post(telegram_url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": recommendation,
        "parse_mode": "Markdown"
    })

    return {"status": "ok", "message": "Alert processed and recommendation sent"}

