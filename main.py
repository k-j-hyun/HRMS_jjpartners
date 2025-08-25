from fastapi import FastAPI, Depends, HTTPException, Request, status, Query, Form, Body
from fastapi.security import HTTPBearer
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from datetime import datetime, timedelta
import uvicorn
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

# 앱 모듈 import
from app.models.database import get_db, User, Employee, AttendanceRecord, LocationEvent, JobPost, JobApplication, PaymentLog, Department, Violation
from app.auth import verify_token, create_access_token, require_admin, require_manager_or_admin
from app.services.location_service import LocationService
from app.services.job_service import JobBoardService
from app.services.payment_service import PaymentManager
from app.services.geocoding_service import GeocodingService
from app.services.report_service import ReportService
from app.services.violation_detection_service import ViolationDetectionService
from pydantic import BaseModel
from typing import Optional, List
from fastapi.responses import StreamingResponse
import io
from datetime import date
from payment.routes_payment import router as naver_pay_router
from payment.routes_payment_return import router as naver_pay_return_router
from payment.routes_work import router as work_router

# FastAPI 앱 생성
app = FastAPI(
    title="HRMS - Human Resource Management System",
    description="전문적인 인력관리 및 근태관리 시스템",
    version="1.0.0"
)

app.include_router(naver_pay_router)
app.include_router(naver_pay_return_router)
app.include_router(work_router)

# Pydantic 모델 정의
class AddressToCoordinatesRequest(BaseModel):
    address: str

class RegisterRequest(BaseModel):
    username: str
    email: str
    full_name: str
    password: str
    employee_number: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    phone: Optional[str] = None

# 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 템플릿 및 정적 파일 설정
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

security = HTTPBearer()

# Pydantic 모델들
class LoginRequest(BaseModel):
    username: str
    password: str
    role: str = "employee"

