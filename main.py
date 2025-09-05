@app.post("/webhook")
async def webhook(alert: Dict[str, Any], request: Request):
    # تحقق من التوكن
    token = request.query_params.get("token")
    if token != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ---------- Helpers ----------
    def norm_sym(s: str) -> str:
        if not s: return ""
        s = s.upper().strip()
        # تطبيع الأسماء الشائعة
        aliases = {
            "SPCUSD": "SPC",
            "SPC": "SPC",
            "SPCUSD/US DOLLAR": "SPC",
            "ESU2025": "ES",
            "ES": "ES",
            "SPX": "SPX",
            "SPY": "SPY",
            "DX1!": "DX1!",
            "DXY": "DX1!",
            "VX1!": "VX1!",
            "VIX": "VX1!",
        }
        return aliases.get(s, s)

    def to_float(x):
        # يدعم نصًا/رقمًا/نطاق "6484-6488" ⇒ منتصف النطاق
        if x is None: return None
        if isinstance(x, (int, float)): return float(x)
        s = str(x).replace(",", "").strip()
        # نطاقات
        for sep in ["-", "–", "—", " to ", "–", "—"]:
            if sep in s:
                try:
                    a, b = s.split(sep)[0].strip(), s.split(sep)[-1].strip()
                    return (float(a) + float(b)) / 2.0
                except:
                    pass
        # قيمة مفردة
        try: return float(s)
        except: return None

    def pick_first(*keys):
        for k in keys:
            v = alert.get(k)
            if v not in (None, ""): return v
        return None

    # ---------- قراءة الحقول ----------
    raw_symbol = pick_first("symbol", "ticker", "s", "S")
    symbol = norm_sym(raw_symbol or "")

    interval = pick_first("interval", "timeframe", "tf", "Interval") or ""
    price    = to_float(pick_first("price", "close", "p", "Price"))

    # اتجاه الإشارة من أي حقل محتمل
    text_all = " ".join([str(v) for v in alert.values() if isinstance(v, (str,int,float))]).lower()
    recommendation = (pick_first("recommendation","signal","type","position","dir") or "").lower()

    def is_buy(txt):  # يدعم عربي/إنجليزي
        return any(w in txt for w in ["buy","long","شراء","طويل"])
    def is_sell(txt):
        return any(w in txt for w in ["sell","short","بيع","قصير"])

    direction = ""
    if is_buy(recommendation) or is_buy(text_all): direction = "BUY"
    if is_sell(recommendation) or is_sell(text_all): direction = "SELL"

    # SL / TP يمكن أن تأتي بعدة مسميات
    sl  = to_float(pick_first("sl","stop","stop_loss","وقف","وقف_الخسارة","SL"))
    tp1 = to_float(pick_first("tp1","target1","tp","tp_1","الهدف","الهدف_الأول","TP1"))
    tp2 = to_float(pick_first("tp2","target2","tp_2","الهدف_الثاني","TP2"))

    # هل مذكور أنها آمنة؟ (نصًا أو بوجود SL وTP)
    label_note = (pick_first("label","note","comment","Message") or "").lower()
    is_safe = any(w in label_note for w in ["safe","آمنة","مفعل"]) or (sl and tp1)

    # نرفض إن لم تكن توصية قابلة للتنفيذ
    if symbol not in {"SPC","ES","SPX","SPY","DX1!","VX1!"} or direction == "" or not is_safe:
        return {"status":"ignored"}

    # تقدير entry: من price أو mid-range المدخل أو أول نطاق دخول إن وجد
    entry = to_float(pick_first("entry","entry_price","منطقة_الدخول","zone","الدخول","entryZone")) or price

    # إن لم توجد SL/TP نحاول توليدها تحفظيًا من ATR/VWAP (اختياري):
    if (not sl or not tp1):
        # انحرافات تحفظية بسيطة حول السعر الحالي عند غياب المستويات
        # (يمكنك تحسينها لاحقًا بالدمج مع مؤشراتك عبر الحقول المرسلة)
        step = max(2.0, (price or 0) * 0.002)  # ~0.2%
        if direction == "BUY":
            sl  = sl  or round((price or entry) - 3*step, 2)
            tp1 = tp1 or round((price or entry) + 3*step, 2)
            tp2 = tp2 or round(tp1 + 3*step, 2)
        else:
            sl  = sl  or round((price or entry) + 3*step, 2)
            tp1 = tp1 or round((price or entry) - 3*step, 2)
            tp2 = tp2 or round(tp1 - 3*step, 2)

    # صياغة ملخّص موجز
    title = f"{symbol} — توصية آمنة"
    line  = f"{direction} | دخول: {entry} | SL: {sl} | TP1: {tp1} | TP2: {tp2} | الفريم: {interval or 'n/a'}"

    # أولوية SPC: لو هذه إشارة أسهم وتتعارض مع SPC الحديثة، يمكن هنا تطبيق منطق التعارض إن رغبت
    # (اختياري: حافظ على ذاكرة آخر SPC في متغير عالمي/كاش ووسم إشارات الأسهم بانتظار عند التعارض)

    # إرسال لتيليجرام فقط عندما تكون الإشارة آمنة
    try:
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        await httpx.AsyncClient(timeout=10).post(tg_url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"📌 {title}\n{line}",
            "parse_mode": "HTML"
        })
    except Exception:
        pass

    return {"status":"ok","symbol":symbol,"direction":direction,"safe":True}
