from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.database import get_db, User
import os

# JWT 설정
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8시간

security = HTTPBearer()

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_role(required_roles: list):
    def role_checker(current_user: User = Depends(verify_token)):
        if current_user.role not in required_roles:
            raise HTTPException(
                status_code=403, 
                detail=f"Insufficient permissions. Required: {required_roles}"
            )
        return current_user
    return role_checker

# 편의 함수들
def require_admin(current_user: User = Depends(verify_token)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Admin role required"
        )
    return current_user

def require_manager_or_admin(current_user: User = Depends(verify_token)):
    if current_user.role not in ["admin", "manager"]:
        raise HTTPException(
            status_code=403,
            detail="Manager or Admin role required"
        )
    return current_user

# 직원 전용 의존성 (직원/매니저/관리자 허용 버전)
def require_employee(current_user: User = Depends(verify_token)):
    allowed = {"employee", "manager", "admin"}
    if getattr(current_user, "role", None) not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee role required"
        )
    return current_user