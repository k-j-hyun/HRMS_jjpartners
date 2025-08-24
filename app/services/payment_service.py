import requests
import json
import hashlib
import hmac
import uuid
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from app.models.database import JobApplication, PaymentLog

class NaverPayService:
    """네이버페이 결제 서비스"""
    
    def __init__(self):
        import os
        # 네이버페이 API 설정 (환경변수에서 로드)
        self.client_id = os.getenv("NAVER_PAY_CLIENT_ID", "YOUR_NAVER_PAY_CLIENT_ID")
        self.client_secret = os.getenv("NAVER_PAY_CLIENT_SECRET", "YOUR_NAVER_PAY_CLIENT_SECRET")
        self.return_url = os.getenv("NAVER_PAY_RETURN_URL", "http://localhost:8000/api/payment/callback")
        self.base_url = os.getenv("NAVER_PAY_BASE_URL", "https://test-pay.naver.com")  # 기본값: 테스트 환경
        
        # .env 파일이 없거나 값이 설정되지 않은 경우에도 작동하도록 처리
        self.is_production = os.getenv("NAVER_PAY_PRODUCTION", "false").lower() == "true"
        if self.is_production:
            self.base_url = "https://pay.naver.com"
        
    def create_payment_request(self, application_id: int, amount: int, user_name: str) -> Dict:
        """결제 요청 생성"""
        
        # 고유한 거래 ID 생성
        merchant_pay_key = f"flowmate_{application_id}_{uuid.uuid4().hex[:8]}"
        
        # 결제 요청 데이터
        payment_data = {
            "merchantPayKey": merchant_pay_key,
            "productName": "FlowMate 근무 보증금",
            "productCount": 1,
            "totalPayAmount": amount,
            "taxScopeAmount": amount,
            "taxExScopeAmount": 0,
            "returnUrl": self.return_url,
            "orderNumber": str(application_id),
            "merchantUserKey": str(user_name),
            "merchantUserName": user_name,
            "productItems": [
                {
                    "categoryType": "SERVICE",
                    "categoryId": "SERVICE",
                    "uid": str(application_id),
                    "name": "근무 보증금",
                    "payReferrer": "FLOWMATE",
                    "count": 1,
                    "sellPrice": amount,
                    "taxType": "TAX"
                }
            ]
        }
        
        # API 요청
        try:
            headers = self._get_headers()
            response = requests.post(
                f"{self.base_url}/payments/recurrent/regist/v1/payment",
                headers=headers,
                json=payment_data,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") == "Success":
                return {
                    "success": True,
                    "payment_url": result["body"]["paymentUrl"],
                    "merchant_pay_key": merchant_pay_key,
                    "payment_data": payment_data
                }
            else:
                return {
                    "success": False,
                    "error": result.get("message", "결제 요청 실패"),
                    "code": result.get("code")
                }
                
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"네트워크 오류: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"결제 요청 처리 중 오류: {str(e)}"
            }
    
    def verify_payment(self, payment_id: str, amount: int) -> Dict:
        """결제 검증"""
        try:
            headers = self._get_headers()
            response = requests.get(
                f"{self.base_url}/payments/recurrent/approve/v1/payment/{payment_id}",
                headers=headers,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") == "Success":
                payment_info = result["body"]
                
                # 결제 금액 검증
                if payment_info.get("totalPayAmount") == amount:
                    return {
                        "success": True,
                        "payment_info": payment_info,
                        "verified": True
                    }
                else:
                    return {
                        "success": False,
                        "error": "결제 금액 불일치",
                        "verified": False
                    }
            else:
                return {
                    "success": False,
                    "error": result.get("message", "결제 검증 실패"),
                    "verified": False
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"결제 검증 중 오류: {str(e)}",
                "verified": False
            }
    
    def create_refund_request(self, original_payment_id: str, amount: int, reason: str = "근무 완료") -> Dict:
        """환불 요청"""
        
        refund_data = {
            "paymentId": original_payment_id,
            "requestAmount": amount,
            "reason": reason,
            "requestId": f"refund_{uuid.uuid4().hex[:8]}"
        }
        
        try:
            headers = self._get_headers()
            response = requests.post(
                f"{self.base_url}/payments/recurrent/cancel/v1/payment",
                headers=headers,
                json=refund_data,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") == "Success":
                return {
                    "success": True,
                    "refund_info": result["body"],
                    "refund_id": result["body"].get("cancelId")
                }
            else:
                return {
                    "success": False,
                    "error": result.get("message", "환불 요청 실패"),
                    "code": result.get("code")
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"환불 요청 중 오류: {str(e)}"
            }
    
    def _get_headers(self) -> Dict[str, str]:
        """API 요청 헤더 생성"""
        timestamp = str(int(datetime.now().timestamp() * 1000))
        
        # 네이버페이 인증 헤더 생성 (실제 구현에서는 HMAC 서명 필요)
        return {
            "Content-Type": "application/json",
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
            "X-Timestamp": timestamp
        }

class PaymentManager:
    """결제 관리 서비스"""
    
    def __init__(self):
        self.naver_pay = NaverPayService()
    
    def initiate_deposit_payment(self, application_id: int, user_name: str, db: Session) -> Dict:
        """보증금 결제 시작"""
        
        # 신청 정보 조회
        application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
        if not application:
            return {"success": False, "error": "신청 정보를 찾을 수 없습니다."}
        
        if application.deposit_paid:
            return {"success": False, "error": "이미 보증금이 결제되었습니다."}
        
        # 결제 요청 생성
        payment_result = self.naver_pay.create_payment_request(
            application_id, 
            application.deposit_amount, 
            user_name
        )
        
        if payment_result["success"]:
            # 결제 로그 생성
            payment_log = PaymentLog(
                application_id=application_id,
                payment_type="deposit",
                amount=application.deposit_amount,
                payment_method="naver_pay",
                status="pending",
                payment_data=json.dumps(payment_result["payment_data"])
            )
            db.add(payment_log)
            db.commit()
            
            return {
                "success": True,
                "payment_url": payment_result["payment_url"],
                "payment_log_id": payment_log.id
            }
        else:
            return payment_result
    
    def complete_deposit_payment(self, payment_id: str, application_id: int, db: Session) -> Dict:
        """보증금 결제 완료 처리"""
        
        application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
        if not application:
            return {"success": False, "error": "신청 정보를 찾을 수 없습니다."}
        
        # 결제 검증
        verify_result = self.naver_pay.verify_payment(payment_id, application.deposit_amount)
        
        if verify_result["success"] and verify_result["verified"]:
            # 신청 상태 업데이트 - approved 상태를 유지하고 결제만 완료 처리
            application.deposit_paid = True
            application.payment_id = payment_id
            # status는 이미 approved이므로 변경하지 않음
            
            # 결제 로그 업데이트
            payment_log = db.query(PaymentLog).filter(
                PaymentLog.application_id == application_id,
                PaymentLog.payment_type == "deposit",
                PaymentLog.status == "pending"
            ).first()
            
            if payment_log:
                payment_log.status = "completed"
                payment_log.payment_id = payment_id
                payment_log.completed_at = datetime.now()
                payment_log.payment_data = json.dumps(verify_result["payment_info"])
            
            db.commit()
            
            return {"success": True, "message": "보증금 결제가 완료되었습니다."}
        else:
            return {"success": False, "error": verify_result["error"]}
    
    def process_deposit_refund(self, application_id: int, db: Session, force_refund: bool = False) -> Dict:
        """보증금 환불 처리"""
        
        application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
        if not application:
            return {"success": False, "error": "신청 정보를 찾을 수 없습니다."}
        
        if not application.deposit_paid:
            return {"success": False, "error": "보증금이 결제되지 않았습니다."}
        
        if application.deposit_refunded:
            return {"success": False, "error": "이미 환불 처리되었습니다."}
        
        # force_refund가 True이면 work_completed 검사 생략 (관리자 강제 환불)
        if not force_refund and not application.work_completed:
            return {"success": False, "error": "근무가 완료되지 않았습니다."}
        
        # 환불 요청
        refund_result = self.naver_pay.create_refund_request(
            application.payment_id,
            application.deposit_amount,
            "근무 완료에 따른 보증금 환불" if not force_refund else "관리자 수동 환불"
        )
        
        if refund_result["success"]:
            # 환불 로그 생성
            refund_log = PaymentLog(
                application_id=application_id,
                payment_type="refund",
                amount=application.deposit_amount,
                payment_method="naver_pay",
                status="completed",
                payment_id=refund_result["refund_id"],
                completed_at=datetime.now(),
                payment_data=json.dumps(refund_result["refund_info"])
            )
            db.add(refund_log)
            
            # 신청 상태 업데이트
            application.deposit_refunded = True
            
            db.commit()
            
            return {"success": True, "message": "보증금 환불이 완료되었습니다."}
        else:
            return refund_result
