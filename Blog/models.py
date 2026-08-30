from typing import Annotated, Literal
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------

class HeadingBlock(BaseModel):
    type: Literal["heading1", "heading2", "heading3"]
    content: str = Field(min_length=1, max_length=300)


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    content: str = Field(min_length=0, max_length=5000)


class ImageBlock(BaseModel):
    type: Literal["image"]
    url: str = Field(min_length=1, max_length=1000)
    alt: str = Field(default="", max_length=300)
    caption: str = Field(default="", max_length=300)


class MermaidBlock(BaseModel):
    type: Literal["mermaid"]
    content: str = Field(min_length=1, max_length=5000)


class CodeBlock(BaseModel):
    type: Literal["code"]
    language: str = Field(default="", max_length=40)
    content: str = Field(min_length=0, max_length=10000)


class TableRow(BaseModel):
    cells: list[str] = Field(min_length=1, max_length=10)


class TableBlock(BaseModel):
    type: Literal["table"]
    headers: list[str] = Field(min_length=1, max_length=10)
    rows: list[TableRow] = Field(default_factory=list, max_length=50)


class BulletListBlock(BaseModel):
    type: Literal["bullet-list"]
    items: list[str] = Field(min_length=1, max_length=30)


class NumberedListBlock(BaseModel):
    type: Literal["numbered-list"]
    items: list[str] = Field(min_length=1, max_length=30)


class DividerBlock(BaseModel):
    type: Literal["divider"]


BlogBlock = Annotated[
    HeadingBlock
    | ParagraphBlock
    | ImageBlock
    | MermaidBlock
    | CodeBlock
    | TableBlock
    | BulletListBlock
    | NumberedListBlock
    | DividerBlock,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Blog post models
# ---------------------------------------------------------------------------

class BlogPost(BaseModel):
    slug: str = Field(
        min_length=2, max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe unique identifier",
    )
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=400, description="Short summary shown on blog cards")
    cover_image_url: str = Field(default="", max_length=1000)
    cover_image_alt: str = Field(default="", max_length=300)
    tags: list[str] = Field(default_factory=list, max_length=8)
    project_id: str | None = Field(default=None, max_length=80, description="Optional project catalog ID this post belongs to")
    published: bool = Field(default=False)
    blocks: list[BlogBlock] = Field(default_factory=list, max_length=200)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags):
        normalized = [t.strip() for t in tags if t.strip()]
        if any(len(t) > 40 for t in normalized):
            raise ValueError("Tags must be 40 characters or fewer")
        return list(dict.fromkeys(normalized))

    @field_validator("cover_image_url")
    @classmethod
    def validate_image_url(cls, url):
        if url and not url.startswith("https://"):
            raise ValueError("Cover image URL must use HTTPS")
        return url


class BlogPostUpdate(BaseModel):
    """Used for PUT — all fields optional so admin can save partial state."""
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=400)
    cover_image_url: str | None = Field(default=None, max_length=1000)
    cover_image_alt: str | None = Field(default=None, max_length=300)
    tags: list[str] | None = Field(default=None, max_length=8)
    project_id: str | None = Field(default=None, max_length=80)
    published: bool | None = None
    blocks: list[BlogBlock] | None = Field(default=None, max_length=200)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags):
        if tags is None:
            return None
        normalized = [tag.strip() for tag in tags if tag.strip()]
        if any(len(tag) > 40 for tag in normalized):
            raise ValueError("Tags must be 40 characters or fewer")
        return list(dict.fromkeys(normalized))

    @field_validator("cover_image_url")
    @classmethod
    def validate_image_url(cls, url):
        if url and not url.startswith("https://"):
            raise ValueError("Cover image URL must use HTTPS")
        return url


class BlogListItem(BaseModel):
    """Lightweight representation used in paginated list responses."""
    slug: str
    title: str
    description: str
    cover_image_url: str
    cover_image_alt: str
    tags: list[str]
    project_id: str | None
    published: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BlogListResponse(BaseModel):
    posts: list[BlogListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
