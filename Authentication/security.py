from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import randbelow

import jwt
from bson import ObjectId
from fastapi import Cookie, HTTPException, status
from pwdlib import PasswordHash

from .config import settings
from .database import users


password_hash = PasswordHash.recommended()


def create_otp():
    return f"{randbelow(1_000_000):06d}"


def hash_otp(otp: str):
    return sha256(otp.encode()).hexdigest()


def create_access_token(user_id: str):
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode({"sub": user_id, "exp": expires}, settings.jwt_secret, algorithm="HS256")


def decode_access_token(access_token: str | None):
    if not access_token:
        return None
    try:
        payload = jwt.decode(access_token, settings.jwt_secret, algorithms=["HS256"])
        return payload["sub"]
    except (jwt.InvalidTokenError, KeyError):
        return None


async def optional_user_id(access_token: str | None = Cookie(default=None)):
    return decode_access_token(access_token)


async def current_user_id(access_token: str | None = Cookie(default=None)):
    user_id = decode_access_token(access_token)
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account is disabled")
    return user_id


def has_project_access(user, project_id):
    return bool(user) and user.get("role") != "demo" and (
        user.get("role") == "admin" or project_id not in user.get("blocked_projects", [])
    )