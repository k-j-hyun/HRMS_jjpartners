"""
리포트 생성 서비스

관리자 대시보드에서 사용할 리포트 생성 기능을 제공합니다.
- 일간/주간/월간 출근 리포트
- 직원별 근무 현황 리포트  
- 위반 사항 리포트
- 부서별 통계 리포트
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import json
from io import BytesIO
import csv
import io

from ..models.database import (
    User, Employee, AttendanceRecord, LocationEvent, 
    Department, Site, Violation, Company
)


class ReportService:
    """리포트 생성 서비스 클래스"""
    
    @staticmethod
    def generate_daily_report(target_date: date, db: Session) -> Dict:
        """일간 출근 리포트 생성"""
        start_datetime = datetime.combine(target_date, datetime.min.time())
        end_datetime = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        
        # 기본 통계
        total_employees = db.query(Employee).count()
        
        # 당일 출근 기록
        daily_attendance = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.check_in_time >= start_datetime,
                AttendanceRecord.check_in_time < end_datetime
            )
        ).all()
        
        present_count = len(daily_attendance)
        late_count = len([r for r in daily_attendance if r.is_late])
        early_leave_count = len([r for r in daily_attendance if r.is_early_leave])
        absent_count = total_employees - present_count
        
        # 부서별 통계
        dept_stats = {}
        for record in daily_attendance:
            employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
            dept_name = employee.department.name if employee.department else "부서 없음"
            
            if dept_name not in dept_stats:
                dept_stats[dept_name] = {
                    "present": 0,
                    "late": 0,
                    "early_leave": 0,
                    "total_work_hours": 0
                }
            
            dept_stats[dept_name]["present"] += 1
            if record.is_late:
                dept_stats[dept_name]["late"] += 1
            if record.is_early_leave:
                dept_stats[dept_name]["early_leave"] += 1
            if record.total_work_minutes:
                dept_stats[dept_name]["total_work_hours"] += record.total_work_minutes / 60
        
        # 상세 출근 기록
        detailed_records = []
        for record in daily_attendance:
            employee = db.query(Employee).filter(Employee.id == record.employee_id).first()
            user = db.query(User).filter(User.id == employee.user_id).first()
            site = db.query(Site).filter(Site.id == record.site_id).first()
            
            detailed_records.append({
                "employee_number": employee.employee_number,
                "employee_name": user.full_name,
                "department": employee.department.name if employee.department else "부서 없음",
                "position": employee.position or "-",
                "check_in_time": record.check_in_time.strftime("%H:%M:%S") if record.check_in_time else "-",
                "check_out_time": record.check_out_time.strftime("%H:%M:%S") if record.check_out_time else "-",
                "total_work_hours": f"{record.total_work_minutes // 60}:{record.total_work_minutes % 60:02d}" if record.total_work_minutes else "-",
                "site_name": site.name if site else "-",
                "status": "지각" if record.is_late else "조기퇴근" if record.is_early_leave else "정상",
                "is_late": record.is_late,
                "is_early_leave": record.is_early_leave
            })
        
        return {
            "report_type": "daily",
            "target_date": target_date.strftime("%Y-%m-%d"),
            "generated_at": datetime.now(),
            "summary": {
                "total_employees": total_employees,
                "present_count": present_count,
                "absent_count": absent_count,
                "late_count": late_count,
                "early_leave_count": early_leave_count,
                "attendance_rate": round((present_count / total_employees) * 100, 1) if total_employees > 0 else 0
            },
            "department_stats": dept_stats,
            "detailed_records": detailed_records
        }
    
    @staticmethod
    def generate_weekly_report(start_date: date, db: Session) -> Dict:
        """주간 출근 리포트 생성"""
        end_date = start_date + timedelta(days=7)
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.min.time())
        
        # 주간 출근 기록
        weekly_attendance = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.check_in_time >= start_datetime,
                AttendanceRecord.check_in_time < end_datetime
            )
        ).all()
        
        # 일별 통계 계산
        daily_stats = {}
        for i in range(7):
            current_date = start_date + timedelta(days=i)
            day_start = datetime.combine(current_date, datetime.min.time())
            day_end = datetime.combine(current_date + timedelta(days=1), datetime.min.time())
            
            day_records = [r for r in weekly_attendance 
                          if day_start <= r.check_in_time < day_end]
            
            daily_stats[current_date.strftime("%Y-%m-%d")] = {
                "date": current_date.strftime("%m/%d (%a)"),
                "present": len(day_records),
                "late": len([r for r in day_records if r.is_late]),
                "total_work_hours": sum([r.total_work_minutes or 0 for r in day_records]) / 60
            }
        
        # 직원별 주간 통계
        employee_stats = {}
        for record in weekly_attendance:
            emp_id = record.employee_id
            if emp_id not in employee_stats:
                employee = db.query(Employee).filter(Employee.id == emp_id).first()
                user = db.query(User).filter(User.id == employee.user_id).first()
                
                employee_stats[emp_id] = {
                    "employee_name": user.full_name,
                    "department": employee.department.name if employee.department else "부서 없음",
                    "work_days": 0,
                    "late_count": 0,
                    "total_hours": 0,
                    "avg_hours": 0
                }
            
            employee_stats[emp_id]["work_days"] += 1
            if record.is_late:
                employee_stats[emp_id]["late_count"] += 1
            if record.total_work_minutes:
                employee_stats[emp_id]["total_hours"] += record.total_work_minutes / 60
        
        # 평균 근무시간 계산
        for emp_id in employee_stats:
            stats = employee_stats[emp_id]
            if stats["work_days"] > 0:
                stats["avg_hours"] = round(stats["total_hours"] / stats["work_days"], 1)
                stats["total_hours"] = round(stats["total_hours"], 1)
        
        return {
            "report_type": "weekly",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": (end_date - timedelta(days=1)).strftime("%Y-%m-%d"),
            "generated_at": datetime.now(),
            "daily_stats": daily_stats,
            "employee_stats": list(employee_stats.values()),
            "summary": {
                "total_work_days": sum([stats["present"] for stats in daily_stats.values()]),
                "total_late_count": sum([stats["late"] for stats in daily_stats.values()]),
                "total_work_hours": round(sum([stats["total_work_hours"] for stats in daily_stats.values()]), 1)
            }
        }
    
    @staticmethod
    def generate_monthly_report(year: int, month: int, db: Session) -> Dict:
        """월간 출근 리포트 생성"""
        # 해당 월의 첫날과 마지막날 계산
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date, datetime.min.time())
        
        # 월간 출근 기록
        monthly_attendance = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.check_in_time >= start_datetime,
                AttendanceRecord.check_in_time < end_datetime
            )
        ).all()
        
        # 직원별 월간 통계
        employee_monthly_stats = {}
        total_employees = db.query(Employee).count()
        
        for record in monthly_attendance:
            emp_id = record.employee_id
            if emp_id not in employee_monthly_stats:
                employee = db.query(Employee).filter(Employee.id == emp_id).first()
                user = db.query(User).filter(User.id == employee.user_id).first()
                
                employee_monthly_stats[emp_id] = {
                    "employee_number": employee.employee_number,
                    "employee_name": user.full_name,
                    "department": employee.department.name if employee.department else "부서 없음",
                    "work_days": 0,
                    "late_count": 0,
                    "early_leave_count": 0,
                    "total_hours": 0,
                    "avg_hours": 0,
                    "attendance_rate": 0
                }
            
            stats = employee_monthly_stats[emp_id]
            stats["work_days"] += 1
            if record.is_late:
                stats["late_count"] += 1
            if record.is_early_leave:
                stats["early_leave_count"] += 1
            if record.total_work_minutes:
                stats["total_hours"] += record.total_work_minutes / 60
        
        # 근무일수로 출근율 및 평균 계산
        working_days = len(set([r.check_in_time.date() for r in monthly_attendance]))
        
        for emp_id in employee_monthly_stats:
            stats = employee_monthly_stats[emp_id]
            if working_days > 0:
                stats["attendance_rate"] = round((stats["work_days"] / working_days) * 100, 1)
            if stats["work_days"] > 0:
                stats["avg_hours"] = round(stats["total_hours"] / stats["work_days"], 1)
            stats["total_hours"] = round(stats["total_hours"], 1)
        
        # 부서별 통계
        dept_monthly_stats = {}
        for emp_stats in employee_monthly_stats.values():
            dept = emp_stats["department"]
            if dept not in dept_monthly_stats:
                dept_monthly_stats[dept] = {
                    "department": dept,
                    "employee_count": 0,
                    "total_work_days": 0,
                    "total_late_count": 0,
                    "total_hours": 0,
                    "avg_attendance_rate": 0
                }
            
            dept_stats = dept_monthly_stats[dept]
            dept_stats["employee_count"] += 1
            dept_stats["total_work_days"] += emp_stats["work_days"]
            dept_stats["total_late_count"] += emp_stats["late_count"]
            dept_stats["total_hours"] += emp_stats["total_hours"]
        
        # 부서별 평균 계산
        for dept_stats in dept_monthly_stats.values():
            if dept_stats["employee_count"] > 0:
                dept_stats["avg_attendance_rate"] = round(
                    (dept_stats["total_work_days"] / (dept_stats["employee_count"] * working_days)) * 100, 1
                ) if working_days > 0 else 0
                dept_stats["total_hours"] = round(dept_stats["total_hours"], 1)
        
        return {
            "report_type": "monthly",
            "year": year,
            "month": month,
            "month_name": f"{year}년 {month}월",
            "generated_at": datetime.now(),
            "working_days": working_days,
            "employee_stats": list(employee_monthly_stats.values()),
            "department_stats": list(dept_monthly_stats.values()),
            "summary": {
                "total_employees": total_employees,
                "total_work_records": len(monthly_attendance),
                "total_late_records": len([r for r in monthly_attendance if r.is_late]),
                "total_work_hours": round(sum([r.total_work_minutes or 0 for r in monthly_attendance]) / 60, 1),
                "avg_attendance_rate": round((len(monthly_attendance) / (total_employees * working_days)) * 100, 1) if working_days > 0 and total_employees > 0 else 0
            }
        }
    
    @staticmethod
    def generate_violation_report(start_date: date, end_date: date, db: Session) -> Dict:
        """위반 사항 리포트 생성"""
        start_datetime = datetime.combine(start_date, datetime.min.time())
        end_datetime = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        
        # 기간 내 위반 사항 조회
        violations = db.query(Violation).filter(
            and_(
                Violation.occurred_at >= start_datetime,
                Violation.occurred_at < end_datetime
            )
        ).all()
        
        # 위반 유형별 통계
        violation_types = {}
        severity_stats = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        status_stats = {"pending": 0, "acknowledged": 0, "resolved": 0, "dismissed": 0}
        
        detailed_violations = []
        
        for violation in violations:
            # 위반 유형별 카운트
            v_type = violation.violation_type
            if v_type not in violation_types:
                violation_types[v_type] = 0
            violation_types[v_type] += 1
            
            # 심각도별 카운트
            if violation.severity in severity_stats:
                severity_stats[violation.severity] += 1
            
            # 상태별 카운트
            if violation.status in status_stats:
                status_stats[violation.status] += 1
            
            # 상세 정보
            employee = db.query(Employee).filter(Employee.id == violation.employee_id).first()
            user = db.query(User).filter(User.id == employee.user_id).first()
            
            detailed_violations.append({
                "id": violation.id,
                "employee_name": user.full_name,
                "employee_number": employee.employee_number,
                "department": employee.department.name if employee.department else "부서 없음",
                "violation_type": violation.violation_type,
                "violation_type_text": ReportService._get_violation_type_text(violation.violation_type),
                "severity": violation.severity,
                "severity_text": ReportService._get_severity_text(violation.severity),
                "occurred_at": violation.occurred_at,
                "description": violation.description,
                "status": violation.status,
                "status_text": ReportService._get_status_text(violation.status),
                "auto_detected": violation.auto_detected
            })
        
        # 직원별 위반 통계
        employee_violation_stats = {}
        for violation in violations:
            emp_id = violation.employee_id
            if emp_id not in employee_violation_stats:
                employee = db.query(Employee).filter(Employee.id == emp_id).first()
                user = db.query(User).filter(User.id == employee.user_id).first()
                
                employee_violation_stats[emp_id] = {
                    "employee_name": user.full_name,
                    "department": employee.department.name if employee.department else "부서 없음",
                    "total_violations": 0,
                    "high_severity_count": 0,
                    "resolved_count": 0
                }
            
            stats = employee_violation_stats[emp_id]
            stats["total_violations"] += 1
            if violation.severity in ["high", "critical"]:
                stats["high_severity_count"] += 1
            if violation.status == "resolved":
                stats["resolved_count"] += 1
        
        return {
            "report_type": "violations",
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "generated_at": datetime.now(),
            "summary": {
                "total_violations": len(violations),
                "pending_violations": status_stats["pending"],
                "resolved_violations": status_stats["resolved"],
                "high_severity_violations": severity_stats["high"] + severity_stats["critical"]
            },
            "violation_types": violation_types,
            "severity_stats": severity_stats,
            "status_stats": status_stats,
            "employee_violation_stats": list(employee_violation_stats.values()),
            "detailed_violations": detailed_violations
        }
    
    @staticmethod
    def export_report_to_csv(report_data: Dict) -> str:
        """리포트 데이터를 CSV 형태로 변환"""
        output = io.StringIO()
        
        if report_data["report_type"] == "daily":
            # 일간 리포트 CSV
            writer = csv.writer(output)
            writer.writerow(["일간 출근 리포트"])
            writer.writerow(["날짜", report_data["target_date"]])
            writer.writerow(["생성시간", report_data["generated_at"].strftime("%Y-%m-%d %H:%M")])
            writer.writerow([])
            
            # 요약 통계
            writer.writerow(["요약 통계"])
            writer.writerow(["총 직원수", report_data["summary"]["total_employees"]])
            writer.writerow(["출근자수", report_data["summary"]["present_count"]])
            writer.writerow(["결근자수", report_data["summary"]["absent_count"]])
            writer.writerow(["지각자수", report_data["summary"]["late_count"]])
            writer.writerow(["출근율", f"{report_data['summary']['attendance_rate']}%"])
            writer.writerow([])
            
            # 상세 기록
            writer.writerow(["상세 출근 기록"])
            writer.writerow(["직원번호", "이름", "부서", "직급", "출근시간", "퇴근시간", "근무시간", "근무지", "상태"])
            
            for record in report_data["detailed_records"]:
                writer.writerow([
                    record["employee_number"],
                    record["employee_name"],
                    record["department"],
                    record["position"],
                    record["check_in_time"],
                    record["check_out_time"],
                    record["total_work_hours"],
                    record["site_name"],
                    record["status"]
                ])
        
        elif report_data["report_type"] == "monthly":
            # 월간 리포트 CSV
            writer = csv.writer(output)
            writer.writerow([f"월간 출근 리포트 - {report_data['month_name']}"])
            writer.writerow(["생성시간", report_data["generated_at"].strftime("%Y-%m-%d %H:%M")])
            writer.writerow([])
            
            # 요약 통계
            writer.writerow(["요약 통계"])
            writer.writerow(["총 직원수", report_data["summary"]["total_employees"]])
            writer.writerow(["총 출근 기록", report_data["summary"]["total_work_records"]])
            writer.writerow(["총 지각 기록", report_data["summary"]["total_late_records"]])
            writer.writerow(["총 근무시간", f"{report_data['summary']['total_work_hours']}시간"])
            writer.writerow(["평균 출근율", f"{report_data['summary']['avg_attendance_rate']}%"])
            writer.writerow([])
            
            # 직원별 통계
            writer.writerow(["직원별 월간 통계"])
            writer.writerow(["직원번호", "이름", "부서", "근무일수", "지각횟수", "조기퇴근횟수", "총 근무시간", "평균 근무시간", "출근율"])
            
            for emp_stats in report_data["employee_stats"]:
                writer.writerow([
                    emp_stats["employee_number"],
                    emp_stats["employee_name"],
                    emp_stats["department"],
                    emp_stats["work_days"],
                    emp_stats["late_count"],
                    emp_stats["early_leave_count"],
                    f"{emp_stats['total_hours']}시간",
                    f"{emp_stats['avg_hours']}시간",
                    f"{emp_stats['attendance_rate']}%"
                ])
        
        elif report_data["report_type"] == "violations":
            # 위반사항 리포트 CSV
            writer = csv.writer(output)
            writer.writerow([f"위반사항 리포트 ({report_data['start_date']} ~ {report_data['end_date']})"])
            writer.writerow(["생성시간", report_data["generated_at"].strftime("%Y-%m-%d %H:%M")])
            writer.writerow([])
            
            # 요약 통계
            writer.writerow(["요약 통계"])
            writer.writerow(["총 위반건수", report_data["summary"]["total_violations"]])
            writer.writerow(["대기중 위반", report_data["summary"]["pending_violations"]])
            writer.writerow(["해결된 위반", report_data["summary"]["resolved_violations"]])
            writer.writerow(["고심각도 위반", report_data["summary"]["high_severity_violations"]])
            writer.writerow([])
            
            # 위반 상세 기록
            writer.writerow(["위반사항 상세 기록"])
            writer.writerow(["직원명", "직원번호", "부서", "위반유형", "심각도", "발생시간", "설명", "상태", "자동감지"])
            
            for violation in report_data["detailed_violations"]:
                writer.writerow([
                    violation["employee_name"],
                    violation["employee_number"],
                    violation["department"],
                    violation["violation_type_text"],
                    violation["severity_text"],
                    violation["occurred_at"].strftime("%Y-%m-%d %H:%M"),
                    violation["description"],
                    violation["status_text"],
                    "예" if violation["auto_detected"] else "아니오"
                ])
        
        csv_content = output.getvalue()
        output.close()
        return csv_content
    
    @staticmethod
    def _get_violation_type_text(violation_type: str) -> str:
        """위반 유형 한글 변환"""
        types = {
            'late_arrival': '지각',
            'early_departure': '조기퇴근',
            'unauthorized_break': '무단휴식',
            'location_spoofing': '위치조작',
            'attendance_fraud': '출근조작',
            'geofence_violation': '지오펜스 위반',
            'excessive_break': '과도한 휴식'
        }
        return types.get(violation_type, violation_type)
    
    @staticmethod
    def _get_severity_text(severity: str) -> str:
        """심각도 한글 변환"""
        severities = {
            'low': '낮음',
            'medium': '보통',
            'high': '높음',
            'critical': '심각'
        }
        return severities.get(severity, severity)
    
    @staticmethod
    def _get_status_text(status: str) -> str:
        """상태 한글 변환"""
        statuses = {
            'pending': '대기중',
            'acknowledged': '확인됨',
            'resolved': '해결됨',
            'dismissed': '기각됨'
        }
        return statuses.get(status, status)
