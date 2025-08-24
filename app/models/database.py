from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from passlib.context import CryptContext
import uuid

DATABASE_URL = "sqlite:///./hrms_attendance.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 암호화 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    """사용자 계정 (관리자/직원 공통)"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="employee")  # admin, manager, employee
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)
    
    # 관계
    employee_profile = relationship("Employee", back_populates="user", uselist=False)

class Company(Base):
    """회사 정보"""
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    business_number = Column(String(20), unique=True, nullable=False)
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # 관계
    departments = relationship("Department", back_populates="company")
    sites = relationship("Site", back_populates="company")

class Department(Base):
    """부서 정보"""
    __tablename__ = "departments"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=True)
    
    # 관계
    company = relationship("Company", back_populates="departments")
    employees = relationship("Employee", back_populates="department")

class Employee(Base):
    """직원 프로필"""
    __tablename__ = "employees"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    employee_number = Column(String(20), unique=True, nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    position = Column(String(50), nullable=True)
    hire_date = Column(DateTime, nullable=False)
    phone = Column(String(20), nullable=True)
    emergency_contact = Column(String(100), nullable=True)
    
    # 근무 설정
    work_type = Column(String(20), default="office")  # office, field, remote, hybrid
    default_work_hours = Column(Integer, default=8)  # 기본 근무시간
    overtime_allowed = Column(Boolean, default=False)
    
    # 위치 설정
    assigned_sites = Column(Text, nullable=True)  # JSON으로 저장
    gps_tracking_enabled = Column(Boolean, default=True)
    location_update_interval = Column(Integer, default=300)  # 초 단위
    
    # 관계
    user = relationship("User", back_populates="employee_profile")
    department = relationship("Department", back_populates="employees")
    attendance_records = relationship("AttendanceRecord", back_populates="employee")
    location_events = relationship("LocationEvent", back_populates="employee")

class Site(Base):
    """근무지/사업장"""
    __tablename__ = "sites"
    
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geofence_radius = Column(Float, default=100.0)  # 미터 단위
    
    # 운영 시간
    operating_hours_start = Column(String(5), default="09:00")  # HH:MM 형식
    operating_hours_end = Column(String(5), default="18:00")
    
    # 설정
    check_in_required = Column(Boolean, default=True)
    check_out_required = Column(Boolean, default=True)
    break_time_tracking = Column(Boolean, default=True)
    
    # 관계
    company = relationship("Company", back_populates="sites")
    attendance_records = relationship("AttendanceRecord", back_populates="site")
    location_events = relationship("LocationEvent", back_populates="site")

class AttendanceRecord(Base):
    """출근 기록"""
    __tablename__ = "attendance_records"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=False)
    
    # 출근 정보
    check_in_time = Column(DateTime, nullable=True)
    check_out_time = Column(DateTime, nullable=True)
    scheduled_start = Column(DateTime, nullable=True)
    scheduled_end = Column(DateTime, nullable=True)
    
    # 계산된 시간
    total_work_minutes = Column(Integer, default=0)
    break_minutes = Column(Integer, default=0)
    overtime_minutes = Column(Integer, default=0)
    
    # 상태
    status = Column(String(20), default="scheduled")  # scheduled, checked_in, completed, absent
    is_late = Column(Boolean, default=False)
    is_early_leave = Column(Boolean, default=False)
    
    # 위치 정보
    check_in_location = Column(String(100), nullable=True)
    check_out_location = Column(String(100), nullable=True)
    
    # 메모/사유
    notes = Column(Text, nullable=True)
    admin_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    
    # 관계
    employee = relationship("Employee", back_populates="attendance_records")
    site = relationship("Site", back_populates="attendance_records")
    violations = relationship("Violation", back_populates="attendance_record")

class LocationEvent(Base):
    """위치 이벤트 (GPS 추적)"""
    __tablename__ = "location_events"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    
    # 위치 정보
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)
    speed = Column(Float, nullable=True)
    
    # 이벤트 정보
    event_type = Column(String(20), nullable=False)  # check_in, check_out, location_update, geofence_enter, geofence_exit
    timestamp = Column(DateTime, nullable=False, default=datetime.now)
    
    # 검증 정보
    is_mock_location = Column(Boolean, default=False)
    device_info = Column(String(255), nullable=True)
    network_type = Column(String(20), nullable=True)  # wifi, cellular, gps
    
    # 관계
    employee = relationship("Employee", back_populates="location_events")
    site = relationship("Site", back_populates="location_events")

