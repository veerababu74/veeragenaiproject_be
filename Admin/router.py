import re

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pymongo import ReturnDocument

from Authentication.database import users
from Authentication.cloudinary_storage import upload_project_image
from Authentication.models import UserResponse
from Authentication.router import user_response
from Authentication.security import current_user_id

from .landing import (
    get_landing_content, get_project_catalog, get_public_project_catalog,
    get_workspace_projects, save_landing_content, save_project_catalog,
)
from .models import AdminUpdateUserRequest, LandingContent, LandingPortfolioProject, ProjectCatalog


router = APIRouter(prefix="/admin", tags=["Admin"])
public_router = APIRouter(tags=["Landing"])


async def current_admin(user_id: str = Depends(current_user_id)):
    admin = await users.find_one({"_id": ObjectId(user_id)})
    if not admin or admin.get("role", "user") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin


@public_router.get("/landing", response_model=LandingContent)
async def landing():
    return await get_landing_content()


@public_router.get("/portfolio", response_model=ProjectCatalog)
async def portfolio():
    return await get_public_project_catalog()


@public_router.get("/projects/catalog", response_model=list[LandingPortfolioProject])
async def project_catalog(_: str = Depends(current_user_id)):
    return await get_workspace_projects()


@router.get("/landing", response_model=LandingContent)
async def admin_landing(_: dict = Depends(current_admin)):
    return await get_landing_content()


@router.put("/landing", response_model=LandingContent)
async def update_landing(content: LandingContent, admin: dict = Depends(current_admin)):
    return await save_landing_content(content, str(admin["_id"]))


@router.get("/projects", response_model=ProjectCatalog)
async def admin_projects(_: dict = Depends(current_admin)):
    return await get_project_catalog()


@router.put("/projects", response_model=ProjectCatalog)
async def update_projects(content: ProjectCatalog, admin: dict = Depends(current_admin)):
    return await save_project_catalog(content, str(admin["_id"]))


@router.post("/projects/{project_id}/image")
async def upload_admin_project_image(
    project_id: str, picture: UploadFile = File(...), _: dict = Depends(current_admin)
):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", project_id):
        raise HTTPException(status_code=400, detail="Use a valid project ID before uploading")
    if picture.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Use a JPEG, PNG, or WebP image")
    content = await picture.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Project image must be 8 MB or smaller")
    try:
        return await upload_project_image(content, project_id)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Project image upload failed") from error


@router.get("/users", response_model=list[UserResponse])
async def list_users(_: dict = Depends(current_admin)):
    documents = await users.find({}).sort("created_at", -1).to_list(length=500)
    return [user_response(user) for user in documents]


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user_access(
    user_id: str, data: AdminUpdateUserRequest, admin: dict = Depends(current_admin)
):
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if data.is_active is False and str(admin["_id"]) == user_id:
        raise HTTPException(status_code=400, detail="You cannot disable your own admin account")
    changes = data.model_dump(exclude_none=True)
    user = await users.find_one_and_update(
        {"_id": ObjectId(user_id)}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user_response(user)