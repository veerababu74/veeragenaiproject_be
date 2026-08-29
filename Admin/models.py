from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AdminUpdateUserRequest(BaseModel):
    is_active: bool | None = None
    blocked_projects: list[str] | None = Field(default=None, max_length=50)

    @field_validator("blocked_projects")
    @classmethod
    def normalize_projects(cls, projects):
        if projects is None:
            return None
        normalized = [project.strip() for project in projects if project.strip()]
        if any(len(project) > 80 for project in normalized):
            raise ValueError("Project identifiers must be 80 characters or fewer")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def require_change(self):
        if self.is_active is None and self.blocked_projects is None:
            raise ValueError("Provide active status or blocked projects")
        return self


class LandingHeroSlide(BaseModel):
    eyebrow: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=320)
    image_url: str = Field(min_length=1, max_length=1000)
    image_alt: str = Field(min_length=1, max_length=160)


class LandingMetric(BaseModel):
    value: str = Field(min_length=1, max_length=20)
    label: str = Field(min_length=1, max_length=80)


class LandingFeature(BaseModel):
    icon: Literal["robot", "brain", "cpu", "vision", "chart", "workflow"]
    eyebrow: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=280)


class LandingRoadmapItem(BaseModel):
    phase: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=280)
    status: Literal["available", "building", "planned"]


class LandingLink(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    href: str = Field(min_length=1, max_length=500)


class LandingPortfolioProject(BaseModel):
    id: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=320)
    category: str = Field(min_length=1, max_length=60)
    tags: list[str] = Field(default_factory=list, max_length=8)
    image_url: str = Field(min_length=1, max_length=1000)
    image_alt: str = Field(min_length=1, max_length=160)
    status: Literal["available", "beta", "coming-soon"]
    featured: bool = False
    show_public: bool = True
    show_workspace: bool = True
    display_order: int = Field(default=0, ge=0, le=999)
    project_url: str = Field(min_length=1, max_length=500)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, category):
        return category.strip()

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags):
        normalized = [tag.strip() for tag in tags if tag.strip()]
        if any(len(tag) > 40 for tag in normalized):
            raise ValueError("Project tags must be 40 characters or fewer")
        return list(dict.fromkeys(normalized))

    @field_validator("image_url")
    @classmethod
    def require_https_image(cls, image_url):
        if not image_url.startswith("https://"):
            raise ValueError("Project image URLs must use HTTPS")
        return image_url

    @field_validator("project_url")
    @classmethod
    def validate_project_url(cls, project_url):
        if not project_url.startswith(("https://", "/", "#")):
            raise ValueError("Project URLs must use HTTPS, a site path, or an anchor")
        return project_url


class ProjectCatalog(BaseModel):
    nav_label: str = Field(default="Projects", min_length=1, max_length=40)
    eyebrow: str = Field(default="SELECTED WORK", min_length=1, max_length=60)
    title: str = Field(default="Projects built for real engineering questions", min_length=1, max_length=120)
    description: str = Field(default="Explore practical work across artificial intelligence, machine learning, and mechatronics.", min_length=1, max_length=320)
    projects: list[LandingPortfolioProject] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def require_unique_project_ids(self):
        project_ids = [project.id for project in self.projects]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("Portfolio project IDs must be unique")
        return self


class LandingContent(BaseModel):
    brand_name: str = Field(min_length=1, max_length=60)
    announcement: str = Field(min_length=1, max_length=160)
    capabilities_nav_label: str = Field(min_length=1, max_length=40)
    roadmap_nav_label: str = Field(min_length=1, max_length=40)
    login_label: str = Field(min_length=1, max_length=40)
    register_label: str = Field(min_length=1, max_length=40)
    hero_slides: list[LandingHeroSlide] = Field(min_length=1, max_length=5)
    primary_cta_label: str = Field(min_length=1, max_length=60)
    secondary_cta_label: str = Field(min_length=1, max_length=60)
    metrics: list[LandingMetric] = Field(min_length=1, max_length=6)
    features_eyebrow: str = Field(min_length=1, max_length=60)
    features_title: str = Field(min_length=1, max_length=120)
    features_description: str = Field(min_length=1, max_length=320)
    features: list[LandingFeature] = Field(min_length=1, max_length=8)
    roadmap_eyebrow: str = Field(min_length=1, max_length=60)
    roadmap_title: str = Field(min_length=1, max_length=120)
    roadmap_description: str = Field(min_length=1, max_length=320)
    roadmap: list[LandingRoadmapItem] = Field(min_length=1, max_length=8)
    cta_title: str = Field(min_length=1, max_length=120)
    cta_description: str = Field(min_length=1, max_length=280)
    cta_button_label: str = Field(min_length=1, max_length=60)
    footer_description: str = Field(min_length=1, max_length=280)
    footer_links: list[LandingLink] = Field(min_length=1, max_length=8)
    footer_copyright: str = Field(min_length=1, max_length=120)
