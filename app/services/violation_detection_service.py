"""
위반 사항 자동 감지 및 출근 기록 검증 서비스

실시간으로 출근 기록을 모니터링하고 위반 사항을 자동으로 감지합니다.
- 지각 감지
- 조기 퇴근 감지
- 위치 조작 감지
- 비정상적인 근무 패턴 감지
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
import json

from ..models.database import (
    User, Employee, AttendanceRecord, LocationEvent, 
    Department, Site, Violation, Company
)


class ViolationDetectionService:
    """위반 사항 자동 감지 서비스"""
    
    # 기본 근무 시간 설정 (회사별로 다를 수 있음)
    DEFAULT_WORK_START_TIME = time(9, 0)  # 09:00
    DEFAULT_WORK_END_TIME = time(18, 0)   # 18:00
    LATE_THRESHOLD_MINUTES = 10  # 10분 이상 지각시 위반
    EARLY_LEAVE_THRESHOLD_MINUTES = 30  # 30분 이상 조기퇴근시 위반
    
    @staticmethod
    def detect_attendance_violations(db: Session, start_time: datetime = None) -> Dict:
        """출근 기록 기반 위반 사항 감지"""
        
        if not start_time:
            start_time = datetime.now() - timedelta(hours=24)
        
        # 최근 출근 기록 조회
        recent_records = db.query(AttendanceRecord).filter(
            AttendanceRecord.check_in_time >= start_time
        ).all()
        
        detected_violations = []
        
        for record in recent_records:
            violations = ViolationDetectionService._analyze_attendance_record(record, db)
            detected_violations.extend(violations)
        
        # 데이터베이스에 저장
        for violation_data in detected_violations:
            # 중복 확인
            existing = db.query(Violation).filter(
                Violation.employee_id == violation_data['employee_id'],
                Violation.attendance_record_id == violation_data.get('attendance_record_id'),
                Violation.violation_type == violation_data['violation_type'],
                Violation.occurred_at >= violation_data['occurred_at'] - timedelta(minutes=5),
                Violation.occurred_at <= violation_data['occurred_at'] + timedelta(minutes=5)
            ).first()
            
            if not existing:
                violation = Violation(**violation_data)
                db.add(violation)
        
        db.commit()
        
        return {
            "detected_count": len(detected_violations),
            "violations": detected_violations
        }
    
    @staticmethod
    def _analyze_attendance_record(record: AttendanceRecord, db: Session) -> List[Dict]:
        """개별 출근 기록 분석"""
        violations = []
        
        # 근무지 정보 조회
        site = db.query(Site).filter(Site.id == record.site_id).first()
        if not site:
            return violations
        
        # 예정된 근무 시간 vs 실제 근무 시간 비교
        scheduled_start = ViolationDetectionService._get_scheduled_start_time(site)
        scheduled_end = ViolationDetectionService._get_scheduled_end_time(site)
        
        # 지각 검사
        if record.check_in_time and scheduled_start:
            actual_start = record.check_in_time.time()
            
            # 지각 시간 계산
            if actual_start > scheduled_start:
                late_minutes = ViolationDetectionService._calculate_time_difference_minutes(
                    scheduled_start, actual_start
                )
                
                if late_minutes >= ViolationDetectionService.LATE_THRESHOLD_MINUTES:
                    # 이미 is_late 플래그가 설정되지 않았다면 설정
                    if not record.is_late:
                        record.is_late = True
                        db.commit()
                    
                    severity = ViolationDetectionService._determine_late_severity(late_minutes)
                    
                    violations.append({
                        'employee_id': record.employee_id,
                        'attendance_record_id': record.id,
                        'violation_type': 'late_arrival',
                        'severity': severity,
                        'occurred_at': record.check_in_time,
                        'description': f"지각: {late_minutes}분 늦음 (예정: {scheduled_start.strftime('%H:%M')}, 실제: {actual_start.strftime('%H:%M')})",
                        'auto_detected': True,
                        'evidence_data': json.dumps({
                            'scheduled_time': scheduled_start.strftime('%H:%M'),
                            'actual_time': actual_start.strftime('%H:%M'),
                            'late_minutes': late_minutes
                        })
                    })
        
        # 조기 퇴근 검사
        if record.check_out_time and scheduled_end:
            actual_end = record.check_out_time.time()
            
            # 조기 퇴근 시간 계산
            if actual_end < scheduled_end:
                early_minutes = ViolationDetectionService._calculate_time_difference_minutes(
                    actual_end, scheduled_end
                )
                
                if early_minutes >= ViolationDetectionService.EARLY_LEAVE_THRESHOLD_MINUTES:
                    # 이미 is_early_leave 플래그가 설정되지 않았다면 설정
                    if not record.is_early_leave:
                        record.is_early_leave = True
                        db.commit()
                    
                    severity = ViolationDetectionService._determine_early_leave_severity(early_minutes)
                    
                    violations.append({
                        'employee_id': record.employee_id,
                        'attendance_record_id': record.id,
                        'violation_type': 'early_departure',
                        'severity': severity,
                        'occurred_at': record.check_out_time,
                        'description': f"조기퇴근: {early_minutes}분 일찍 퇴근 (예정: {scheduled_end.strftime('%H:%M')}, 실제: {actual_end.strftime('%H:%M')})",
                        'auto_detected': True,
                        'evidence_data': json.dumps({
                            'scheduled_time': scheduled_end.strftime('%H:%M'),
                            'actual_time': actual_end.strftime('%H:%M'),
                            'early_minutes': early_minutes
                        })
                    })
        
        # 비정상적으로 짧은 근무시간 검사
        if record.check_in_time and record.check_out_time:
            work_duration = record.check_out_time - record.check_in_time
            work_hours = work_duration.total_seconds() / 3600
            
            # 4시간 미만 근무시 의심
            if work_hours < 4:
                violations.append({
                    'employee_id': record.employee_id,
                    'attendance_record_id': record.id,
                    'violation_type': 'insufficient_work_hours',
                    'severity': 'medium',
                    'occurred_at': record.check_out_time,
                    'description': f"비정상적으로 짧은 근무시간: {work_hours:.1f}시간",
                    'auto_detected': True,
                    'evidence_data': json.dumps({
                        'work_hours': work_hours,
                        'check_in': record.check_in_time.strftime('%H:%M'),
                        'check_out': record.check_out_time.strftime('%H:%M')
                    })
                })
        
        return violations
    
    @staticmethod
    def detect_location_violations(db: Session, start_time: datetime = None) -> Dict:
        """위치 기반 위반 사항 감지"""
        
        if not start_time:
            start_time = datetime.now() - timedelta(hours=24)
        
        # 최근 위치 이벤트 조회
        recent_events = db.query(LocationEvent).filter(
            LocationEvent.timestamp >= start_time
        ).all()
        
        detected_violations = []
        
        for event in recent_events:
            violations = ViolationDetectionService._analyze_location_event(event, db)
            detected_violations.extend(violations)
        
        # 데이터베이스에 저장
        for violation_data in detected_violations:
            # 중복 확인
            existing = db.query(Violation).filter(
                Violation.employee_id == violation_data['employee_id'],
                Violation.violation_type == violation_data['violation_type'],
                Violation.occurred_at >= violation_data['occurred_at'] - timedelta(minutes=5),
                Violation.occurred_at <= violation_data['occurred_at'] + timedelta(minutes=5)
            ).first()
            
            if not existing:
                violation = Violation(**violation_data)
                db.add(violation)
        
        db.commit()
        
        return {
            "detected_count": len(detected_violations),
            "violations": detected_violations
        }
    
    @staticmethod
    def _analyze_location_event(event: LocationEvent, db: Session) -> List[Dict]:
        """개별 위치 이벤트 분석"""
        violations = []
        
        # GPS 정확도 검사
        if event.accuracy and event.accuracy > 1000:  # 1km 이상의 오차
            violations.append({
                'employee_id': event.employee_id,
                'violation_type': 'location_spoofing',
                'severity': 'high',
                'occurred_at': event.timestamp,
                'description': f"GPS 정확도 비정상: {event.accuracy:.0f}m 오차",
                'auto_detected': True,
                'evidence_data': json.dumps({
                    'accuracy': event.accuracy,
                    'latitude': event.latitude,
                    'longitude': event.longitude,
                    'event_type': event.event_type
                })
            })
        
        # 목 위치 감지 (의심스러운 위치)
        if hasattr(event, 'is_mock_location') and event.is_mock_location:
            violations.append({
                'employee_id': event.employee_id,
                'violation_type': 'mock_location_detected',
                'severity': 'critical',
                'occurred_at': event.timestamp,
                'description': "목 위치 앱 사용 감지",
                'auto_detected': True,
                'evidence_data': json.dumps({
                    'latitude': event.latitude,
                    'longitude': event.longitude,
                    'device_info': event.device_info
                })
            })
        
        # 비정상적인 이동 속도 감지
        if event.speed and event.speed > 200:  # 200km/h 이상
            violations.append({
                'employee_id': event.employee_id,
                'violation_type': 'abnormal_speed',
                'severity': 'medium',
                'occurred_at': event.timestamp,
                'description': f"비정상적인 이동 속도: {event.speed:.0f}km/h",
                'auto_detected': True,
                'evidence_data': json.dumps({
                    'speed': event.speed,
                    'latitude': event.latitude,
                    'longitude': event.longitude
                })
            })
        
        return violations
    
    @staticmethod
    def detect_pattern_violations(db: Session, start_date: datetime = None) -> Dict:
        """근무 패턴 기반 위반 사항 감지"""
        
        if not start_date:
            start_date = datetime.now() - timedelta(days=7)  # 최근 7일
        
        detected_violations = []
        
        # 모든 직원에 대해 분석
        employees = db.query(Employee).all()
        
        for employee in employees:
            # 해당 기간 내 출근 기록
            records = db.query(AttendanceRecord).filter(
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.check_in_time >= start_date
            ).all()
            
            if len(records) < 3:  # 분석하기에 충분한 데이터가 없음
                continue
            
            violations = ViolationDetectionService._analyze_work_patterns(employee, records, db)
            detected_violations.extend(violations)
        
        # 데이터베이스에 저장
        for violation_data in detected_violations:
            existing = db.query(Violation).filter(
                Violation.employee_id == violation_data['employee_id'],
                Violation.violation_type == violation_data['violation_type'],
                Violation.occurred_at >= violation_data['occurred_at'] - timedelta(hours=1)
            ).first()
            
            if not existing:
                violation = Violation(**violation_data)
                db.add(violation)
        
        db.commit()
        
        return {
            "detected_count": len(detected_violations),
            "violations": detected_violations
        }
    
    @staticmethod
    def _analyze_work_patterns(employee: Employee, records: List[AttendanceRecord], db: Session) -> List[Dict]:
        """개별 직원의 근무 패턴 분석"""
        violations = []
        
        # 지각 빈도 분석
        late_count = len([r for r in records if r.is_late])
        late_rate = late_count / len(records) if records else 0
        
        if late_rate > 0.5:  # 50% 이상 지각
            violations.append({
                'employee_id': employee.id,
                'violation_type': 'frequent_lateness',
                'severity': 'medium',
                'occurred_at': datetime.now(),
                'description': f"빈번한 지각: 최근 {len(records)}일 중 {late_count}일 지각 ({late_rate:.1%})",
                'auto_detected': True,
                'evidence_data': json.dumps({
                    'total_days': len(records),
                    'late_days': late_count,
                    'late_rate': late_rate
                })
            })
        
        # 비정상적인 근무시간 패턴
        work_hours = []
        for record in records:
            if record.total_work_minutes:
                work_hours.append(record.total_work_minutes / 60)
        
        if work_hours:
            avg_hours = sum(work_hours) / len(work_hours)
            
            # 평균 3시간 미만 근무
            if avg_hours < 3:
                violations.append({
                    'employee_id': employee.id,
                    'violation_type': 'insufficient_average_hours',
                    'severity': 'medium',
                    'occurred_at': datetime.now(),
                    'description': f"비정상적으로 짧은 평균 근무시간: {avg_hours:.1f}시간",
                    'auto_detected': True,
                    'evidence_data': json.dumps({
                        'average_hours': avg_hours,
                        'work_days': len(work_hours)
                    })
                })
        
        return violations
    
    @staticmethod
    def _get_scheduled_start_time(site: Site) -> time:
        """근무지의 예정 시작 시간 반환"""
        if site.operating_hours_start:
            try:
                hour, minute = map(int, site.operating_hours_start.split(':'))
                return time(hour, minute)
            except:
                pass
        return ViolationDetectionService.DEFAULT_WORK_START_TIME
    
    @staticmethod
    def _get_scheduled_end_time(site: Site) -> time:
        """근무지의 예정 종료 시간 반환"""
        if site.operating_hours_end:
            try:
                hour, minute = map(int, site.operating_hours_end.split(':'))
                return time(hour, minute)
            except:
                pass
        return ViolationDetectionService.DEFAULT_WORK_END_TIME
    
    @staticmethod
    def _calculate_time_difference_minutes(time1: time, time2: time) -> int:
        """두 시간 간의 차이를 분 단위로 반환"""
        datetime1 = datetime.combine(datetime.today(), time1)
        datetime2 = datetime.combine(datetime.today(), time2)
        
        if datetime2 < datetime1:
            datetime2 += timedelta(days=1)
        
        return int((datetime2 - datetime1).total_seconds() / 60)
    
    @staticmethod
    def _determine_late_severity(late_minutes: int) -> str:
        """지각 시간에 따른 심각도 결정"""
        if late_minutes >= 60:  # 1시간 이상
            return 'high'
        elif late_minutes >= 30:  # 30분 이상
            return 'medium'
        else:
            return 'low'
    
    @staticmethod
    def _determine_early_leave_severity(early_minutes: int) -> str:
        """조기 퇴근 시간에 따른 심각도 결정"""
        if early_minutes >= 120:  # 2시간 이상
            return 'high'
        elif early_minutes >= 60:  # 1시간 이상
            return 'medium'
        else:
            return 'low'
    
    @staticmethod
    def run_comprehensive_detection(db: Session) -> Dict:
        """종합적인 위반 사항 감지 실행"""
        start_time = datetime.now()
        
        # 출근 기록 기반 감지
        attendance_result = ViolationDetectionService.detect_attendance_violations(db)
        
        # 위치 기반 감지
        location_result = ViolationDetectionService.detect_location_violations(db)
        
        # 패턴 기반 감지 (주간 단위)
        pattern_result = ViolationDetectionService.detect_pattern_violations(db)
        
        total_detected = (
            attendance_result["detected_count"] + 
            location_result["detected_count"] + 
            pattern_result["detected_count"]
        )
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        return {
            "success": True,
            "total_detected": total_detected,
            "attendance_violations": attendance_result["detected_count"],
            "location_violations": location_result["detected_count"],
            "pattern_violations": pattern_result["detected_count"],
            "processing_time_seconds": processing_time,
            "detection_timestamp": start_time
        }
