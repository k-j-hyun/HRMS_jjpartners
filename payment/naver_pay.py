import os, uuid, hmac, hashlib, time
import httpx

NAVER_BASES = {
    "sandbox": "https://sandbox-pay.naver.com",
    "production": "https://pay.naver.com"
}
API_BASES = {
    "sandbox": "https://sandbox-api.pay.naver.com",   # 예시 엔드포인트(문서 맞춰 수정)
    "production": "https://api.pay.naver.com"
}

ENV = os.getenv("NAVER_PAY_ENV", "sandbox")
PAY_BASE = NAVER_BASES[ENV]
API_BASE = API_BASES[ENV]

CLIENT_ID = os.getenv("NAVER_PAY_CLIENT_ID")         # ← 가맹 Client ID 넣으세요
CLIENT_SECRET = os.getenv("NAVER_PAY_CLIENT_SECRET") # ← Client Secret 넣으세요
MERCHANT_ID = os.getenv("NAVER_PAY_MERCHANT_ID")     # ← 상점(가맹) ID 넣으세요
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

DEPOSIT_AMOUNT = 5000

def _timestamp_ms():
    return str(int(time.time() * 1000))

def naver_auth_headers(body: str = "") -> dict:
    """HMAC 서명(스켈레톤): 실제 규격대로 수정하세요."""
    ts = _timestamp_ms()
    raw = (CLIENT_ID or "") + ts + (body or "")
    signature = hmac.new((CLIENT_SECRET or "").encode(), raw.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Naver-Client-Id": CLIENT_ID or "",
        "X-Naver-Timestamp": ts,
        "X-Naver-Signature": signature,
        "Content-Type": "application/json"
    }

def get_return_urls(merchant_uid: str):
    return {
        "returnUrl": f"{BASE_URL}/payment/naver/return/success?merchant_uid={merchant_uid}",
        "cancelUrl": f"{BASE_URL}/payment/naver/return/cancel?merchant_uid={merchant_uid}",
        "failUrl":   f"{BASE_URL}/payment/naver/return/fail?merchant_uid={merchant_uid}",
    }
