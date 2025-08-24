import requests
import json
from typing import Dict, Optional, Tuple
import os

class GeocodingService:
    """지도 API를 사용한 주소-좌표 변환 서비스"""
    
    @staticmethod
    def get_coordinates_from_address(address: str) -> Dict:
        """
        주소를 입력받아 위도, 경도를 반환
        카카오맵 API 사용 (무료 tier 사용 가능)
        """
        try:
            # 카카오맵 REST API 키 (실제 운영 시에는 환경변수로 설정)
            KAKAO_API_KEY = os.getenv('KAKAO_MAP_API_KEY', 'YOUR_KAKAO_API_KEY')
            
            if KAKAO_API_KEY == 'YOUR_KAKAO_API_KEY':
                # API 키가 없는 경우 서울 시청 좌표 반환 (개발용)
                return {
                    "success": True,
                    "latitude": 37.5666805,
                    "longitude": 126.9784147,
                    "address": address,
                    "message": "개발 모드: 서울 시청 좌표를 반환합니다."
                }
            
            # 카카오맵 API 호출
            url = "https://dapi.kakao.com/v2/local/search/address.json"
            headers = {
                "Authorization": f"KakaoAK {KAKAO_API_KEY}"
            }
            params = {
                "query": address
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data['documents']:
                    # 첫 번째 검색 결과 사용
                    result = data['documents'][0]
                    
                    if 'road_address' in result and result['road_address']:
                        # 도로명 주소가 있는 경우
                        coord_data = result['road_address']
                    else:
                        # 지번 주소만 있는 경우
                        coord_data = result['address']
                    
                    return {
                        "success": True,
                        "latitude": float(coord_data['y']),
                        "longitude": float(coord_data['x']),
                        "address": coord_data['address_name'],
                        "message": "주소를 좌표로 변환했습니다."
                    }
                else:
                    return {
                        "success": False,
                        "error": "주소를 찾을 수 없습니다. 정확한 주소를 입력해주세요."
                    }
            else:
                return {
                    "success": False,
                    "error": f"지도 API 호출 실패: {response.status_code}"
                }
                
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "지도 서비스 응답 시간 초과"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"지도 서비스 연결 실패: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"주소 변환 중 오류 발생: {str(e)}"
            }
    
    @staticmethod
    def get_address_from_coordinates(latitude: float, longitude: float) -> Dict:
        """
        위도, 경도를 입력받아 주소를 반환 (역지오코딩)
        """
        try:
            KAKAO_API_KEY = os.getenv('KAKAO_MAP_API_KEY', 'YOUR_KAKAO_API_KEY')
            
            if KAKAO_API_KEY == 'YOUR_KAKAO_API_KEY':
                return {
                    "success": True,
                    "address": "서울특별시 중구 태평로1가 31",
                    "message": "개발 모드: 샘플 주소를 반환합니다."
                }
            
            url = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
            headers = {
                "Authorization": f"KakaoAK {KAKAO_API_KEY}"
            }
            params = {
                "x": longitude,
                "y": latitude
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data['documents']:
                    result = data['documents'][0]
                    
                    # 도로명 주소 우선, 없으면 지번 주소
                    if 'road_address' in result and result['road_address']:
                        address = result['road_address']['address_name']
                    else:
                        address = result['address']['address_name']
                    
                    return {
                        "success": True,
                        "address": address,
                        "message": "좌표를 주소로 변환했습니다."
                    }
                else:
                    return {
                        "success": False,
                        "error": "해당 좌표의 주소를 찾을 수 없습니다."
                    }
            else:
                return {
                    "success": False,
                    "error": f"지도 API 호출 실패: {response.status_code}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"좌표 변환 중 오류 발생: {str(e)}"
            }
    
    @staticmethod
    def validate_coordinates(latitude: float, longitude: float) -> bool:
        """
        좌표 유효성 검증
        """
        try:
            # 위도는 -90 ~ 90, 경도는 -180 ~ 180
            if not (-90 <= latitude <= 90):
                return False
            if not (-180 <= longitude <= 180):
                return False
            
            # 한국 범위 대략적 검증 (선택사항)
            # 위도: 33-43, 경도: 124-132
            if not (33 <= latitude <= 43):
                return False
            if not (124 <= longitude <= 132):
                return False
                
            return True
        except:
            return False
