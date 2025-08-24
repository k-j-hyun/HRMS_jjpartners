# HRMS_kjh - 전문적인 인력관리 시스템

전문적인 기업 환경을 위한 블랙&화이트 톤의 인력관리 및 근태관리 시스템입니다.

## 빠른 시작

### 방법 1: 자동 설정 (권장)
```bash
python start.py
```

### 방법 2: 수동 설정
```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 데이터베이스 초기화
python setup_database.py

# 3. 서버 실행
python main.py
```

### 4. 브라우저에서 접속
```
http://localhost:8000
```

## 테스트 계정

### 관리자
- **ID**: admin
- **PW**: admin123

### 직원
- **ID**: employee  
- **PW**: emp123

## 로그인 문제 해결

로그인이 안 되는 경우 다음 단계를 따르세요:

### 1단계: 데이터베이스 초기화
```bash
python setup_database.py
```

### 2단계: 서버 재시작
```bash
python main.py
```

### 3단계: 브라우저 캐시 삭제
- 브라우저에서 F12 → Application/저장소 → Local Storage 삭제
- 페이지 새로고침 (Ctrl+F5)

### 4단계: 올바른 계정 정보 확인
- 관리자: `admin` / `admin123`
- 직원: `employee` / `emp123`

## 주요 기능

### 1. 회원가입 및 인증
- 직원 회원가입 기능
- 관리자/직원 역할 기반 로그인
- JWT 토큰 기반 인증

### 2. 관리자 기능
- 직원 관리 및 현황 모니터링
- 채용 공고 등록 및 관리 (관리자 전용)
- 실시간 근무 현황 확인
- 출입 기록 관리

### 3. 직원 기능
- GPS 기반 출근/퇴근 체크
- 실시간 위치 추적
- 근무 시간 자동 계산
- 채용 게시판 조회 및 지원

### 4. 채용 게시판
- 공고 등록 (관리자만 가능)
- 위치 기반 공고 검색
- 보증금 결제 시스템
- 지원 현황 관리

### 5. 지도 연동 기능
- 주소 입력 시 자동 좌표 변환
- 카카오맵 API 연동 지원
- 지오펜싱 기능

## 🛠️ 기술 스택

- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Frontend**: HTML5, CSS3, JavaScript (Vanilla)
- **Authentication**: JWT, bcrypt
- **Maps**: Kakao Map API (선택사항)
- **Design**: 전문적인 Black & White 톤

## API 문서

서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 문제 해결

### 로그인이 안 될 때
1. `setup_database.py` 실행하여 데이터베이스 재생성
2. 브라우저 캐시 및 Local Storage 삭제
3. 올바른 계정 정보 확인

### 서버가 시작되지 않을 때
1. Python 3.8 이상 버전 확인
2. `pip install -r requirements.txt` 실행
3. 포트 8000이 사용 중인지 확인

### 데이터베이스 오류가 날 때
1. `hrms_attendance.db` 파일 삭제
2. `setup_database.py` 재실행

## 디렉토리 구조

```
HRMS_kjh/
├── app/
│   ├── models/
│   │   └── database.py          # 데이터베이스 모델
│   ├── services/
│   │   ├── job_service.py       # 채용 관련 서비스
│   │   ├── location_service.py  # 위치 관련 서비스
│   │   ├── payment_service.py   # 결제 관련 서비스
│   │   └── geocoding_service.py # 지도/좌표 변환 서비스
│   └── auth.py                  # 인증 관련 함수
├── templates/
│   ├── login.html              # 로그인 페이지
│   ├── register.html           # 회원가입 페이지
│   ├── admin_dashboard.html    # 관리자 대시보드
│   ├── employee_mobile.html    # 직원용 모바일 인터페이스
│   ├── job_board.html          # 채용 게시판
│   └── my_applications.html    # 나의 지원 현황
├── static/                     # 정적 파일
├── main.py                     # 메인 애플리케이션
├── setup_database.py           # 데이터베이스 초기화 (NEW!)
├── start.py                    # 프로젝트 시작 스크립트 (NEW!)
└── requirements.txt            # 의존성 목록
```

## 환경 변수 설정 (선택사항)

카카오맵 API를 사용하려면 다음 환경변수를 설정하세요:

```bash
export KAKAO_MAP_API_KEY="your_kakao_api_key_here"
```

환경변수가 설정되지 않은 경우 기본 좌표(서울 시청)를 사용합니다.

## 주요 변경사항

### UI/UX 개선
- 모든 이모티콘 및 이모지 제거
- 전문적인 블랙&화이트 컬러 스킴 적용
- 깔끔하고 심플한 인터페이스

### 기능 추가
1. **회원가입 기능** - 직원이 직접 계정을 생성할 수 있음
2. **관리자 권한 제어** - 공고 등록은 관리자만 가능
3. **지도 API 연동** - 주소 입력 시 자동 좌표 변환
4. **향상된 보안** - 역할 기반 접근 제어

### 관리자 기능 강화
- 관리자 페이지에서 채용 공고 관리
- 등록된 공고가 직원 게시판에 자동 표시
- 실시간 지원자 현황 모니터링

### 버그 수정
- 데이터베이스 초기화 문제 해결
- 로그인 인증 오류 수정
- 테이블 삭제 방지 코드 추가

## 사용 팁

### 관리자로 로그인했을 때
1. 직원 현황을 실시간으로 모니터링할 수 있습니다
2. 채용 공고를 등록하고 지원자를 관리할 수 있습니다
3. 출입 기록과 위반 사항을 확인할 수 있습니다

### 직원으로 로그인했을 때
1. GPS를 통해 출근/퇴근을 체크할 수 있습니다
2. 채용 게시판에서 다른 일자리를 찾아볼 수 있습니다
3. 본인의 근무 기록을 확인할 수 있습니다

## 알려진 이슈

1. **GPS 정확도**: 실내에서는 GPS 정확도가 떨어질 수 있습니다
2. **브라우저 호환성**: 최신 버전의 Chrome, Firefox, Safari 사용을 권장합니다
3. **모바일 최적화**: 데스크톱 우선으로 설계되었으나 모바일에서도 작동합니다

## 지원

문의사항이 있으시면 이슈를 등록해주세요.

## 라이선스

MIT License

---
문의 : spellrain@naver.com
**© 2025 k-j-hyun & JJPartners. All rights reserved.**