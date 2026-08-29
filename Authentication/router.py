from datetime import datetime, timedelta, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pymongo.errors import DuplicateKeyError

from .config import settings
from .cloudinary_storage import delete_profile_picture, is_configured, upload_profile_picture
from .database import users
from .mailer import send_password_reset_email, send_verification_email
from .models import (
    EmailRequest,
    GoogleLoginRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UpdateUserRequest,
    UserResponse,
    VerifyEmailRequest,
)
from .security import (
    create_access_token,
    create_otp,
    current_user_id,
    hash_otp,
    optional_user_id,
    password_hash,
)


router = APIRouter(prefix="/auth", tags=["Authentication"])


def user_response(user):
    return UserResponse(
        id=str(user["_id"]),
        name=user["name"],
        email=user["email"],
        provider=user["provider"],
        is_verified=user["is_verified"],
        first_name=user.get("first_name"),
        last_name=user.get("last_name"),
        linkedin_url=user.get("linkedin_url"),
        github_url=user.get("github_url"),
        phone_number=user.get("phone_number"),
        address=user.get("address"),
        profile_picture_url=user.get("profile_picture_url"),
        role=user.get("role", "user"),
        is_active=user.get("is_active", True),
        blocked_projects=user.get("blocked_projects", []),
    )


def set_session(response: Response, user_id: str):
    response.set_cookie(
        "access_token",
        create_access_token(user_id),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=7 * 24 * 60 * 60,
    )


async def send_otp_or_fail(email: str, otp: str):
    try:
        await send_verification_email(email, otp)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Verification email could not be sent") from error


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest):
    if await users.find_one({"email": data.email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    otp = create_otp()
    await send_otp_or_fail(data.email, otp)
    document = {
        "name": data.email.split("@", 1)[0],
        "email": data.email,
        "password_hash": password_hash.hash(data.password),
        "provider": "email",
        "is_verified": False,
        "role": settings.role_for_email(data.email),
        "is_active": True,
        "blocked_projects": [],
        "verification_otp": hash_otp(otp),
        "verification_expires": datetime.now(timezone.utc) + timedelta(minutes=10),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        await users.insert_one(document)
    except DuplicateKeyError as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from error
    return {"message": "Verification code sent"}


@router.post("/verify-email")
async def verify_email(data: VerifyEmailRequest):
    user = await users.find_one({"email": data.email.lower()})
    now = datetime.now(timezone.utc)
    if not user or user.get("verification_otp") != hash_otp(data.otp):
        raise HTTPException(status_code=400, detail="Invalid verification code")
    expires = user.get("verification_expires")
    if not expires or expires.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=400, detail="Verification code has expired")
    await users.update_one(
        {"_id": user["_id"]},
        {"$set": {"is_verified": True}, "$unset": {"verification_otp": "", "verification_expires": ""}},
    )
    return {"message": "Email verified. You can now sign in."}


@router.post("/resend-verification")
async def resend_verification(data: EmailRequest):
    user = await users.find_one({"email": data.email.lower(), "provider": "email"})
    if not user or user["is_verified"]:
        return {"message": "If the account needs verification, a code was sent"}
    otp = create_otp()
    await send_otp_or_fail(user["email"], otp)
    await users.update_one(
        {"_id": user["_id"]},
        {"$set": {"verification_otp": hash_otp(otp), "verification_expires": datetime.now(timezone.utc) + timedelta(minutes=10)}},
    )
    return {"message": "If the account needs verification, a code was sent"}


@router.post("/login", response_model=UserResponse)
async def login(data: LoginRequest, response: Response):
    user = await users.find_one({"email": data.email.lower(), "provider": "email"})
    if not user or not password_hash.verify(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user["is_verified"]:
        raise HTTPException(status_code=403, detail="Verify your email before signing in")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Your account is disabled")
    set_session(response, str(user["_id"]))
    return user_response(user)


@router.post("/forgot-password")
async def forgot_password(data: EmailRequest):
    message = "If a verified password account exists, a reset code was sent"
    user = await users.find_one(
        {"email": data.email.lower(), "provider": "email", "is_verified": True}
    )
    if not user:
        return {"message": message}
    if user.get("role") == "demo":
        return {"message": message}
    otp = create_otp()
    try:
        await send_password_reset_email(user["email"], otp)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Password reset email could not be sent") from error
    await users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_reset_otp": hash_otp(otp),
                "password_reset_expires": datetime.now(timezone.utc) + timedelta(minutes=10),
            }
        },
    )
    return {"message": message}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest):
    user = await users.find_one({"email": data.email.lower(), "provider": "email"})
    now = datetime.now(timezone.utc)
    if not user or user.get("password_reset_otp") != hash_otp(data.otp):
        raise HTTPException(status_code=400, detail="Invalid reset code")
    expires = user.get("password_reset_expires")
    if not expires or expires.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=400, detail="Reset code has expired")
    await users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"password_hash": password_hash.hash(data.new_password)},
            "$unset": {"password_reset_otp": "", "password_reset_expires": ""},
        },
    )
    return {"message": "Password reset. You can now sign in"}


