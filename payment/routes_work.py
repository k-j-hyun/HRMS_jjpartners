from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import httpx, json, os

from payment.naver_pay import API_BASE, naver_auth_headers
from app.auth import require_employee   # 있으면 사용
from app.models.database import get_db, JobApplication

router = APIRouter()

@router.post("/api/work-complete/{application_id}")
async def work_complete(application_id: int, user=Depends(require_employee), db: Session = Depends(get_db)):
    app_row = db.query(JobApplication).filter(
        JobApplication.id == application_id,
        JobApplication.user_id == user.id
    ).first()
    if not app_row:
        raise HTTPException(404, "Application not found")

    # 1) 근무 완료
    app_row.status = "completed"

    # 2) 환불
    if app_row.deposit_paid and not app_row.deposit_refunded:
        payload = {
            "merchantId": os.getenv("NAVER_PAY_MERCHANT_ID", ""),
            "merchantUid": app_row.payment_id,  # 승인 때와 동일 UID
            "cancelAmount": app_row.deposit_amount or 5000,
            "cancelReason": "근무 완료 환불"
        }
        headers = naver_auth_headers(json.dumps(payload, ensure_ascii=False))
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{API_BASE}/v1/payments/cancel", headers=headers, json=payload)
            ok = r.status_code == 200
            data = r.json() if ok else {"code": r.status_code, "body": r.text}

        if ok:
            app_row.deposit_refunded = True
        else:
            db.commit()
            return {"message": "근무완료 처리되었습니다. (환불 대기/관리자 재시도 필요)", "refund_ok": False, "pg": data}

    db.add(app_row)
    db.commit()
    return {"message": "근무가 완료되었습니다.", "refund_ok": bool(app_row.deposit_refunded)}
