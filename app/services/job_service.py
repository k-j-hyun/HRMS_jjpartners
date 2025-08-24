from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from app.models.database import JobPost, JobApplication, User, Employee, Site
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import math

class JobBoardService:
    """채용 게시판 서비스"""
    
    @staticmethod
    def create_job_post(job_data: Dict, author_id: int, db: Session) -> Dict:
        """채용 공고 작성"""
        try:
            # 날짜 처리
            deadline = None
            if job_data.get("deadline"):
                if isinstance(job_data["deadline"], str):
                    try:
                        deadline = datetime.fromisoformat(job_data["deadline"].replace('Z', '+00:00'))
                    except:
                        deadline = None
                else:
                    deadline = job_data["deadline"]
            
            job_post = JobPost(
                title=job_data["title"],
                company_name=job_data["company_name"],
                description=job_data["description"],
                requirements=job_data.get("requirements"),
                salary=job_data.get("salary"),
                work_hours=job_data.get("work_hours"),
                work_address=job_data["work_address"],
                work_latitude=float(job_data["work_latitude"]),
                work_longitude=float(job_data["work_longitude"]),
                geofence_radius=float(job_data.get("geofence_radius", 100.0)),
                author_id=author_id,
                deadline=deadline,
                max_applicants=job_data.get("max_applicants"),
                auto_approval=job_data.get("auto_approval", False),
                status="active",
                is_active=True,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            db.add(job_post)
            db.commit()
            db.refresh(job_post)
            
            return {
                "success": True,
                "job_post": job_post,
                "message": "채용 공고가 등록되었습니다."
            }
            
        except Exception as e:
            db.rollback()
            print(f"JobPost creation error: {e}")  # 디버그용
            return {
                "success": False,
                "error": f"채용 공고 등록 중 오류가 발생했습니다: {str(e)}"
            }
    
    @staticmethod
    def get_job_posts(
        db: Session, 
        page: int = 1, 
        limit: int = 20,
        search: Optional[str] = None,
        location_filter: Optional[Dict] = None
    ) -> Dict:
        """채용 공고 목록 조회"""
        
        query = db.query(JobPost).filter(JobPost.is_active == True)
        
        # 검색 필터
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    JobPost.title.ilike(search_term),
                    JobPost.company_name.ilike(search_term),
                    JobPost.description.ilike(search_term),
                    JobPost.work_address.ilike(search_term)
                )
            )
        
        # 위치 필터 (사용자 위치 기준 반경 내)
        if location_filter:
            user_lat = location_filter["latitude"]
            user_lng = location_filter["longitude"]
            radius_km = location_filter.get("radius", 10)  # 기본 10km
            
            # Haversine 공식을 사용한 거리 계산 (근사치)
            lat_diff = func.abs(JobPost.work_latitude - user_lat)
            lng_diff = func.abs(JobPost.work_longitude - user_lng)
            
            query = query.filter(
                and_(
                    lat_diff < (radius_km / 111.0),  # 위도 1도 ≈ 111km
                    lng_diff < (radius_km / (111.0 * func.cos(func.radians(user_lat))))
                )
            )
        
        # 마감일 필터 (아직 마감되지 않은 공고만)
        current_time = datetime.now()
        query = query.filter(
            or_(
                JobPost.deadline.is_(None),
                JobPost.deadline > current_time
            )
        )
        
        # 정렬 (최신순)
        query = query.order_by(JobPost.created_at.desc())
        
        # 페이징
        total_count = query.count()
        offset = (page - 1) * limit
        job_posts = query.offset(offset).limit(limit).all()
        
        # 결과 가공
        job_list = []
        for job in job_posts:
            # 신청자 수 계산
            application_count = db.query(JobApplication).filter(
                JobApplication.job_post_id == job.id
            ).count()
            
            # 승인된 신청자 수
            approved_count = db.query(JobApplication).filter(
                JobApplication.job_post_id == job.id,
                JobApplication.status.in_(["approved", "working", "completed"])
            ).count()
            
            # 공고 상태 결정
            job_status = JobBoardService._get_job_status(job, approved_count)
            
            # 거리 계산 (위치 필터가 있는 경우)
            distance = None
            if location_filter:
                distance = JobBoardService._calculate_distance(
                    user_lat, user_lng,
                    job.work_latitude, job.work_longitude
                )
            
            job_list.append({
                "id": job.id,
                "title": job.title,
                "company_name": job.company_name,
                "description": job.description[:200] + "..." if len(job.description) > 200 else job.description,
                "salary": job.salary,
                "work_hours": job.work_hours,
                "work_period": job.work_period,  # 근무 기간 추가
                "work_address": job.work_address,
                "application_count": application_count,
                "approved_count": approved_count,
                "max_applicants": job.max_applicants,
                "auto_approval": job.auto_approval,
                "manually_closed": job.manually_closed,
                "status": job_status,
                "created_at": job.created_at,
                "deadline": job.deadline,
                "distance": distance
            })
        
        return {
            "success": True,
            "job_posts": job_list,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "total_pages": math.ceil(total_count / limit)
        }
    
    @staticmethod
    def get_job_post_detail(job_id: int, db: Session) -> Dict:
        """채용 공고 상세 조회"""
        
        job_post = db.query(JobPost).filter(
            JobPost.id == job_id,
            JobPost.is_active == True
        ).first()
        
        if not job_post:
            return {
                "success": False,
                "error": "채용 공고를 찾을 수 없습니다."
            }
        
        # 작성자 정보
        author = db.query(User).filter(User.id == job_post.author_id).first()
        
        # 신청자 정보
        applications = db.query(JobApplication).filter(
            JobApplication.job_post_id == job_id
        ).all()
        
        application_stats = {
            "total": len(applications),
            "pending": len([app for app in applications if app.status == "pending"]),
            "approved": len([app for app in applications if app.status == "approved"]),
            "working": len([app for app in applications if app.status == "working"]),
            "completed": len([app for app in applications if app.status == "completed"])
        }
        
        return {
            "success": True,
            "job_post": {
                "id": job_post.id,
                "title": job_post.title,
                "company_name": job_post.company_name,
                "description": job_post.description,
                "requirements": job_post.requirements,
                "salary": job_post.salary,
                "work_hours": job_post.work_hours,
                "work_period": job_post.work_period,  # 근무 기간 추가
                "work_address": job_post.work_address,
                "work_latitude": job_post.work_latitude,
                "work_longitude": job_post.work_longitude,
                "geofence_radius": job_post.geofence_radius,
                "max_applicants": job_post.max_applicants,
                "auto_approval": job_post.auto_approval,
                "manually_closed": job_post.manually_closed,
                "author": {
                    "id": author.id,
                    "name": author.full_name,
                    "username": author.username
                } if author else None,
                "created_at": job_post.created_at,
                "updated_at": job_post.updated_at,
                "deadline": job_post.deadline,
                "application_stats": application_stats
            }
        }
    
    @staticmethod
    def apply_to_job(job_id: int, user_id: int, db: Session) -> Dict:
        """채용 공고 신청"""
        
        # 중복 신청 확인
        existing_application = db.query(JobApplication).filter(
            JobApplication.job_post_id == job_id,
            JobApplication.user_id == user_id
        ).first()
        
        if existing_application:
            return {
                "success": False,
                "error": "이미 신청한 채용 공고입니다."
            }
        
        # 채용 공고 존재 확인
        job_post = db.query(JobPost).filter(
            JobPost.id == job_id,
            JobPost.is_active == True
        ).first()
        
        if not job_post:
            return {
                "success": False,
                "error": "채용 공고를 찾을 수 없습니다."
            }
        
        # 마감일 확인
        if job_post.deadline and job_post.deadline < datetime.now():
            return {
                "success": False,
                "error": "마감된 채용 공고입니다."
            }
        
        # 수동 마감 확인
        if job_post.manually_closed:
            return {
                "success": False,
                "error": "인원마감된 채용 공고입니다."
            }
        
        # 인원 제한 확인
        if job_post.max_applicants:
            approved_count = db.query(JobApplication).filter(
                JobApplication.job_post_id == job_id,
                JobApplication.status.in_(["approved", "working", "completed"])
            ).count()
            
            if approved_count >= job_post.max_applicants:
                return {
                    "success": False,
                    "error": "이미 모집인원이 가득 찬 채용 공고입니다."
                }
        
        try:
            # 신청 생성
            initial_status = "approved" if job_post.auto_approval else "pending"
            
            application = JobApplication(
                job_post_id=job_id,
                user_id=user_id,
                status=initial_status
            )
            
            # 자동 승인인 경우 승인 정보 설정
            if job_post.auto_approval:
                application.reviewed_at = datetime.now()
                application.reviewed_by = job_post.author_id  # 작성자가 자동 승인
            
            db.add(application)
            db.commit()
            db.refresh(application)
            
            message = "채용 공고에 신청되었습니다."
            if job_post.auto_approval:
                message += " 자동으로 승인되었습니다."
            else:
                message += " 관리자 승인을 기다리세요."
            
            # 보증금 결제 요청은 승인된 경우에만
            if application.status == "approved":
                message += " 보증금을 결제해주세요."
            
            return {
                "success": True,
                "application": application,
                "message": message,
                "auto_approved": job_post.auto_approval
            }
            
        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "error": f"신청 중 오류가 발생했습니다: {str(e)}"
            }
    
    @staticmethod
    def update_employee_work_location(application_id: int, db: Session) -> Dict:
        """직원의 근무지 위치를 신청한 게시글 주소로 변경"""
        
        # 신청 정보 조회
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id,
            JobApplication.deposit_paid == True
        ).first()
        
        if not application:
            return {
                "success": False,
                "error": "유효한 신청 정보를 찾을 수 없습니다."
            }
        
        # 직원 정보 조회
        employee = db.query(Employee).filter(
            Employee.user_id == application.user_id
        ).first()
        
        if not employee:
            return {
                "success": False,
                "error": "직원 정보를 찾을 수 없습니다."
            }
        
        # 해당 게시글의 근무지 정보로 새로운 Site 생성 또는 기존 Site 업데이트
        job_post = application.job_post
        
        # 기본 회사 조회 (첫 번째 회사 사용)
        from app.models.database import Company
        default_company = db.query(Company).first()
        if not default_company:
            return {
                "success": False,
                "error": "기본 회사 정보를 찾을 수 없습니다."
            }
        
        # 동일한 위치의 Site가 이미 있는지 확인
        existing_site = db.query(Site).filter(
            Site.latitude == job_post.work_latitude,
            Site.longitude == job_post.work_longitude
        ).first()
        
        if not existing_site:
            # 새로운 근무지 생성
            new_site = Site(
                company_id=default_company.id,
                name=f"{job_post.company_name} - {job_post.title}",
                address=job_post.work_address,
                latitude=job_post.work_latitude,
                longitude=job_post.work_longitude,
                geofence_radius=job_post.geofence_radius
            )
            db.add(new_site)
            db.commit()
            db.refresh(new_site)
            work_site = new_site
        else:
            work_site = existing_site
        
        # 직원의 assigned_sites 업데이트
        import json
        assigned_sites = []
        if employee.assigned_sites:
            try:
                assigned_sites = json.loads(employee.assigned_sites)
            except:
                assigned_sites = []
        
        # 새로운 근무지 추가 (중복 방지)
        if work_site.id not in assigned_sites:
            assigned_sites.append(work_site.id)
            employee.assigned_sites = json.dumps(assigned_sites)
        
        # 신청 상태 업데이트
        application.status = "working"
        application.work_start_date = datetime.now()
        
        db.commit()
        
        return {
            "success": True,
            "message": f"근무지가 '{work_site.name}'로 설정되었습니다.",
            "work_site": {
                "id": work_site.id,
                "name": work_site.name,
                "address": work_site.address,
                "latitude": work_site.latitude,
                "longitude": work_site.longitude
            }
        }
    
    @staticmethod
    def complete_work(application_id: int, db: Session) -> Dict:
        """근무 완료 처리"""
        
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id,
            JobApplication.status == "working"
        ).first()
        
        if not application:
            return {
                "success": False,
                "error": "진행 중인 근무를 찾을 수 없습니다."
            }
        
        # 근무 완료 처리
        application.status = "completed"
        application.work_end_date = datetime.now()
        application.work_completed = True
        
        db.commit()
        
        return {
            "success": True,
            "message": "근무가 완료되었습니다. 보증금 환불이 진행됩니다."
        }
    
    @staticmethod
    def get_user_applications(user_id: int, db: Session) -> Dict:
        """사용자의 신청 목록 조회"""
        
        applications = db.query(JobApplication).filter(
            JobApplication.user_id == user_id
        ).order_by(JobApplication.applied_at.desc()).all()
        
        application_list = []
        for app in applications:
            job_post = app.job_post
            application_list.append({
                "id": app.id,
                "job_post": {
                    "id": job_post.id,
                    "title": job_post.title,
                    "company_name": job_post.company_name,
                    "work_address": job_post.work_address
                },
                "status": app.status,
                "applied_at": app.applied_at,
                "deposit_paid": app.deposit_paid,
                "deposit_refunded": app.deposit_refunded,
                "work_start_date": app.work_start_date,
                "work_end_date": app.work_end_date
            })
        
        return {
            "success": True,
            "applications": application_list
        }
    
    @staticmethod
    def _get_job_status(job: JobPost, approved_count: int) -> str:
        """공고 상태 결정"""
        current_time = datetime.now()
        
        # 수동으로 마감된 경우
        if job.manually_closed:
            return "closed"
        
        # 마감일이 지난 경우
        if job.deadline and job.deadline < current_time:
            return "expired"
        
        # 인원이 가득 찬 경우
        if job.max_applicants and approved_count >= job.max_applicants:
            return "full"
        
        # 활성 상태
        return "active"
    
    @staticmethod
    def get_job_applications(job_id: int, db: Session) -> Dict:
        """공고의 신청자 목록 조회"""
        job_post = db.query(JobPost).filter(JobPost.id == job_id).first()
        if not job_post:
            return {
                "success": False,
                "error": "공고를 찾을 수 없습니다."
            }
        
        applications = db.query(JobApplication).filter(
            JobApplication.job_post_id == job_id
        ).order_by(JobApplication.applied_at.desc()).all()
        
        application_list = []
        for app in applications:
            user = app.user
            reviewer = None
            if app.reviewed_by:
                reviewer = db.query(User).filter(User.id == app.reviewed_by).first()
            
            application_list.append({
                "id": app.id,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "email": user.email
                },
                "status": app.status,
                "applied_at": app.applied_at,
                "reviewed_at": app.reviewed_at,
                "reviewer": reviewer.full_name if reviewer else None,
                "rejection_reason": app.rejection_reason,
                "deposit_paid": app.deposit_paid,
                "work_start_date": app.work_start_date,
                "work_end_date": app.work_end_date,
                "work_completed": app.work_completed
            })
        
        approved_count = len([app for app in applications if app.status in ["approved", "working", "completed"]])
        job_status = JobBoardService._get_job_status(job_post, approved_count)
        
        return {
            "success": True,
            "job_post": {
                "id": job_post.id,
                "title": job_post.title,
                "company_name": job_post.company_name,
                "max_applicants": job_post.max_applicants,
                "auto_approval": job_post.auto_approval,
                "status": job_status,
                "approved_count": approved_count
            },
            "applications": application_list
        }
    
    @staticmethod
    def review_application(application_id: int, action: str, reviewer_id: int, reason: str = None, db: Session = None) -> Dict:
        """신청 승인/거절 처리"""
        application = db.query(JobApplication).filter(
            JobApplication.id == application_id
        ).first()
        
        if not application:
            return {
                "success": False,
                "error": "신청을 찾을 수 없습니다."
            }
        
        if application.status != "pending":
            return {
                "success": False,
                "error": "이미 처리된 신청입니다."
            }
        
        try:
            if action == "approve":
                # 인원 제한 확인
                job_post = application.job_post
                if job_post.max_applicants:
                    approved_count = db.query(JobApplication).filter(
                        JobApplication.job_post_id == job_post.id,
                        JobApplication.status.in_(["approved", "working", "completed"])
                    ).count()
                    
                    if approved_count >= job_post.max_applicants:
                        return {
                            "success": False,
                            "error": "이미 모집인원이 가득 찬 공고입니다."
                        }
                
                application.status = "approved"
                application.reviewed_at = datetime.now()
                application.reviewed_by = reviewer_id
                
            elif action == "reject":
                application.status = "rejected"
                application.reviewed_at = datetime.now()
                application.reviewed_by = reviewer_id
                application.rejection_reason = reason
                
            else:
                return {
                    "success": False,
                    "error": "잘못된 액션입니다."
                }
            
            db.commit()
            
            return {
                "success": True,
                "message": f"신청이 {'승인' if action == 'approve' else '거절'}되었습니다."
            }
            
        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "error": f"처리 중 오류가 발생했습니다: {str(e)}"
            }
    
    @staticmethod
    def toggle_job_status(job_id: int, db: Session) -> Dict:
        """공고 상태 토글 (인원마감/재개방)"""
        job_post = db.query(JobPost).filter(JobPost.id == job_id).first()
        if not job_post:
            return {
                "success": False,
                "error": "공고를 찾을 수 없습니다."
            }
        
        try:
            job_post.manually_closed = not job_post.manually_closed
            job_post.updated_at = datetime.now()
            db.commit()
            
            status_text = "인원마감" if job_post.manually_closed else "재개방"
            
            return {
                "success": True,
                "message": f"공고가 {status_text}되었습니다.",
                "manually_closed": job_post.manually_closed
            }
            
        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "error": f"상태 변경 중 오류가 발생했습니다: {str(e)}"
            }
    
    @staticmethod
    def _calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """두 지점 간의 거리 계산 (Haversine 공식)"""
        
        from math import radians, cos, sin, asin, sqrt
        
        # 지구 반지름 (km)
        R = 6371
        
        # 위경도를 라디안으로 변환
        lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
        
        # Haversine 공식
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        c = 2 * asin(sqrt(a))
        
        return R * c  # km 단위 거리
