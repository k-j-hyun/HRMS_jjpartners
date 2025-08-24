from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import uuid
from urllib.parse import urlencode, quote

from payment.naver_pay import PAY_BASE, naver_auth_headers, get_return_urls, DEPOSIT_AMOUNT, MERCHANT_ID
from app.models.database import get_db, JobApplication
from app.auth import require_employee  # 위치에 맞게 사용

router = APIRouter(prefix="/api/payment/naver", tags=["payment"])

@router.post("/create")
def create_payment(application_id: int, user=Depends(require_employee), db: Session = Depends(get_db)):
    # 1) 신청 조회(본인 것만)
    app_row = db.query(JobApplication).filter(
        JobApplication.id == application_id,
        JobApplication.user_id == user.id
    ).first()
    if not app_row:
        raise HTTPException(status_code=404, detail="Application not found")

    if app_row.deposit_paid:
        raise HTTPException(status_code=400, detail="이미 결제 완료된 신청입니다.")

    # 2) 주문 고유키
    merchant_uid = f"DEP-{app_row.id}-{uuid.uuid4().hex[:8]}"

    # 3) 리다이렉트 URL들
    urls = get_return_urls(merchant_uid)

    # 4) 네이버페이 결제 페이지 URL(스켈레톤)
    q = urlencode({
        "merchantId": MERCHANT_ID or "",
        "merchantUid": merchant_uid,
        "amount": app_row.deposit_amount or DEPOSIT_AMOUNT,
        "productName": "보증금 결제",
        "returnUrl": urls["returnUrl"],
        "cancelUrl": urls["cancelUrl"],
        "failUrl": urls["failUrl"],
    }, quote_via=quote)
    payment_url = f"{PAY_BASE}/web/checkout?{q}"

    # 5) DB 반영
    app_row.payment_id = merchant_uid          # ← 주문키 저장(승인/환불 시 사용)
    if not app_row.deposit_amount:
        app_row.deposit_amount = DEPOSIT_AMOUNT
    db.add(app_row)
    db.commit()

    return {"success": True, "payment_url": payment_url}
