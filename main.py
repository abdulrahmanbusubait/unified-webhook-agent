
from fastapi import FastAPI, Request, HTTPException
import os, time, json, hmac, hashlib

app = FastAPI(title="Unified Webhook Agent")

# بيئة العمل
SHARED_TOKEN = os.getenv("SHARED_TOKEN", "CHANGE_ME")
AGENT_FORWARD_URL = os.getenv("AGENT_FORWARD_URL", "")
FORWARD_HMAC_SECRET = os.getenv("FORWARD_HMAC_SECRET", "")

def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

@app.get("/health")
def health():
    return {"status": "ok", "time": int(time.time())}

@app.post("/webhook/tv")
async def tv(request: Request):
    token = request.query_params.get("token")
    if token != SHARED_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw_body = await request.body()
    content_type = request.headers.get("content-type","")

    try:
        body = json.loads(raw_body.decode("utf-8")) if "json" in content_type else {"message": raw_body.decode("utf-8")}
    except Exception:
        body = {"message": raw_body.decode("utf-8", errors="ignore")}

    event = {"received_at": int(time.time()), "source": "tradingview", "payload": body}

    os.makedirs("logs", exist_ok=True)
    with open("logs/events.log", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    if AGENT_FORWARD_URL:
        import httpx
        headers = {"content-type": "application/json"}
        data = json.dumps(event, ensure_ascii=False).encode("utf-8")
        if FORWARD_HMAC_SECRET:
            headers["X-Signature"] = sign(FORWARD_HMAC_SECRET, data)
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(AGENT_FORWARD_URL, content=data, headers=headers)
        return {"ok": True, "forwarded": True}
    return {"ok": True, "forwarded": False}