class LocationRequest(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None

class AttendanceAction(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None

class JobPostCreate(BaseModel):
    title: str
    company_name: str
    description: str
    requirements: Optional[str] = None
    salary: Optional[str] = None
    work_hours: Optional[str] = None
    work_period: Optional[str] = None  # 근무 기간 추가
    work_address: str
    work_latitude: float
    work_longitude: float
    geofence_radius: Optional[float] = 100.0
    deadline: Optional[datetime] = None
    max_applicants: Optional[int] = None
    auto_approval: Optional[bool] = False

class JobApplicationRequest(BaseModel):
    job_post_id: int

class PaymentCallback(BaseModel):
    payment_id: str
    application_id: int
    status: str

class PaymentCreateRequest(BaseModel):
    application_id: int

class TestRequest(BaseModel):
    test_id: int
    message: str

class DepartmentCreateRequest(BaseModel):
    name: str
    description: str = ""

# PWA 지원
@app.get("/static/sw.js")
def service_worker():
    """Service Worker 제공"""
    from fastapi.responses import FileResponse
    return FileResponse("static/sw.js", media_type="application/javascript")

# 웹 페이지 라우트들
@app.get("/")
def index(request: Request):
    """메인 페이지"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register")
def register_page(request: Request):
    """회원가입 페이지"""
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/")
def home(request: Request):
    """홈페이지"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
def login_page(request: Request):
    """로그인 페이지"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/admin")
def admin_dashboard(request: Request):
    """관리자 대시보드"""
    return templates.TemplateResponse("admin_dashboard.html", {"request": request})

@app.get("/employee")
def employee_mobile(request: Request):
    """직원용 모바일 인터페이스"""
    return templates.TemplateResponse("employee_mobile.html", {"request": request})

@app.get("/employee/history")
def employee_history(request: Request):
    """직원 출입 기록 페이지"""
    return templates.TemplateResponse("employee_history.html", {"request": request})

@app.get("/jobs")
def job_board(request: Request):
    """채용 게시판"""
    return templates.TemplateResponse("job_board.html", {"request": request})

@app.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int):
    """채용 공고 상세 페이지"""
    return templates.TemplateResponse("job_detail.html", {"request": request, "job_id": job_id})

@app.get("/api-test")
def api_test_page(request: Request):
    """디버깅용 API 테스트 페이지"""
    return templates.TemplateResponse("api_test.html", {"request": request})

@app.get("/my-applications")
def my_applications(request: Request):
    """나의 신청 목록"""
    return templates.TemplateResponse("my_applications.html", {"request": request})

@app.get("/payment/complete")
def payment_complete(request: Request):
    """보증금 결제 완료 페이지"""
    return templates.TemplateResponse("payment_complete.html", {"request": request})

@app.post("/api/payment/start/{application_id}")
def start_payment(application_id: int, current_user: dict = Depends(verify_token), db: Session = Depends(get_db)):
    """보증금 결제 시작"""
    try:
        # 신청 정보 확인
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id,
            JobApplication.user_id == current_user["user_id"]
        ).first()
        
        if not application:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다")
        
        # 이미 결제되었는지 확인
        if application.deposit_paid:
            raise HTTPException(status_code=400, detail="이미 보증금이 결제되었습니다")
        
        # 승인되지 않은 신청인지 확인
        if application.status != 'approved':
            raise HTTPException(status_code=400, detail="승인된 신청만 결제가 가능합니다")
        
        # TODO: 실제 결제 서비스 연동 (네이버페이, 토스페이 등)
        # payment_manager = PaymentManager()
        # payment_result = payment_manager.start_deposit_payment(application_id, db)
        
        # 현재는 테스트용으로 결제 완료 페이지로 바로 이동
        return {
            "success": True,
            "payment_url": f"/payment/complete?applicationId={application_id}&status=success&paymentId=TEST_{application_id}",
            "message": "결제 페이지로 이동합니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"결제 시작 중 오류가 발생했습니다: {str(e)}")

@app.post("/api/payment/complete/{application_id}")
def complete_payment(application_id: int, payment_data: dict = Body(...), current_user: dict = Depends(verify_token), db: Session = Depends(get_db)):
    """보증금 결제 완료 처리"""
    try:
        # 신청 정보 확인
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id,
            JobApplication.user_id == current_user["user_id"]
        ).first()
        
        if not application:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다")
        
        if application.status != 'approved':
            raise HTTPException(status_code=400, detail="승인된 신청만 결제 처리가 가능합니다")
        
        payment_status = payment_data.get('status', 'success')
        payment_id = payment_data.get('payment_id')
        
        if payment_status == 'success':
            # 보증금 결제 완료 처리
            application.deposit_paid = True
            
            # 결제 로그 생성
            payment_log = PaymentLog(
                user_id=current_user["user_id"],
                application_id=application_id,
                payment_type="deposit",
                amount=5000,  # 보증금 금액
                payment_id=payment_id or f"TEST_{application_id}",
                payment_method="naverpay",
                status="completed",
                created_at=datetime.now()
            )
            db.add(payment_log)
            db.commit()
            
            return {"success": True, "message": "보증금 결제가 완료되었습니다"}
        else:
            return {"success": False, "message": "결제가 취소되거나 실패했습니다"}
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"결제 완료 처리 중 오류가 발생했습니다: {str(e)}")

# 인증 API
@app.post("/api/auth/register")
async def register(register_data: RegisterRequest, db: Session = Depends(get_db)):
    """회원가입"""
    from app.models.database import get_password_hash
    import uuid
    from datetime import datetime
    
    # 중복 확인
    existing_user = db.query(User).filter(
        (User.username == register_data.username) | 
        (User.email == register_data.email)
    ).first()
    
    if existing_user:
        if existing_user.username == register_data.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 사용 중인 사용자명입니다."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 사용 중인 이메일입니다."
            )
    
    try:
        # 새 사용자 생성
        new_user = User(
            username=register_data.username,
            email=register_data.email,
            full_name=register_data.full_name,
            hashed_password=get_password_hash(register_data.password),
            role="employee",
            is_active=True
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # 직원번호 생성 (제공되지 않은 경우)
        employee_number = register_data.employee_number
        if not employee_number:
            employee_number = f"EMP{new_user.id:04d}"
        
        # 부서 ID 찾기
        department_id = None
        if register_data.department:
            department = db.query(Department).filter(Department.name == register_data.department).first()
            if department:
                department_id = department.id
        
        # 직원 프로필 생성
        new_employee = Employee(
            user_id=new_user.id,
            employee_number=employee_number,
            department_id=department_id,
            position=register_data.position,
            hire_date=datetime.now(),
            phone=register_data.phone,
            work_type="office",
            gps_tracking_enabled=True
        )
        
        db.add(new_employee)
        db.commit()
        
        return {
            "message": "회원가입이 완료되었습니다.",
            "user_id": new_user.id,
            "employee_number": employee_number
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"회원가입 처리 중 오류가 발생했습니다: {str(e)}"
        )

@app.post("/api/auth/login")
async def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """로그인"""
    from app.models.database import verify_password
    
    user = db.query(User).filter(User.username == login_data.username).first()
    
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용자명 또는 비밀번호가 올바르지 않습니다."
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비활성화된 계정입니다."
        )
    
    # 역할 확인
    if login_data.role == "admin" and user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 없습니다."
        )
    
    # 마지막 로그인 시간 업데이트
    user.last_login = datetime.now()
    db.commit()
    
    # 토큰 생성
    access_token = create_access_token(data={"sub": user.username})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role
        }
    }

@app.get("/api/auth/verify")
async def verify_user_token(current_user: User = Depends(verify_token)):
    """토큰 검증"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "email": current_user.email
    }

@app.get("/admin/employee/{employee_id}/detail")
def employee_detail_page(request: Request, employee_id: int):
    return templates.TemplateResponse(
        "employee_detail.html",
        {"request": request, "employee_id": employee_id}
    )

# 직원 상세 정보 API
@app.get("/api/admin/employee/{employee_id}")
async def get_employee_detail(
    employee_id: int,
    current_user: User = Depends(require_manager_or_admin), # 관리자 또는 매니저 권한 필요
    db: Session = Depends(get_db)
):
    """
    직원 상세 정보 조회 API 엔드포인트

    Args:
        employee_id (int): 상세 정보를 조회할 직원의 ID.
        current_user (User): 인증된 현재 사용자 객체 (require_manager_or_admin 의존성 주입).
        db (Session): 데이터베이스 세션 객체 (get_db 의존성 주입).

    Returns:
        dict: 직원의 상세 정보, 통계, 최근 출근 기록 및 위치 이벤트 목록.
    
    Raises:
        HTTPException: 직원 정보를 찾을 수 없거나 권한이 없는 경우.
    """
    # 1. 직원 정보 조회: 주어진 employee_id로 직원 엔티티를 찾습니다.
    #    직원이 존재하지 않으면 404 Not Found 오류를 발생시킵니다.
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
    
    # 2. 사용자 정보 조회: 직원과 연결된 사용자 엔티티를 찾습니다.
    user = db.query(User).filter(User.id == employee.user_id).first()
    
    # 3. 최근 출근 기록 조회: 해당 직원의 최신 출근 기록 10개를 가져옵니다.
    recent_attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_id == employee_id
    ).order_by(AttendanceRecord.check_in_time.desc()).limit(10).all()
    
    # 4. 최근 위치 이벤트 조회: 해당 직원의 최신 위치 이벤트 20개를 가져옵니다.
    recent_locations = db.query(LocationEvent).filter(
        LocationEvent.employee_id == employee_id
    ).order_by(LocationEvent.timestamp.desc()).limit(20).all()
    
    # 5. 월별 통계 계산: 현재 월의 출근 기록을 기반으로 통계를 계산합니다.
    today = datetime.now().date()
    this_month_start = datetime(today.year, today.month, 1) # 현재 월의 첫째 날
    
    this_month_attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_id == employee_id,
        AttendanceRecord.check_in_time >= this_month_start # 현재 월의 출근 기록 필터링
    ).all()
    
    # 근무 완료된 일수 계산 (퇴근 시간이 있는 기록만 카운트)
    total_work_days = len([r for r in this_month_attendance if r.check_out_time])
    # 총 근무 시간 계산 (분 단위 합계를 시간으로 변환)
    total_work_minutes_sum = sum([r.total_work_minutes for r in this_month_attendance if r.total_work_minutes is not None])
    total_work_hours = total_work_minutes_sum / 60
    # 지각 횟수 계산
    late_count = len([r for r in this_month_attendance if r.is_late])
    
    # 6. 결과 반환: 직원의 기본 정보, 계산된 통계, 그리고 최근 활동 목록을 구조화하여 반환합니다.
    return {
        "employee": {
            "id": employee.id,
            "employee_number": employee.employee_number,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "department": employee.department.name if employee.department else None, # 부서명 (없으면 None)
            "position": employee.position,
            "hire_date": employee.hire_date,
            "phone": employee.phone,
            "work_type": employee.work_type,
            "gps_tracking_enabled": employee.gps_tracking_enabled
        },
        "statistics": {
            "total_work_days": total_work_days,
            "total_work_hours": round(total_work_hours, 1), # 소수점 첫째 자리까지 반올림
            "late_count": late_count,
            "avg_work_hours": round(total_work_hours / total_work_days, 1) if total_work_days > 0 else 0 # 평균 근무 시간
        },
        "recent_attendance": [
            {
                "id": record.id,
                "check_in_time": record.check_in_time,
                "check_out_time": record.check_out_time,
                "total_work_minutes": record.total_work_minutes,
                "is_late": record.is_late,
                "site_name": record.site.name if record.site else None # 근무지 이름 (없으면 None)
            } for record in recent_attendance
        ],
        "recent_locations": [
            {
                "event_type": event.event_type,
                "timestamp": event.timestamp,
                "site_name": event.site.name if event.site else None, # 위치 이벤트 발생 근무지 이름 (없으면 None)
                "accuracy": event.accuracy
            } for event in recent_locations
        ]
    }

