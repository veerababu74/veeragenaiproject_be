"""
HuggingFace Dataset storage helper for blog images.

Reuses the existing HUGGINGFACE_TOKEN and HUGGINGFACE_BUCKET env vars.
Images are uploaded to:
  hf://datasets/<BUCKET>/blogs/images/<slug>/<filename>
and the public URL is returned.
"""

import logging
import mimetypes
import os
import uuid
from io import BytesIO

from huggingface_hub import HfApi
from Authentication.config import settings

logger = logging.getLogger("veera.blog.storage")

_api: HfApi | None = None


def _get_api() -> HfApi:
    global _api
    if _api is None:
        if not settings.huggingface_token:
            raise RuntimeError("HUGGINGFACE_TOKEN is not configured")
        _api = HfApi(token=settings.huggingface_token)
    return _api


def _repo_id() -> str:
    if not settings.huggingface_bucket:
        raise RuntimeError("HUGGINGFACE_BUCKET is not configured")
    return settings.huggingface_bucket


def upload_blog_image(content: bytes, slug: str, content_type: str) -> str:
    """
    Upload a blog image to HuggingFace and return its public HTTPS URL.

    Args:
        content: Raw image bytes.
        slug: Blog post slug used as folder name.
        content_type: MIME type of the image (e.g. 'image/jpeg').

    Returns:
        Public HTTPS URL of the uploaded file.
    """
    api = _get_api()
    repo_id = _repo_id()

    extension = mimetypes.guess_extension(content_type) or ".jpg"
    # mimetypes can return .jpe for jpeg — normalise
    if extension in (".jpe", ".jpeg"):
        extension = ".jpg"

    filename = f"{uuid.uuid4().hex}{extension}"
    path_in_repo = f"blogs/images/{slug}/{filename}"

    logger.info("Uploading blog image | repo=%s | path=%s | size=%d bytes", repo_id, path_in_repo, len(content))

    api.upload_file(
        path_or_fileobj=BytesIO(content),
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"Upload blog image for {slug}",
    )

    # Construct the public URL
    # HuggingFace datasets raw file URL pattern:
    # https://huggingface.co/datasets/<repo_id>/resolve/main/<path>
    public_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{path_in_repo}"
    logger.info("Blog image uploaded | url=%s", public_url)
    return public_url
