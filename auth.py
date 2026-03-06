import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db, User
from dotenv import load_dotenv

load_dotenv()

# Secret key to sign JWT token
SECRET_KEY = os.getenv("SECRET_KEY", "b39dc1d8c11fb62788e0db4742f1f3e7") # In a real app, generate a secure random string
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 days expiration

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Custom OAuth scheme that also reads from cookies if headers aren't present
class OAuth2PasswordBearerWithCookie(OAuth2PasswordBearer):
    async def __call__(self, request: Request):
        authorization = request.headers.get("Authorization")
        if authorization:
            return await super().__call__(request)
        
        cookie_authorization = request.cookies.get("access_token")
        if not cookie_authorization:
            return None
        
        # Token is expected as "Bearer <token>"
        try:
            scheme, param = cookie_authorization.split()
            if scheme.lower() == "bearer":
                return param
        except ValueError:
            pass
        return None

oauth2_scheme = OAuth2PasswordBearerWithCookie(tokenUrl="/token", auto_error=False)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        # User is not logged in
        return None
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return current_user