# 부서 목록 API (관리자용)
@app.get("/api/admin/departments")
async def get_departments(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """부서 목록 조회"""
    try:
        departments = db.query(Department).all()
        return [
            {
                "id": dept.id,
                "name": dept.name,
                "description": dept.description,
                "employee_count": len(dept.employees) if dept.employees else 0
            } for dept in departments
        ]
    except Exception as e:
        print(f"Departments API error: {e}")
        return []

# 부서 목록 API (회원가입용 - 인증 불필요)
@app.get("/api/departments")
async def get_public_departments(db: Session = Depends(get_db)):
    """회원가입용 부서 목록 조회 (인증 불필요)"""
    try:
        departments = db.query(Department).all()
        return [
            {
                "id": dept.id,
                "name": dept.name
            } for dept in departments
        ]
    except Exception as e:
        print(f"Public departments API error: {e}")
        return []

@app.post("/api/admin/departments")
async def create_department(
    department_data: DepartmentCreateRequest,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """부서 생성"""
    try:
        # 기본 회사 확인 및 생성
        from app.models.database import Company
        default_company = db.query(Company).filter(Company.id == 1).first()
        if not default_company:
            default_company = Company(
                id=1,
                name="기본 회사",
                business_number="000-00-00000",
                address="기본 주소"
            )
            db.add(default_company)
            db.flush()
        
        # 중복 확인
        existing_dept = db.query(Department).filter(Department.name == department_data.name).first()
        if existing_dept:
            raise HTTPException(status_code=400, detail="이미 존재하는 부서명입니다.")
        
        # 부서 생성
        department = Department(
            name=department_data.name,
            description=department_data.description,
            company_id=1  # 기본 회사 ID
        )
        db.add(department)
        db.commit()
        db.refresh(department)
        
        return {
            "success": True,
            "message": "부서가 성공적으로 생성되었습니다.",
            "department": {
                "id": department.id,
                "name": department.name,
                "description": department.description
            }
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"부서 생성 중 오류가 발생했습니다: {str(e)}")

@app.delete("/api/admin/departments/{department_id}")
async def delete_department(
    department_id: int,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """부서 삭제"""
    try:
        # 부서 존재 확인
        department = db.query(Department).filter(Department.id == department_id).first()
        if not department:
            raise HTTPException(status_code=404, detail="존재하지 않는 부서입니다.")
        
        # 부서에 속한 직원 확인
        employee_count = db.query(Employee).filter(Employee.department_id == department_id).count()
        if employee_count > 0:
            raise HTTPException(
                status_code=400, 
                detail=f"부서에 {employee_count}명의 직원이 속해 있어 삭제할 수 없습니다. 먼저 모든 직원을 다른 부서로 이동시켜주세요."
            )
        
        # 부서 삭제
        db.delete(department)
        db.commit()
        
        return {
            "success": True,
            "message": f"'{department.name}' 부서가 성공적으로 삭제되었습니다."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting department {department_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"부서 삭제 중 오류가 발생했습니다: {str(e)}")

# Test endpoint to verify Pydantic model works
@app.post("/api/test/request")
async def test_request(test_data: TestRequest):
    """Test endpoint"""
    return {"success": True, "received": test_data.dict()}

# Test endpoint with dependencies like the payment endpoint
@app.post("/api/test/with-deps")
async def test_request_with_deps(
    test_data: TestRequest,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """Test endpoint with dependencies"""
    return {"success": True, "received": test_data.dict(), "user": current_user.username}

# 실제 결제 기능을 위한 네이버페이 결제 API
@app.post("/api/payment/naver/create-new")
async def create_naver_payment(
    payment_data: PaymentCreateRequest,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """네이버페이 결제 생성"""
    application = db.query(JobApplication).filter(
        JobApplication.id == payment_data.application_id,
        JobApplication.user_id == current_user.id
    ).first()
    
    if not application:
        raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다.")
    
    if application.deposit_paid:
        raise HTTPException(status_code=400, detail="이미 결제된 신청입니다.")
    
    payment_manager = PaymentManager()
    result = payment_manager.initiate_deposit_payment(
        payment_data.application_id,
        current_user.full_name,
        db
    )
    
    if result["success"]:
        return {
            "success": True,
            "payment_url": result["payment_url"],
            "message": "결제 페이지가 생성되었습니다."
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# 관리자 대시보드 실제 데이터 로드 API들
@app.get("/api/admin/attendance-records")
async def get_attendance_records(
    date: Optional[str] = None,
    department_id: Optional[int] = None,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """출근 기록 조회"""
    query = db.query(AttendanceRecord)
    
    # 날짜 필터
    if date:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        start_datetime = datetime.combine(target_date, datetime.min.time())
        end_datetime = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        query = query.filter(
            AttendanceRecord.check_in_time >= start_datetime,
            AttendanceRecord.check_in_time < end_datetime
        )
    
    # 부서 필터
    if department_id:
        query = query.join(Employee).filter(Employee.department_id == department_id)
    
    records = query.order_by(AttendanceRecord.check_in_time.desc()).limit(100).all()
    
    from app.models.database import Site
    result = []
    for record in records:
        employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
        user = db.query(User).filter(User.id == employee.user_id).first()
        site = db.query(Site).filter(Site.id == record.site_id).first() if record.site_id else None
        
        result.append({
            "employee_name": user.full_name,
            "check_in_time": record.check_in_time,
            "check_out_time": record.check_out_time,
            "total_work_minutes": record.total_work_minutes,
            "is_late": record.is_late,
            "site_name": site.name if site else None,
            "status": record.status
        })
    
    return result

@app.get("/api/admin/violations")
async def get_violations(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """위반 사항 조회"""
    violations = db.query(Violation).order_by(Violation.occurred_at.desc()).limit(50).all()
    
    result = []
    for violation in violations:
        employee = db.query(Employee).filter(Employee.id == violation.employee_id).first()
        user = db.query(User).filter(User.id == employee.user_id).first()
        
        result.append({
            "id": violation.id,
            "employee_name": user.full_name,
            "violation_type": violation.violation_type,
            "severity": violation.severity,
            "occurred_at": violation.occurred_at,
            "description": violation.description,
            "status": violation.status
        })
    
    return result


@app.get("/api/admin/stats")
async def get_admin_stats(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """관리자 대시보드 통계"""
    today = datetime.now().date()
    
    # 전체 직원 수
    total_employees = db.query(Employee).count()
    
    # 오늘 출근한 직원 수
    present_today = db.query(AttendanceRecord).filter(
        AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time()),
        AttendanceRecord.check_in_time < datetime.combine(today + timedelta(days=1), datetime.min.time())
    ).count()
    
    # 오늘 지각한 직원 수
    late_today = db.query(AttendanceRecord).filter(
        AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time()),
        AttendanceRecord.is_late == True
    ).count()
    
    # 오늘 결근한 직원 수 (예정되어 있었지만 출근하지 않은 직원)
    absent_today = total_employees - present_today
    
    return {
        "total_employees": total_employees,
        "present_today": present_today,
        "late_today": late_today,
        "absent_today": max(0, absent_today)
    }

@app.get("/api/admin/current-status")
async def get_current_working_status(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """현재 근무 중인 직원 현황"""
    today = datetime.now().date()
    
    # 오늘 출근했지만 아직 퇴근하지 않은 직원들
    working_records = db.query(AttendanceRecord).filter(
        AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time()),
        AttendanceRecord.check_out_time.is_(None)
    ).all()
    
    working_employees = []
    for record in working_records:
        employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
        user = db.query(User).filter(User.id == employee.user_id).first()
        
        # 최근 위치 조회
        last_location = db.query(LocationEvent).filter(
            LocationEvent.employee_id == employee.id
        ).order_by(LocationEvent.timestamp.desc()).first()
        
        working_employees.append({
            "employee_id": employee.id,
            "employee_name": user.full_name,
            "department": employee.department.name if employee.department else None,
            "check_in_time": record.check_in_time,
            "current_site": last_location.site.name if last_location and last_location.site else None,
            "last_location_update": last_location.timestamp if last_location else None
        })
    
    return {"working_employees": working_employees}

@app.get("/api/admin/recent-activity")
async def get_recent_activity(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """최근 출입 활동"""
    recent_events = db.query(LocationEvent).filter(
        LocationEvent.event_type.in_(["check_in", "check_out", "geofence_enter", "geofence_exit"])
    ).order_by(LocationEvent.timestamp.desc()).limit(20).all()
    
    activities = []
    for event in recent_events:
        employee = db.query(Employee).filter(Employee.id == event.employee_id).first()
        user = db.query(User).filter(User.id == employee.user_id).first()
        
        activities.append({
            "employee_name": user.full_name,
            "event_type": event.event_type,
            "site_name": event.site.name if event.site else None,
            "timestamp": event.timestamp,
            "location": f"{event.latitude:.6f}, {event.longitude:.6f}"
        })
    
    return activities

@app.get("/api/admin/employees")
async def get_all_employees(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """전체 직원 목록"""
    employees = db.query(Employee).all()
    
    employee_list = []
    for emp in employees:
        user = db.query(User).filter(User.id == emp.user_id).first()
        
        # 현재 상태 확인
        today = datetime.now().date()
        today_attendance = db.query(AttendanceRecord).filter(
            AttendanceRecord.employee_id == emp.id,
            AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time())
        ).first()
        
        status = "waiting"
        if today_attendance:
            if today_attendance.check_out_time:
                status = "completed"
            elif today_attendance.check_in_time:
                status = "working"
        
        # 최근 위치
        last_location = db.query(LocationEvent).filter(
            LocationEvent.employee_id == emp.id
        ).order_by(LocationEvent.timestamp.desc()).first()
        
        employee_list.append({
            "id": emp.id,
            "employee_number": emp.employee_number,
            "full_name": user.full_name,
            "department": emp.department.name if emp.department else None,
            "position": emp.position,
            "current_status": status,
            "last_location": f"{last_location.site.name if last_location and last_location.site else '위치 정보 없음'}",
            "gps_enabled": emp.gps_tracking_enabled,
            "role": user.role  # 사용자 권한 정보 추가
        })
    
    return employee_list

@app.post("/api/admin/employees")
async def create_employee(
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    department_id: int = Form(...),
    position: str = Form(...),
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """직원 추가"""
    from app.models.database import get_password_hash
    try:
        # 중복 확인
        existing_user = db.query(User).filter(
            or_(User.username == username, User.email == email)
        ).first()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="이미 존재하는 사용자명 또는 이메일입니다.")
        
        # 사용자 계정 생성
        user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            role="employee"
        )
        db.add(user)
        db.flush()
        
        # 직원 번호 생성
        employee_number = f"EMP{user.id:04d}"
        
        # 직원 프로필 생성
        employee = Employee(
            user_id=user.id,
            employee_number=employee_number,
            department_id=department_id,
            position=position,
            hire_date=datetime.now(),
            work_type="office",
            gps_tracking_enabled=True
        )
        db.add(employee)
        db.commit()
        
        return {
            "success": True,
            "message": "직원이 성공적으로 추가되었습니다.",
            "employee_id": employee.id
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"직원 추가 중 오류가 발생했습니다: {str(e)}")

@app.delete("/api/admin/employees/{employee_id}")
async def delete_employee(
    employee_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """직원 삭제"""
    try:
        # 직원 조회
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
        
        # 해당 직원의 사용자 계정 조회
        user = db.query(User).filter(User.id == employee.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자 계정을 찾을 수 없습니다.")
        
        # 관련 데이터 삭제 (외래키 제약조건 고려)
        # 1. 출근 기록 삭제
        db.query(AttendanceRecord).filter(AttendanceRecord.employee_id == employee_id).delete()
        
        # 2. 위치 이벤트 삭제
        db.query(LocationEvent).filter(LocationEvent.employee_id == employee_id).delete()
        
        # 3. 위반사항 삭제
        db.query(Violation).filter(Violation.employee_id == employee_id).delete()
        
        # 4. 직원 삭제
        db.delete(employee)
        
        # 5. 사용자 계정 삭제
        db.delete(user)
        
        db.commit()
        
        return {
            "success": True,
            "message": "직원이 성공적으로 삭제되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"직원 삭제 중 오류가 발생했습니다: {str(e)}")

@app.put("/api/admin/employees/{employee_id}/role")
async def change_employee_role(
    employee_id: int,
    role_data: dict,
    current_user: User = Depends(require_admin),  # 관리자만 권한 변경 가능
    db: Session = Depends(get_db)
):
    """직원 권한 변경"""
    try:
        # 직원 조회
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
        
        # 해당 직원의 사용자 계정 조회
        user = db.query(User).filter(User.id == employee.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자 계정을 찾을 수 없습니다.")
        
        # 새 권한 검증
        new_role = role_data.get("role")
        valid_roles = ["employee", "manager", "admin"]
        if new_role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"유효하지 않은 권한입니다. 가능한 권한: {', '.join(valid_roles)}")
        
        # 자기 자신의 권한은 변경할 수 없음
        if user.id == current_user.id:
            raise HTTPException(status_code=400, detail="자신의 권한은 변경할 수 없습니다.")
        
        # 권한 업데이트
        old_role = user.role
        user.role = new_role
        db.commit()
        
        role_names = {
            "employee": "일반 직원",
            "manager": "매니저", 
            "admin": "관리자"
        }
        
        return {
            "success": True,
            "message": f"{user.full_name}님의 권한이 '{role_names[old_role]}'에서 '{role_names[new_role]}'로 변경되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"권한 변경 중 오류가 발생했습니다: {str(e)}")

@app.put("/api/admin/employees/{employee_id}")
async def update_employee(
    employee_id: int,
    employee_data: dict,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """직원 정보 업데이트"""
    try:
        # 직원 존재 확인
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
        
        # 해당 직원의 사용자 계정 조회
        user = db.query(User).filter(User.id == employee.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자 계정을 찾을 수 없습니다.")
        
        # 직원번호 중복 확인 (다른 직원과 중복되지 않도록)
        if employee_data.get('employee_number'):
            existing_employee = db.query(Employee).filter(
                Employee.employee_number == employee_data['employee_number'],
                Employee.id != employee_id
            ).first()
            if existing_employee:
                raise HTTPException(status_code=400, detail="이미 존재하는 직원번호입니다.")
        
        # 업데이트할 필드들
        if employee_data.get('employee_number'):
            employee.employee_number = employee_data['employee_number']
        if employee_data.get('username'):
            # 사용자명 중복 확인
            existing_user = db.query(User).filter(
                User.username == employee_data['username'],
                User.id != user.id
            ).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="이미 존재하는 사용자명입니다.")
            user.username = employee_data['username']
        if employee_data.get('full_name'):
            user.full_name = employee_data['full_name']  # User 테이블의 full_name 필드 업데이트
        if employee_data.get('email') is not None:
            user.email = employee_data['email']  # User 테이블의 email 필드 업데이트
        if employee_data.get('phone_number') is not None:
            employee.phone = employee_data['phone_number']  # Employee 테이블의 phone 필드 업데이트
        if employee_data.get('department_id') is not None:
            # 부서 존재 확인
            if employee_data['department_id']:
                department = db.query(Department).filter(Department.id == employee_data['department_id']).first()
                if not department:
                    raise HTTPException(status_code=400, detail="존재하지 않는 부서입니다.")
            employee.department_id = employee_data['department_id']
        if employee_data.get('position') is not None:
            employee.position = employee_data['position']
        if employee_data.get('salary') is not None:
            employee.salary = employee_data['salary']
        if employee_data.get('hire_date') is not None:
            from datetime import datetime
            if employee_data['hire_date']:
                employee.hire_date = datetime.fromisoformat(employee_data['hire_date'])
            else:
                employee.hire_date = None
        
        # 변경사항 저장
        db.commit()
        db.refresh(employee)
        
        return {
            "success": True,
            "message": f"{user.full_name}님의 정보가 성공적으로 업데이트되었습니다.",
            "employee": {
                "id": employee.id,
                "employee_number": employee.employee_number,
                "full_name": user.full_name,
                "email": user.email,
                "phone_number": employee.phone,
                "department_id": employee.department_id,
                "position": employee.position,
                "hire_date": employee.hire_date.isoformat() if employee.hire_date else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating employee {employee_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"직원 정보 업데이트 중 오류가 발생했습니다: {str(e)}")

@app.post("/api/admin/employees/{employee_id}/reset-password")
async def reset_employee_password(
    employee_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """직원 비밀번호 초기화"""
    from app.models.database import get_password_hash
    try:
        # 직원 정보 조회
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise HTTPException(status_code=404, detail="직원을 찾을 수 없습니다.")
        
        # 해당 직원의 사용자 계정 조회
        user = db.query(User).filter(User.id == employee.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="사용자 계정을 찾을 수 없습니다.")
        
        # 비밀번호를 'abcd1234'로 초기화
        default_password = "abcd1234"
        user.hashed_password = get_password_hash(default_password)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"{user.full_name}님의 비밀번호가 초기화되었습니다. (초기 비밀번호: {default_password})"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"비밀번호 초기화 중 오류가 발생했습니다: {str(e)}")

# 직원 API
@app.get("/api/employee/status")
async def get_employee_status(
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """직원 현재 상태 조회"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    status_data = LocationService.get_employee_current_status(employee.id, db)
    
    # 할당된 근무지 정보 추가
    assigned_sites_info = []
    for site in status_data.get("assigned_sites", []):
        assigned_sites_info.append({
            "id": site.id,
            "name": site.name,
            "address": site.address,
            "latitude": site.latitude,
            "longitude": site.longitude,
            "geofence_radius": site.geofence_radius
        })
    
    return {
        "status": status_data["status"],
        "attendance": {
            "check_in_time": status_data["check_in_time"],
            "check_out_time": status_data["check_out_time"],
            "site_name": status_data["site_name"]
        },
        "current_site": status_data["current_site"],
        "assigned_sites": assigned_sites_info
    }

@app.post("/api/employee/check-location")
async def check_employee_location(
    location_data: LocationRequest,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """직원 위치 확인 및 지오펜스 체크"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    # 지오펜스 체크
    geofence_result = LocationService.check_geofence(
        location_data.latitude, 
        location_data.longitude, 
        employee.id, 
        db
    )
    
    # 할당된 모든 근무지와의 거리 정보 추가
    assigned_sites = LocationService.get_employee_assigned_sites(employee.id, db)
    sites_distances = []
    
    for site in assigned_sites:
        distance = LocationService.calculate_distance(
            location_data.latitude, location_data.longitude,
            site.latitude, site.longitude
        )
        sites_distances.append({
            "site_id": site.id,
            "site_name": site.name,
            "distance": round(distance),
            "inside_geofence": distance <= site.geofence_radius,
            "latitude": site.latitude,
            "longitude": site.longitude
        })
    
    return {
        "inside_geofence": geofence_result["inside"],
        "site_name": geofence_result["site"].name if geofence_result["site"] else None,
        "distance": geofence_result["min_distance"],
        "closest_site": geofence_result["closest_site"].name if geofence_result["closest_site"] else None,
        "sites_distances": sites_distances
    }

@app.post("/api/employee/checkIn")
async def employee_check_in(
    action_data: AttendanceAction,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """출근 체크"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    # 위치 업데이트 처리
    location_data = {
        'latitude': action_data.latitude,
        'longitude': action_data.longitude,
        'accuracy': action_data.accuracy or 10.0
    }
    
    result = LocationService.process_location_update(employee.id, location_data, db)
    
    if result["status"] == "success" and result.get("attendance", {}).get("action") == "check_in":
        return {"message": f"{result['site']}에서 출근이 완료되었습니다.", "result": result}
    else:
        raise HTTPException(
            status_code=400, 
            detail="출근 체크에 실패했습니다. 지정된 근무지 내에 있는지 확인해주세요."
        )

@app.post("/api/employee/checkOut")
async def employee_check_out(
    action_data: AttendanceAction,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """퇴근 체크"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    # 오늘의 출근 기록 확인
    today = datetime.now().date()
    attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.employee_id == employee.id,
        AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time()),
        AttendanceRecord.check_out_time.is_(None)
    ).first()
    
    if not attendance:
        raise HTTPException(status_code=400, detail="출근 기록이 없습니다.")
    
    # 퇴근 처리
    attendance.check_out_time = datetime.now()
    attendance.status = "completed"
    attendance.check_out_location = f"퇴근 체크 ({action_data.latitude:.6f}, {action_data.longitude:.6f})"
    
    # 근무 시간 계산
    work_duration = attendance.check_out_time - attendance.check_in_time
    attendance.total_work_minutes = int(work_duration.total_seconds() / 60)
    
    db.commit()
    
    # 위치 이벤트 기록
    checkout_event = LocationEvent(
        employee_id=employee.id,
        site_id=attendance.site_id,
        latitude=action_data.latitude,
        longitude=action_data.longitude,
        accuracy=action_data.accuracy,
        event_type="check_out",
        timestamp=attendance.check_out_time
    )
    db.add(checkout_event)
    db.commit()
    
    return {
        "message": "퇴근이 완료되었습니다.",
        "work_duration": f"{attendance.total_work_minutes // 60}시간 {attendance.total_work_minutes % 60}분"
    }

@app.get("/api/employee/recent-activity")
async def get_employee_recent_activity(
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """직원 최근 활동 조회"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    recent_events = db.query(LocationEvent).filter(
        LocationEvent.employee_id == employee.id
    ).order_by(LocationEvent.timestamp.desc()).limit(10).all()
    
    activities = []
    for event in recent_events:
        activities.append({
            "event_type": event.event_type,
            "site_name": event.site.name if event.site else None,
            "timestamp": event.timestamp,
            "accuracy": event.accuracy
        })
    
    return activities

@app.get("/api/employee/attendance-history")
async def get_employee_attendance_history(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """직원 출입 기록 조회"""
    employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
    if not employee:
        raise HTTPException(status_code=404, detail="직원 정보를 찾을 수 없습니다.")
    
    # 기본 쿼리 설정
    query = db.query(AttendanceRecord).filter(AttendanceRecord.employee_id == employee.id)
    
    # 날짜 필터
    if start_date:
        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        query = query.filter(AttendanceRecord.check_in_time >= start_datetime)
    
    if end_date:
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(AttendanceRecord.check_in_time < end_datetime)
    
    # 상태 필터
    if status:
        if status == "late":
            query = query.filter(AttendanceRecord.is_late == True)
        elif status == "working":
            query = query.filter(AttendanceRecord.check_out_time.is_(None))
        elif status == "completed":
            query = query.filter(AttendanceRecord.check_out_time.is_not(None))
    
    # 최신 순으로 정렬
    records = query.order_by(AttendanceRecord.check_in_time.desc()).all()
    
    # 기록 변환
    record_list = []
    for record in records:
        from app.models.database import Site
        site = db.query(Site).filter(Site.id == record.site_id).first() if record.site_id else None
        
        record_list.append({
            "id": record.id,
            "check_in_time": record.check_in_time,
            "check_out_time": record.check_out_time,
            "total_work_minutes": record.total_work_minutes,
            "is_late": record.is_late,
            "status": record.status,
            "site_name": site.name if site else None,
            "check_in_location": record.check_in_location,
            "check_out_location": record.check_out_location
        })
    
    # 통계 계산
    total_days = len([r for r in records if r.check_out_time])
    total_minutes = sum([r.total_work_minutes for r in records if r.total_work_minutes])
    total_hours = round(total_minutes / 60, 1) if total_minutes else 0
    late_count = len([r for r in records if r.is_late])
    avg_hours = round(total_hours / total_days, 1) if total_days > 0 else 0
    
    statistics = {
        "total_days": total_days,
        "total_hours": total_hours,
        "late_count": late_count,
        "avg_hours": avg_hours
    }
    
    return {
        "records": record_list,
        "statistics": statistics
    }

# 채용 게시판 API
@app.get("/api/jobs")
async def get_job_posts(
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius: Optional[float] = 10,
    db: Session = Depends(get_db)
):
    """채용 공고 목록 조회"""
    
    location_filter = None
    if latitude and longitude:
        location_filter = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius
        }
    
    result = JobBoardService.get_job_posts(
        db=db,
        page=page,
        limit=limit,
        search=search,
        location_filter=location_filter
    )
    
    return result

@app.get("/api/jobs/{job_id}")
async def get_job_detail(job_id: int, db: Session = Depends(get_db)):
    """채용 공고 상세 조회"""
    return JobBoardService.get_job_post_detail(job_id, db)

@app.post("/api/jobs")
async def create_job_post(
    job_data: JobPostCreate,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """채용 공고 작성"""
    
    job_dict = job_data.dict()
    result = JobBoardService.create_job_post(job_dict, current_user.id, db)
    
    if result["success"]:
        return {"message": result["message"], "job_id": result["job_post"].id}
    else:
        raise HTTPException(status_code=400, detail=result["error"])

@app.get("/api/jobs/{job_id}/application-status")
async def get_application_status(
    job_id: int,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """사용자의 특정 공고 지원 상태 조회"""
    try:
        application = db.query(JobApplication).filter(
            JobApplication.job_post_id == job_id,
            JobApplication.user_id == current_user.id
        ).first()
        
        if application:
            return {
                "has_applied": True,
                "application": {
                    "id": application.id,
                    "job_post_id": application.job_post_id,
                    "status": application.status,
                    "payment_status": "paid" if application.deposit_paid else "unpaid",
                    "applied_at": application.applied_at.isoformat() if application.applied_at else None,
                    "approved_at": application.reviewed_at.isoformat() if application.reviewed_at else None
                }
            }
        else:
            return {
                "has_applied": False,
                "application": None
            }
    except Exception as e:
        print(f"Error getting application status: {str(e)}")
        raise HTTPException(status_code=500, detail="지원 상태 조회 중 오류가 발생했습니다.")

@app.post("/api/jobs/{job_id}/apply")
async def apply_to_job(
    job_id: int,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """채용 공고 신청"""
    try:
        result = JobBoardService.apply_to_job(job_id, current_user.id, db)
        
        if result["success"]:
            # 승인된 경우에만 결제 요청 생성
            if result["application"].status == "approved":
                payment_manager = PaymentManager()
                payment_result = payment_manager.initiate_deposit_payment(
                    result["application"].id,
                    current_user.full_name,
                    db
                )
                
                if payment_result["success"]:
                    return {
                        "message": result["message"],
                        "application_id": result["application"].id,
                        "payment_url": payment_result["payment_url"],
                        "auto_approved": result.get("auto_approved", False)
                    }
                else:
                    # 결제 실패해도 신청은 유지
                    return {
                        "message": result["message"] + " (결제 처리 오류)",
                        "application_id": result["application"].id,
                        "auto_approved": result.get("auto_approved", False)
                    }
            else:
                # 대기 중인 경우
                return {
                    "message": result["message"],
                    "application_id": result["application"].id,
                    "auto_approved": result.get("auto_approved", False)
                }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
            
    except Exception as e:
        print(f"Apply error: {e}")  # 서버 로그용
        raise HTTPException(status_code=500, detail=f"신청 처리 중 오류가 발생했습니다: {str(e)}")

# 공고 신청자 목록 조회 API
@app.get("/api/admin/jobs/{job_id}/applications")
async def get_job_applications(
    job_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """공고 신청자 목록 조회"""
    result = JobBoardService.get_job_applications(job_id, db)
    
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=404, detail=result["error"])

# 신청 승인/거절 API
class ApplicationReviewRequest(BaseModel):
    action: str
    reason: Optional[str] = None

@app.post("/api/admin/applications/{application_id}/review")
async def review_application(
    application_id: int,
    request: ApplicationReviewRequest,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """신청 승인/거절 처리"""
    if request.action not in ["approve", "reject"]:
        raise HTTPException(status_code=400, detail="잘못된 액션입니다.")
    
    result = JobBoardService.review_application(
        application_id, request.action, current_user.id, request.reason, db
    )
    
    if result["success"]:
        return {"message": result["message"]}
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# 공고 상태 토글 API
@app.post("/api/admin/jobs/{job_id}/toggle-status")
async def toggle_job_status(
    job_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """공고 상태 토글 (인원마감/재개방)"""
    result = JobBoardService.toggle_job_status(job_id, db)
    
    if result["success"]:
        return {
            "message": result["message"],
            "manually_closed": result["manually_closed"]
        }
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# 환불 API
@app.post("/api/admin/applications/{application_id}/refund")
async def process_refund(
    application_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """관리자 직접 환불 처리"""
    try:
        application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
        if not application:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
        
        if not application.deposit_paid:
            raise HTTPException(status_code=400, detail="결제되지 않은 보증금은 환불할 수 없습니다.")
        
        if application.deposit_refunded:
            raise HTTPException(status_code=400, detail="이미 환불된 보증금입니다.")
        
        # 환불 처리 (실제로는 결제 서비스 API 호출)
        # TODO: 실제 환불 API 호출 구현
        
        # 환불 상태 업데이트
        application.deposit_refunded = True
        
        # PaymentLog에 환불 기록 추가
        refund_log = PaymentLog(
            application_id=application_id,
            payment_id=f"REFUND_{application.payment_id}",
            payment_method=application.payment_method,
            amount=-application.deposit_amount,  # 음수로 환불 표시
            status="completed",
            payment_date=datetime.now()
        )
        db.add(refund_log)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"{application.deposit_amount}원이 환불 처리되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"환불 처리 중 오류가 발생했습니다: {str(e)}")

@app.post("/api/auto-refund/{application_id}")
async def auto_refund_on_completion(
    application_id: int,
    db: Session = Depends(get_db)
):
    """근무 완료 시 자동 환불"""
    try:
        application = db.query(JobApplication).filter(JobApplication.id == application_id).first()
        if not application:
            return {"success": False, "message": "신청을 찾을 수 없습니다."}
        
        if not application.deposit_paid or application.deposit_refunded:
            return {"success": False, "message": "환불 조건이 맞지 않습니다."}
        
        if application.status != "completed":
            return {"success": False, "message": "근무가 완료되지 않았습니다."}
        
        # 자동 환불 처리
        # TODO: 실제 환불 API 호출 구현
        
        application.deposit_refunded = True
        
        # 환불 로그 기록
        refund_log = PaymentLog(
            application_id=application_id,
            payment_id=f"AUTO_REFUND_{application.payment_id}",
            payment_method=application.payment_method,
            amount=-application.deposit_amount,
            status="completed",
            payment_date=datetime.now()
        )
        db.add(refund_log)
        
        db.commit()
        
        return {
            "success": True,
            "message": f"근무 완료로 인해 {application.deposit_amount}원이 자동 환불되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        return {"success": False, "message": f"자동 환불 중 오류가 발생했습니다: {str(e)}"}

@app.delete("/api/admin/jobs/{job_id}")
async def delete_job_post(
    job_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """공고 삭제"""
    try:
        # 공고 조회
        job_post = db.query(JobPost).filter(JobPost.id == job_id).first()
        if not job_post:
            raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
        
        # 관련 신청 정보들 삭제
        applications = db.query(JobApplication).filter(JobApplication.job_post_id == job_id).all()
        for application in applications:
            # 결제 로그 삭제
            db.query(PaymentLog).filter(PaymentLog.application_id == application.id).delete()
            # 신청 삭제
            db.delete(application)
        
        # 공고 삭제
        db.delete(job_post)
        db.commit()
        
        return {
            "success": True,
            "message": "공고가 성공적으로 삭제되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"공고 삭제 중 오류가 발생했습니다: {str(e)}")

@app.delete("/api/my-applications/{application_id}")
async def cancel_application(
    application_id: int,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """신청 취소"""
    try:
        # 신청 조회
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id,
            JobApplication.user_id == current_user.id
        ).first()
        
        if not application:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다.")
        
        # 취소 가능한 상태 확인
        if application.status in ["completed", "working"]:
            raise HTTPException(status_code=400, detail="이미 근무가 시작된 신청은 취소할 수 없습니다.")
        
        if application.deposit_paid and not application.deposit_refunded:
            raise HTTPException(status_code=400, detail="보증금이 결제된 신청은 관리자에게 문의하세요.")
        
        # 관련 데이터 삭제
        # 결제 로그 삭제 (보증금이 결제되지 않은 경우)
        if not application.deposit_paid:
            db.query(PaymentLog).filter(PaymentLog.application_id == application_id).delete()
        
        # 신청 삭제
        db.delete(application)
        db.commit()
        
        return {
            "success": True,
            "message": "신청이 성공적으로 취소되었습니다."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"신청 취소 중 오류가 발생했습니다: {str(e)}")

@app.get("/api/my-applications")
async def get_my_applications(
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """나의 신청 목록"""
    return JobBoardService.get_user_applications(current_user.id, db)

# 결제 API
@app.post("/api/payment/callback")
async def payment_callback(
    callback_data: PaymentCallback,
    db: Session = Depends(get_db)
):
    """네이버페이 결제 콜백"""
    
    if callback_data.status == "SUCCESS":
        payment_manager = PaymentManager()
        result = payment_manager.complete_deposit_payment(
            callback_data.payment_id,
            callback_data.application_id,
            db
        )
        
        if result["success"]:
            # 근무지 위치 업데이트
            location_result = JobBoardService.update_employee_work_location(
                callback_data.application_id, db
            )
            
            return {
                "message": "결제가 완료되었습니다. 근무지가 설정되었습니다.",
                "work_location": location_result.get("work_site")
            }
        else:
            raise HTTPException(status_code=400, detail=result["error"])
    else:
        raise HTTPException(status_code=400, detail="결제가 실패했습니다.")

@app.post("/api/work-complete/{application_id}")
async def complete_work(
    application_id: int,
    current_user: User = Depends(verify_token),
    db: Session = Depends(get_db)
):
    """근무 완료 처리 및 보증금 환불"""
    
    # 근무 완료 처리
    work_result = JobBoardService.complete_work(application_id, db)
    
    if work_result["success"]:
        # 자동 환불 처리
        refund_response = await auto_refund_on_completion(application_id, db)
        
        if refund_response["success"]:
            return {
                "message": "근무가 완료되었고 보증금이 환불되었습니다."
            }
        else:
            return {
                "message": "근무는 완료되었지만 환불 처리 중 오류가 발생했습니다.",
                "error": refund_response["message"]
            }
    else:
        raise HTTPException(status_code=400, detail=work_result["error"])

# 지도/위치 API
@app.post("/api/geocoding/address-to-coordinates")
async def address_to_coordinates(
    request_data: AddressToCoordinatesRequest,
    current_user: User = Depends(verify_token)
):
    """주소를 위도, 경도로 변환"""
    
    if not request_data.address.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="주소를 입력해주세요."
        )
    
    result = GeocodingService.get_coordinates_from_address(request_data.address)
    
    if result["success"]:
        return {
            "success": True,
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "address": result["address"],
            "message": result.get("message", "주소를 좌표로 변환했습니다.")
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

@app.get("/api/geocoding/coordinates-to-address")
async def coordinates_to_address(
    latitude: float,
    longitude: float,
    current_user: User = Depends(verify_token)
):
    """좌표를 주소로 변환"""
    
    if not GeocodingService.validate_coordinates(latitude, longitude):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="잘못된 좌표값입니다."
        )
    
    result = GeocodingService.get_address_from_coordinates(latitude, longitude)
    
    if result["success"]:
        return {
            "success": True,
            "address": result["address"],
            "message": result.get("message", "좌표를 주소로 변환했습니다.")
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"]
        )

# 레거시 API (기존 호환성을 위해 유지)
@app.get("/employees")
async def legacy_get_employees(db: Session = Depends(get_db)):
    """레거시: 직원 목록 조회"""
    employees = db.query(Employee).all()
    result = []
    for emp in employees:
        user = db.query(User).filter(User.id == emp.user_id).first()
        result.append({
            "id": emp.id,
            "name": user.full_name,
            "team": emp.department.name if emp.department else None
        })
    return result

@app.get("/sites")
async def legacy_get_sites(db: Session = Depends(get_db)):
    """레거시: 근무지 목록 조회"""
    from app.models.database import Site
    sites = db.query(Site).all()
    return [
        {
            "id": site.id,
            "name": site.name,
            "lat": site.latitude,
            "lng": site.longitude,
            "radius_m": site.geofence_radius
        }
        for site in sites
    ]

@app.post("/track-location")
async def legacy_track_location(
    event_data: dict,
    db: Session = Depends(get_db)
):
    """레거시: 위치 추적 (기존 모바일 앱 호환성)"""
    employee_id = event_data.get('employee_id')
    
    if not employee_id:
        raise HTTPException(status_code=400, detail="Employee ID required")
    
    location_data = {
        'latitude': event_data['lat'],
        'longitude': event_data['lng'],
        'accuracy': event_data.get('accuracy', 10.0)
    }
    
    result = LocationService.process_location_update(employee_id, location_data, db)
    
    return {
        "status": "success",
        "type": result["event_type"].upper(),
        "site": result["site"],
        "distance": result["distance"],
        "timestamp": datetime.now()
    }

# 관리자 전용 보증금 환불 처리 API
@app.post("/api/admin/refund/{application_id}")
async def admin_process_refund(
    application_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """관리자가 수동으로 보증금 환불 처리"""
    try:
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id
        ).first()
        
        if not application:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다.")
        
        if not application.deposit_paid:
            raise HTTPException(status_code=400, detail="보증금이 결제되지 않았습니다.")
        
        if application.deposit_refunded:
            raise HTTPException(status_code=400, detail="이미 환불 처리되었습니다.")
        
        # 환불 처리 (관리자 강제 환불 모드)
        payment_manager = PaymentManager()
        refund_result = payment_manager.process_deposit_refund(application_id, db, force_refund=True)
        
        if refund_result["success"]:
            return {"message": refund_result["message"]}
        else:
            raise HTTPException(status_code=400, detail=refund_result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"환불 처리 중 오류가 발생했습니다: {str(e)}")

# 관리자 전용 근무 완료 처리 API
@app.post("/api/admin/complete-work/{application_id}")
async def admin_complete_work(
    application_id: int,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """관리자가 수동으로 근무 완료 처리"""
    try:
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id
        ).first()
        
        if not application:
            raise HTTPException(status_code=404, detail="신청 정보를 찾을 수 없습니다.")
        
        if application.status != "working":
            raise HTTPException(status_code=400, detail="근무 중이 아닌 신청입니다.")
        
        # 근무 완료 처리
        work_result = JobBoardService.complete_work(application_id, db)
        
        if work_result["success"]:
            return {"message": work_result["message"]}
        else:
            raise HTTPException(status_code=400, detail=work_result["error"])
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"근무 완료 처리 중 오류가 발생했습니다: {str(e)}")
@app.post("/api/admin/reports/generate")
async def generate_report(
    report_type: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """리포트 생성"""
    try:
        if report_type == "daily":
            if not start_date:
                target_date = date.today()
            else:
                target_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            
            report_data = ReportService.generate_daily_report(target_date, db)
            
        elif report_type == "weekly":
            if not start_date:
                # 이번 주 월요일
                today = date.today()
                start_date_obj = today - timedelta(days=today.weekday())
            else:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            
            report_data = ReportService.generate_weekly_report(start_date_obj, db)
            
        elif report_type == "monthly":
            if year and month:
                report_data = ReportService.generate_monthly_report(year, month, db)
            else:
                today = date.today()
                report_data = ReportService.generate_monthly_report(today.year, today.month, db)
                
        elif report_type == "violations":
            if start_date and end_date:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                # 최근 30일
                end_date_obj = date.today()
                start_date_obj = end_date_obj - timedelta(days=30)
            
            report_data = ReportService.generate_violation_report(start_date_obj, end_date_obj, db)
            
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 리포트 유형입니다.")
        
        return {
            "success": True,
            "message": "리포트가 생성되었습니다.",
            "data": report_data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 생성 중 오류가 발생했습니다: {str(e)}")

@app.get("/api/admin/reports/export/{report_type}")
async def export_report(
    report_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """리포트 CSV 내보내기"""
    try:
        # 먼저 리포트 데이터 생성
        if report_type == "daily":
            if not start_date:
                target_date = date.today()
            else:
                target_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            report_data = ReportService.generate_daily_report(target_date, db)
            filename = f"daily_report_{target_date.strftime('%Y%m%d')}.csv"
            
        elif report_type == "weekly":
            if not start_date:
                today = date.today()
                start_date_obj = today - timedelta(days=today.weekday())
            else:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            report_data = ReportService.generate_weekly_report(start_date_obj, db)
            filename = f"weekly_report_{start_date_obj.strftime('%Y%m%d')}.csv"
            
        elif report_type == "monthly":
            if year and month:
                report_data = ReportService.generate_monthly_report(year, month, db)
                filename = f"monthly_report_{year}{month:02d}.csv"
            else:
                today = date.today()
                report_data = ReportService.generate_monthly_report(today.year, today.month, db)
                filename = f"monthly_report_{today.year}{today.month:02d}.csv"
                
        elif report_type == "violations":
            if start_date and end_date:
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end_date_obj = date.today()
                start_date_obj = end_date_obj - timedelta(days=30)
            report_data = ReportService.generate_violation_report(start_date_obj, end_date_obj, db)
            filename = f"violations_report_{start_date_obj.strftime('%Y%m%d')}_{end_date_obj.strftime('%Y%m%d')}.csv"
            
        else:
            raise HTTPException(status_code=400, detail="지원하지 않는 리포트 유형입니다.")
        
        # CSV 생성
        csv_content = ReportService.export_report_to_csv(report_data)
        
        # CSV를 바이트 스트림으로 변환
        csv_bytes = csv_content.encode('utf-8-sig')  # BOM 추가로 한글 깨짐 방지
        
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 내보내기 중 오류가 발생했습니다: {str(e)}")

# 위반 사항 자동 감지 및 생성 API
@app.post("/api/admin/violations/detect")
async def detect_violations(
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """위반 사항 자동 감지 및 생성"""
    try:
        # ViolationDetectionService를 사용한 종합적인 위반 사항 감지
        result = ViolationDetectionService.run_comprehensive_detection(db)
        
        if result["success"]:
            # 감지된 위반사항 유형 리스트 생성
            violation_types = []
            if result["attendance_violations"] > 0:
                violation_types.append("출근기록위반")
            if result["location_violations"] > 0:
                violation_types.append("위치위반")
            if result["pattern_violations"] > 0:
                violation_types.append("패턴위반")
            
            return {
                "success": True,
                "message": f"{result['total_detected']}건의 위반사항이 감지되었습니다.",
                "detected_count": result["total_detected"],
                "violation_types": violation_types,
                "details": {
                    "attendance_violations": result["attendance_violations"],
                    "location_violations": result["location_violations"],
                    "pattern_violations": result["pattern_violations"],
                    "processing_time": f"{result['processing_time_seconds']:.2f}초"
                }
            }
        else:
            return {
                "success": False,
                "message": "위반사항 감지에 실패했습니다.",
                "detected_count": 0,
                "violation_types": []
            }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"위반사항 감지 중 오류가 발생했습니다: {str(e)}")

@app.put("/api/admin/violations/{violation_id}/review")
async def review_violation(
    violation_id: int,
    action: str,  # acknowledge, resolve, dismiss
    notes: Optional[str] = None,
    current_user: User = Depends(require_manager_or_admin),
    db: Session = Depends(get_db)
):
    """위반사항 검토 및 처리"""
    violation = db.query(Violation).filter(Violation.id == violation_id).first()
    if not violation:
        raise HTTPException(status_code=404, detail="위반사항을 찾을 수 없습니다.")
    
    if action == "acknowledge":
        violation.status = "acknowledged"
    elif action == "resolve":
        violation.status = "resolved"
    elif action == "dismiss":
        violation.status = "dismissed"
    else:
        raise HTTPException(status_code=400, detail="잘못된 처리 액션입니다.")
    
    violation.reviewed_by = current_user.id
    violation.reviewed_at = datetime.now()
    if notes:
        violation.resolution_notes = notes
    
    db.commit()
    
    return {
        "success": True,
        "message": f"위반사항이 {action} 처리되었습니다."
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)