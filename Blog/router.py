"""
Blog FastAPI router.

Public routes  (no auth):
  GET  /blogs                  — paginated list of published posts
  GET  /blogs/{slug}           — single published post

Admin routes   (admin auth required):
  GET  /admin/blogs            — all posts (including unpublished)
  GET  /admin/blogs/{slug}     — single post (any state)
  POST /admin/blogs            — create new post
  PUT  /admin/blogs/{slug}     — update post
  DELETE /admin/blogs/{slug}   — delete post
  POST /admin/blogs/{slug}/images — upload an image to HuggingFace, returns URL
"""

import logging
import re
from datetime import datetime, timezone
from math import ceil

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pymongo import ReturnDocument

from Authentication.database import project_catalog, users
from Authentication.security import current_user_id

from .models import BlogListItem, BlogListResponse, BlogPost, BlogPostUpdate
from .storage import upload_blog_image

logger = logging.getLogger("veera.blog")

# ---- Lazy import to avoid circular dep ----
from Authentication.database import database as _db


def _blogs():
    return _db.blogs


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

async def _require_admin(user_id: str = Depends(current_user_id)):
    admin = await users.find_one({"_id": ObjectId(user_id)})
    if not admin or admin.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _doc_to_list_item(doc: dict) -> dict:
    return {
        "slug": doc["slug"],
        "title": doc["title"],
        "description": doc.get("description", ""),
        "cover_image_url": doc.get("cover_image_url", ""),
        "cover_image_alt": doc.get("cover_image_alt", ""),
        "tags": doc.get("tags", []),
        "project_id": doc.get("project_id"),
        "published": doc.get("published", False),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _doc_to_post(doc: dict) -> dict:
    return {
        **_doc_to_list_item(doc),
        "blocks": doc.get("blocks", []),
    }


async def _require_project(project_id: str | None):
    if project_id and not await project_catalog.find_one(
        {"_id": "default", "projects.id": project_id}, {"_id": 1}
    ):
        raise HTTPException(status_code=400, detail="Linked project ID does not exist")


async def _sync_project_link(previous_project_id: str | None, project_id: str | None, slug: str):
    if previous_project_id and previous_project_id != project_id:
        await project_catalog.update_one(
            {"_id": "default", "projects": {"$elemMatch": {"id": previous_project_id, "blog_slug": slug}}},
            {"$set": {"projects.$.blog_slug": None}},
        )
    if project_id:
        await project_catalog.update_one(
            {"_id": "default", "projects.id": project_id},
            {"$set": {"projects.$.blog_slug": slug}},
        )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

public_router = APIRouter(tags=["Blog"])
admin_router = APIRouter(prefix="/admin", tags=["Blog Admin"])

PAGE_SIZE = 8


def _public_blog_filter(search: str) -> dict:
    query = {"published": True}
    if search:
        pattern = {"$regex": re.escape(search), "$options": "i"}
        query["$or"] = [
            {"title": pattern},
            {"description": pattern},
            {"tags": pattern},
        ]
    return query


# ---- Public ----------------------------------------------------------------

@public_router.get("/blogs", response_model=BlogListResponse)
async def list_blogs(
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=PAGE_SIZE),
    search: str = Query("", max_length=100),
):
    blogs = _blogs()
    query = _public_blog_filter(search.strip())
    skip = (page - 1) * page_size
    cursor = blogs.find(query, {"blocks": 0}).sort("created_at", -1).skip(skip).limit(page_size)
    docs = await cursor.to_list(length=page_size)
    total = await blogs.count_documents(query)
    return {
        "posts": [_doc_to_list_item(doc) for doc in docs],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, ceil(total / page_size)),
    }


@public_router.get("/blogs/{slug}")
async def get_blog(slug: str):
    blogs = _blogs()
    doc = await blogs.find_one({"slug": slug, "published": True})
    if not doc:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return _doc_to_post(doc)


# ---- Admin -----------------------------------------------------------------

@admin_router.get("/blogs", response_model=BlogListResponse)
async def admin_list_blogs(
    page: int = Query(1, ge=1),
    _: dict = Depends(_require_admin),
):
    blogs = _blogs()
    skip = (page - 1) * PAGE_SIZE
    cursor = blogs.find({}, {"blocks": 0}).sort("created_at", -1).skip(skip).limit(PAGE_SIZE)
    docs = await cursor.to_list(length=PAGE_SIZE)
    total = await blogs.count_documents({})
    return {
        "posts": [_doc_to_list_item(doc) for doc in docs],
        "total": total,
        "page": page,
        "page_size": PAGE_SIZE,
        "total_pages": max(1, ceil(total / PAGE_SIZE)),
    }


@admin_router.get("/blogs/{slug}")
async def admin_get_blog(slug: str, _: dict = Depends(_require_admin)):
    blogs = _blogs()
    doc = await blogs.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Blog post not found")
    return _doc_to_post(doc)


@admin_router.post("/blogs", status_code=201)
async def create_blog(post: BlogPost, admin: dict = Depends(_require_admin)):
    blogs = _blogs()
    if await blogs.find_one({"slug": post.slug}):
        raise HTTPException(status_code=409, detail="A blog post with this slug already exists")
    await _require_project(post.project_id)
    now = datetime.now(timezone.utc)
    doc = post.model_dump()
    doc.update({
        "created_at": now,
        "updated_at": now,
        "created_by": str(admin["_id"]),
    })
    await blogs.insert_one(doc)
    await _sync_project_link(None, post.project_id, post.slug)
    return _doc_to_post(doc)


@admin_router.put("/blogs/{slug}")
async def update_blog(slug: str, update: BlogPostUpdate, admin: dict = Depends(_require_admin)):
    blogs = _blogs()
    existing = await blogs.find_one({"slug": slug})
    if not existing:
        raise HTTPException(status_code=404, detail="Blog post not found")
    await _require_project(update.project_id if "project_id" in update.model_fields_set else None)
    changes = update.model_dump(exclude_none=True)
    if "project_id" in update.model_fields_set:
        changes["project_id"] = update.project_id
    changes["updated_at"] = datetime.now(timezone.utc)
    changes["updated_by"] = str(admin["_id"])
    doc = await blogs.find_one_and_update(
        {"slug": slug},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    if "project_id" in update.model_fields_set:
        await _sync_project_link(existing.get("project_id"), update.project_id, slug)
    return _doc_to_post(doc)


@admin_router.delete("/blogs/{slug}", status_code=204)
async def delete_blog(slug: str, _: dict = Depends(_require_admin)):
    blogs = _blogs()
    result = await blogs.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Blog post not found")
    await project_catalog.update_one(
        {"_id": "default", "projects.blog_slug": slug},
        {"$set": {"projects.$[project].blog_slug": None}},
        array_filters=[{"project.blog_slug": slug}],
    )


@admin_router.post("/blogs/{slug}/images")
async def upload_blog_image_endpoint(
    slug: str,
    image: UploadFile = File(...),
    _: dict = Depends(_require_admin),
):
    blogs = _blogs()
    if not await blogs.find_one({"slug": slug}):
        raise HTTPException(status_code=404, detail="Blog post not found — create it first")
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if image.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Use a JPEG, PNG, WebP, or GIF image")
    content = await image.read(16 * 1024 * 1024 + 1)
    if len(content) > 16 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be 16 MB or smaller")
    try:
        url = upload_blog_image(content, slug, image.content_type)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Blog image upload failed")
        raise HTTPException(status_code=502, detail="Image upload failed") from error
    return {"image_url": url}