class Violation(Base):
    """규정 위반 기록"""
    __tablename__ = "violations"
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    attendance_record_id = Column(Integer, ForeignKey("attendance_records.id"), nullable=True)
    
    # 위반 정보
    violation_type = Column(String(50), nullable=False)  # late_arrival, early_departure, unauthorized_break, location_spoofing, etc.
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    
    # 시간 정보
    occurred_at = Column(DateTime, nullable=False)
    duration_minutes = Column(Integer, nullable=True)
    
    # 상세 정보
    description = Column(Text, nullable=False)
    auto_detected = Column(Boolean, default=True)
    evidence_data = Column(Text, nullable=True)  # JSON 형태의 증거 데이터
    
    # 처리 상태
    status = Column(String(20), default="pending")  # pending, acknowledged, resolved, dismissed
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.now)
    
    # 관계
    attendance_record = relationship("AttendanceRecord", back_populates="violations")

class JobPost(Base):
    """채용 공고/일자리 게시글"""
    __tablename__ = "job_posts"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    company_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    requirements = Column(Text, nullable=True)
    salary = Column(String(100), nullable=True)
    work_hours = Column(String(100), nullable=True)
    work_period = Column(String(100), nullable=True)  # 근무 기간 추가
    
    # 근무지 주소 정보
    work_address = Column(Text, nullable=False)
    work_latitude = Column(Float, nullable=False)
    work_longitude = Column(Float, nullable=False)
    geofence_radius = Column(Float, default=100.0)  # 미터 단위
    
    # 게시글 정보
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    
    # 마감일
    deadline = Column(DateTime, nullable=True)
    
    # 모집 설정
    max_applicants = Column(Integer, nullable=True)  # 최대 모집인원
    auto_approval = Column(Boolean, default=False)  # 자동승인 여부
    status = Column(String(20), default="active")  # active, full, expired
    manually_closed = Column(Boolean, default=False)  # 운영자가 수동으로 마감한 경우
    
    # 관계
    applications = relationship("JobApplication", back_populates="job_post")

class JobApplication(Base):
    """일자리 신청"""
    __tablename__ = "job_applications"
    
    id = Column(Integer, primary_key=True, index=True)
    job_post_id = Column(Integer, ForeignKey("job_posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # 신청 정보
    applied_at = Column(DateTime, default=datetime.now)
    status = Column(String(20), default="pending")  # pending, approved, rejected, working, completed
    
    # 승인/거절 정보
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    # 결제 정보
    payment_id = Column(String(100), nullable=True)
    deposit_amount = Column(Integer, default=5000)  # 보증금 (원)
    deposit_paid = Column(Boolean, default=False)
    deposit_refunded = Column(Boolean, default=False)
    payment_method = Column(String(20), default="naver_pay")
    
    # 근무 정보
    work_start_date = Column(DateTime, nullable=True)
    work_end_date = Column(DateTime, nullable=True)
    work_completed = Column(Boolean, default=False)
    
    # 관계
    job_post = relationship("JobPost", back_populates="applications")
    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    payment_logs = relationship("PaymentLog", back_populates="application")

class PaymentLog(Base):
    """결제 로그"""
    __tablename__ = "payment_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"), nullable=False)
    
    # 결제 정보
    payment_type = Column(String(20), nullable=False)  # deposit, refund
    amount = Column(Integer, nullable=False)
    payment_method = Column(String(20), default="naver_pay")
    payment_id = Column(String(100), nullable=True)  # 네이버페이 결제 ID
    
    # 상태
    status = Column(String(20), default="pending")  # pending, completed, failed, cancelled
    
    # 시간 정보
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    
    # 메타데이터
    payment_data = Column(Text, nullable=True)  # JSON 형태의 결제 상세 정보
    error_message = Column(Text, nullable=True)
    
    # 관계
    application = relationship("JobApplication", back_populates="payment_logs")

class AuditLog(Base):
    """감사 로그"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.now)

# 테이블 생성
Base.metadata.create_all(bind=engine)  # 새로운 테이블 생성 (기존 테이블은 유지)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 암호화 관련 함수들
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)