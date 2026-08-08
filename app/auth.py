import hashlib
import hmac
import base64
import json
import time
import os
from fastapi import Request, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = b"quiz_app_secret_key_extremely_secure_12345"
TOKEN_EXPIRY = 24 * 60 * 60 # 24 hours in seconds

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    return f"{base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()}"

def verify_password(password: str, hashed_str: str) -> bool:
    try:
        salt_b64, key_b64 = hashed_str.split(':')
        salt = base64.b64decode(salt_b64)
        expected_key = base64.b64decode(key_b64)
        actual_key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
        return hmac.compare_digest(expected_key, actual_key)
    except Exception:
        return False

def create_token(payload: dict) -> str:
    payload = payload.copy()
    payload['exp'] = int(time.time()) + TOKEN_EXPIRY
    payload_json = json.dumps(payload).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode().rstrip('=')
    
    # Calculate HMAC signature
    signature = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode().rstrip('=')
    
    return f"{payload_b64}.{signature_b64}"

def verify_token(token: str) -> dict:
    try:
        parts = token.split('.')
        if len(parts) != 2:
            return None
        payload_b64, signature_b64 = parts
        
        # Verify signature
        expected_sig = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip('=')
        
        if not hmac.compare_digest(expected_sig_b64, signature_b64):
            return None
        
        # Decode and check expiration
        # Add padding back if necessary
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += '=' * (4 - rem)
        payload_json = base64.urlsafe_b64decode(payload_b64.encode()).decode()
        payload = json.loads(payload_json)
        
        if payload.get('exp', 0) < time.time():
            return None
            
        return payload
    except Exception:
        return None

def get_current_user(request: Request):
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    
    if not token:
        token = request.cookies.get("token")
            
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
        
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token"
        )
    return payload

def get_current_teacher(request: Request):
    user = get_current_user(request)
    if user.get("role") != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Teachers only"
        )
    return user

def get_current_student(request: Request):
    user = get_current_user(request)
    if user.get("role") != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Students only"
        )
    return user