@router.post("/google", response_model=UserResponse)
async def google_login(data: GoogleLoginRequest, response: Response):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    try:
        info = id_token.verify_oauth2_token(
            data.credential, google_requests.Request(), settings.google_client_id
        )
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid Google credential") from error
    if not info.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google email is not verified")

    email = info["email"].lower()
    user = await users.find_one({"email": email})
    if user and user["provider"] != "google":
        raise HTTPException(status_code=409, detail="This email is registered with a password")
    if not user:
        document = {
            "name": info.get("name") or email.split("@", 1)[0],
            "first_name": info.get("given_name"),
            "last_name": info.get("family_name"),
            "email": email,
            "provider": "google",
            "google_sub": info["sub"],
            "is_verified": True,
            "role": settings.role_for_email(email),
            "is_active": True,
            "blocked_projects": [],
            "created_at": datetime.now(timezone.utc),
        }
        result = await users.insert_one(document)
        document["_id"] = result.inserted_id
        user = document
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Your account is disabled")
    changes = {
        "name": info.get("name") or user["name"],
        "first_name": info.get("given_name"),
        "last_name": info.get("family_name"),
    }
    if info.get("picture") and not user.get("profile_picture_url") and is_configured():
        try:
            changes.update(await upload_profile_picture(info["picture"], str(user["_id"])))
        except Exception:
            pass
    changes = {key: value for key, value in changes.items() if value is not None}
    if changes:
        await users.update_one({"_id": user["_id"]}, {"$set": changes})
        user.update(changes)
    set_session(response, str(user["_id"]))
    return user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(
        "access_token",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )


@router.get("/me", response_model=UserResponse)
async def me(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user_response(user)


@router.patch("/me", response_model=UserResponse)
async def update_me(data: UpdateUserRequest, user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    changes = {}
    if data.name is not None:
        changes["name"] = data.name.strip()
    for field in (
        "first_name",
        "last_name",
        "linkedin_url",
        "github_url",
        "phone_number",
        "address",
    ):
        value = getattr(data, field)
        if field in data.model_fields_set:
            changes[field] = str(value).strip() if value is not None else None
    if data.new_password:
        if user["provider"] != "email" or not password_hash.verify(
            data.current_password, user["password_hash"]
        ):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        changes["password_hash"] = password_hash.hash(data.new_password)
    await users.update_one({"_id": user["_id"]}, {"$set": changes})
    user.update(changes)
    return user_response(user)


@router.post("/me/profile-picture", response_model=UserResponse)
async def update_profile_picture(
    picture: UploadFile = File(...), user_id: str = Depends(current_user_id)
):
    if picture.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Use a JPEG, PNG, or WebP image")
    content = await picture.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Profile picture must be 5 MB or smaller")
    previous_user = await users.find_one({"_id": ObjectId(user_id)})
    if not previous_user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        changes = await upload_profile_picture(content, user_id)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Profile picture upload failed") from error
    try:
        user = await users.find_one_and_update(
            {"_id": previous_user["_id"]}, {"$set": changes}, return_document=True
        )
        previous_public_id = previous_user.get("profile_picture_public_id")
        if previous_public_id and previous_public_id != changes["profile_picture_public_id"]:
            await delete_profile_picture(previous_public_id)
    except Exception as error:
        previous_picture = {
            "profile_picture_url": previous_user.get("profile_picture_url"),
            "profile_picture_public_id": previous_user.get("profile_picture_public_id"),
        }
        await users.update_one({"_id": previous_user["_id"]}, {"$set": previous_picture})
        try:
            await delete_profile_picture(changes["profile_picture_public_id"])
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Profile picture replacement failed") from error
    return user_response(user)


@router.get("/session", response_model=UserResponse | None)
async def session(user_id: str | None = Depends(optional_user_id)):
    if not user_id or not ObjectId.is_valid(user_id):
        return None
    user = await users.find_one({"_id": ObjectId(user_id)})
    return user_response(user) if user and user.get("is_active", True) else None