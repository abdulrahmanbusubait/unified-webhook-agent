
# unified-webhook-agent

Webhook موحّد لاستقبال جميع تنبيهات TradingView وتحليلها أو إعادة توجيهها لاحقًا.

## خطوات النشر على Render
1. أنشئ مستودع جديد في GitHub وارفع ملفات المشروع.
2. اربط المستودع مع Render.
3. اضبط المتغير البيئي `SHARED_TOKEN` بكلمة مرور قوية.
4. احصل على رابط الـ Webhook النهائي:
```
https://<service>.onrender.com/webhook/tv?token=<SHARED_TOKEN>
```

## مثال رسالة تنبيه من TradingView
```json
{
  "symbol": "{{ticker}}",
  "interval": "{{interval}}",
  "price": {{close}},
  "kind": "SPC"
}
```
