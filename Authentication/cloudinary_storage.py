import asyncio
from uuid import uuid4

import cloudinary
import cloudinary.uploader

from .config import settings


def is_configured():
    return all(
        (settings.cloudinary_cloud_name, settings.cloudinary_api_key, settings.cloudinary_api_secret)
    )


def configuration_error():
    required = {
        "CLOUDINARY_CLOUD_NAME": settings.cloudinary_cloud_name,
        "CLOUDINARY_API_KEY": settings.cloudinary_api_key,
        "CLOUDINARY_API_SECRET": settings.cloudinary_api_secret,
    }
    missing = [name for name, value in required.items() if not value]
    return f"Cloudinary is missing: {', '.join(missing)}"


def _upload(source, public_id: str, folder: str, transformation):
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    return cloudinary.uploader.upload(
        source,
        folder=folder,
        public_id=f"{public_id}-{uuid4().hex}",
        resource_type="image",
        invalidate=True,
        transformation=transformation,
    )


async def upload_profile_picture(source, user_id: str):
    if not is_configured():
        raise RuntimeError(configuration_error())
    result = await asyncio.to_thread(
        _upload,
        source,
        user_id,
        settings.cloudinary_profile_folder,
        [
            {"width": 512, "height": 512, "crop": "fill", "gravity": "face"},
            {"quality": "auto", "fetch_format": "auto"},
        ],
    )
    return {"profile_picture_url": result["secure_url"], "profile_picture_public_id": result["public_id"]}


async def upload_project_image(source, project_id: str):
    if not is_configured():
        raise RuntimeError(configuration_error())
    result = await asyncio.to_thread(
        _upload,
        source,
        project_id,
        settings.cloudinary_project_folder,
        [
            {"width": 1600, "height": 900, "crop": "fill", "gravity": "auto"},
            {"quality": "auto", "fetch_format": "auto"},
        ],
    )
    return {"image_url": result["secure_url"]}


def _delete(public_id: str):
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    result = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
    if result.get("result") not in {"ok", "not found"}:
        raise RuntimeError("Cloudinary did not delete the previous image")


async def delete_profile_picture(public_id: str):
    if public_id:
        await asyncio.to_thread(_delete, public_id)