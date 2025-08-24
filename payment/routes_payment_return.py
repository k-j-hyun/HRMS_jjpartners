from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import httpx, json, os

from payment.naver_pay import API_BASE, naver_auth_headers
from app.models.database import get_db, JobApplication

router = APIRouter(prefix="/payment/naver/return", tags=["payment-return"])

@router.get("/success", response_class=HTMLResponse)
async def payment_success(merchant_uid: str, request: Request, db: Session = Depends(get_db)):
    # 1) 주문 찾기 (payment_id)
    app_row = db.query(JobApplication).filter(JobApplication.payment_id == merchant_uid).first()
    if not app_row:
        return HTMLResponse("<h3>주문 정보를 찾을 수 없습니다.</h3>", status_code=404)

    # 2) 결제 승인(검증) 호출 — 실제 스펙으로 교체
    payload = {
        "merchantId": os.getenv("NAVER_PAY_MERCHANT_ID", ""),
        "merchantUid": merchant_uid,
        "amount": app_row.deposit_amount or 5000
    }
    headers = naver_auth_headers(json.dumps(payload, ensure_ascii=False))
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{API_BASE}/v1/payments/confirm", headers=headers, json=payload)
        ok = r.status_code == 200
        data = r.json() if ok else {"code": r.status_code, "body": r.text}

    if not ok:
        return HTMLResponse(f"<h3>결제 승인 실패</h3><pre>{data}</pre>", status_code=400)

    # 3) 성공 처리
    app_row.deposit_paid = True
    db.add(app_row)
    db.commit()

    return HTMLResponse("""
      <html><body style="font-family:sans-serif">
      <h3>결제가 완료되었습니다.</h3>
      <script>setTimeout(function(){ window.location.href='/my-applications'; }, 1000);</script>
      </body></html>
    """)

@router.get("/cancel", response_class=HTMLResponse)
def payment_cancel(merchant_uid: str):
    return HTMLResponse("<h3>사용자가 결제를 취소했습니다.</h3>", status_code=200)

@router.get("/fail", response_class=HTMLResponse)
def payment_fail(merchant_uid: str):
    return HTMLResponse("<h3>결제에 실패했습니다.</h3>", status_code=200)
