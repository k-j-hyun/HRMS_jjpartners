import math
from typing import Tuple, Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.database import Employee, Site, LocationEvent, AttendanceRecord, Violation
import requests
import json

class LocationService:
    
    @staticmethod
    def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """두 좌표 간의 거리를 미터 단위로 계산 (Haversine 공식)"""
        R = 6371000  # 지구 반지름 (미터)
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lng = math.radians(lng2 - lng1)
        
        a = (math.sin(delta_lat/2) ** 2 + 
             math.cos(lat1_rad) * math.cos(lat2_rad) * 
             math.sin(delta_lng/2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    @staticmethod
    def validate_location_accuracy(accuracy: float) -> bool:
        """위치 정확도 검증 (100m 이내만 신뢰)"""
        return accuracy <= 100.0
    
    @staticmethod
    def detect_mock_location(location_data: dict, previous_location: dict = None) -> bool:
        """모의 위치 감지"""
        # 1. 정확도가 비현실적으로 좋음 (1m 이하)
        if location_data.get('accuracy', 0) < 1.0:
            return True
        
        # 2. 이전 위치와 비교하여 비현실적 이동
        if previous_location:
            time_diff = (datetime.now() - previous_location['timestamp']).total_seconds()
            if time_diff > 0:
                distance = LocationService.calculate_distance(
                    previous_location['latitude'], previous_location['longitude'],
                    location_data['latitude'], location_data['longitude']
                )
                # 시속 300km/h 이상의 이동은 의심
                max_possible_distance = (300 * 1000 / 3600) * time_diff  # m/s * 초
                if distance > max_possible_distance:
                    return True
        
        return False
    
    @staticmethod
    def check_geofence(lat: float, lng: float, employee_id: int, db: Session) -> Dict:
        """지오펜스 체크 및 사이트 확인"""
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {"inside": False, "site": None, "distance": None}
        
        # 직원에게 할당된 사이트들 조회
        assigned_sites = []
        if employee.assigned_sites:
            try:
                import json
                site_ids = json.loads(employee.assigned_sites)
                assigned_sites = db.query(Site).filter(Site.id.in_(site_ids)).all()
            except:
                pass
        
        # 할당된 사이트가 없으면 모든 사이트 조회
        if not assigned_sites:
            assigned_sites = db.query(Site).all()
        
        closest_site = None
        min_distance = float('inf')
        
        for site in assigned_sites:
            distance = LocationService.calculate_distance(lat, lng, site.latitude, site.longitude)
            
            if distance < min_distance:
                min_distance = distance
                closest_site = site
            
            # 지오펜스 내부에 있는지 확인
            if distance <= site.geofence_radius:
                return {
                    "inside": True,
                    "site": site,
                    "distance": distance,
                    "closest_site": closest_site,
                    "min_distance": min_distance
                }
        
        return {
            "inside": False,
            "site": None,
            "distance": None,
            "closest_site": closest_site,
            "min_distance": min_distance
        }
    
    @staticmethod
    def process_location_update(employee_id: int, location_data: dict, db: Session) -> Dict:
        """위치 업데이트 처리"""
        
        # 1. 이전 위치 조회
        last_location = db.query(LocationEvent).filter(
            LocationEvent.employee_id == employee_id
        ).order_by(LocationEvent.timestamp.desc()).first()
        
        # 2. 모의 위치 감지
        is_mock = LocationService.detect_mock_location(
            location_data, 
            {
                'latitude': last_location.latitude,
                'longitude': last_location.longitude,
                'timestamp': last_location.timestamp
            } if last_location else None
        )
        
        # 3. 위치 정확도 검증
        if not LocationService.validate_location_accuracy(location_data.get('accuracy', 999)):
            return {"status": "error", "message": "Location accuracy too low"}
        
        # 4. 지오펜스 체크
        geofence_result = LocationService.check_geofence(
            location_data['latitude'], 
            location_data['longitude'], 
            employee_id, 
            db
        )
        
        # 5. 이벤트 타입 결정
        event_type = "location_update"
        
        if geofence_result["inside"]:
            # 이전에 사이트 밖에 있었다면 ENTER
            if not last_location or last_location.site_id != geofence_result["site"].id:
                event_type = "geofence_enter"
        else:
            # 이전에 사이트 안에 있었다면 EXIT
            if last_location and last_location.site_id:
                event_type = "geofence_exit"
        
        # 6. 위치 이벤트 저장
        location_event = LocationEvent(
            employee_id=employee_id,
            site_id=geofence_result["site"].id if geofence_result["site"] else None,
            latitude=location_data['latitude'],
            longitude=location_data['longitude'],
            accuracy=location_data.get('accuracy'),
            altitude=location_data.get('altitude'),
            speed=location_data.get('speed'),
            event_type=event_type,
            is_mock_location=is_mock,
            device_info=location_data.get('device_info'),
            network_type=location_data.get('network_type', 'unknown')
        )
        
        db.add(location_event)
        db.commit()
        
        # 7. 출근/퇴근 처리
        attendance_result = LocationService.process_attendance_event(
            employee_id, event_type, geofence_result, db
        )
        
        return {
            "status": "success",
            "event_type": event_type,
            "site": geofence_result["site"].name if geofence_result["site"] else None,
            "distance": geofence_result.get("min_distance"),
            "is_mock": is_mock,
            "attendance": attendance_result
        }
    
    @staticmethod
    def process_attendance_event(employee_id: int, event_type: str, geofence_result: dict, db: Session) -> Dict:
        """출근/퇴근 이벤트 처리"""
        today = datetime.now().date()
        
        # 오늘의 출근 기록 조회
        attendance = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time()),
                AttendanceRecord.check_in_time < datetime.combine(today + timedelta(days=1), datetime.min.time())
            )
        ).first()
        
        if event_type == "geofence_enter" and geofence_result["inside"]:
            # 출근 처리
            if not attendance:
                # 새로운 출근 기록 생성
                attendance = AttendanceRecord(
                    employee_id=employee_id,
                    site_id=geofence_result["site"].id,
                    check_in_time=datetime.now(),
                    status="checked_in",
                    check_in_location=f"{geofence_result['site'].name} ({geofence_result['distance']:.1f}m)"
                )
                db.add(attendance)
                db.commit()
                
                return {"action": "check_in", "time": attendance.check_in_time}
        
        elif event_type == "geofence_exit" and attendance and not attendance.check_out_time:
            # 퇴근 처리
            attendance.check_out_time = datetime.now()
            attendance.status = "completed"
            attendance.check_out_location = f"Exited from work area"
            
            # 근무 시간 계산
            if attendance.check_in_time:
                work_duration = attendance.check_out_time - attendance.check_in_time
                attendance.total_work_minutes = int(work_duration.total_seconds() / 60)
            
            db.commit()
            
            return {"action": "check_out", "time": attendance.check_out_time}
        
        return {"action": "location_update"}

    @staticmethod
    def get_employee_current_status(employee_id: int, db: Session) -> Dict:
        """직원의 현재 상태 조회"""
        today = datetime.now().date()
        
        # 오늘의 출근 기록
        attendance = db.query(AttendanceRecord).filter(
            and_(
                AttendanceRecord.employee_id == employee_id,
                AttendanceRecord.check_in_time >= datetime.combine(today, datetime.min.time())
            )
        ).first()
        
        # 최근 위치
        last_location = db.query(LocationEvent).filter(
            LocationEvent.employee_id == employee_id
        ).order_by(LocationEvent.timestamp.desc()).first()
        
        # 직원의 할당된 근무지 조회
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        assigned_sites = []
        if employee and employee.assigned_sites:
            try:
                import json
                site_ids = json.loads(employee.assigned_sites)
                assigned_sites = db.query(Site).filter(Site.id.in_(site_ids)).all()
            except:
                pass
        
        status = "waiting"
        if attendance:
            if attendance.check_out_time:
                status = "completed"
            elif attendance.check_in_time:
                status = "working"
        
        return {
            "status": status,
            "attendance": attendance,
            "last_location": last_location,
            "current_site": last_location.site.name if last_location and last_location.site else None,
            "assigned_sites": assigned_sites,
            "check_in_time": attendance.check_in_time if attendance else None,
            "check_out_time": attendance.check_out_time if attendance else None,
            "site_name": attendance.site.name if attendance and attendance.site else None
        }
    
    @staticmethod
    def get_employee_assigned_sites(employee_id: int, db: Session) -> List[Site]:
        """직원에게 할당된 근무지 목록 조회"""
        employee = db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee or not employee.assigned_sites:
            return []
        
        try:
            import json
            site_ids = json.loads(employee.assigned_sites)
            return db.query(Site).filter(Site.id.in_(site_ids)).all()
        except:
            return []