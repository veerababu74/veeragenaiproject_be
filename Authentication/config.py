from functools import lru_cache
import os
from pathlib import Path
from tempfile import gettempdir
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ENV_LOCAL_FILE = Path(__file__).resolve().parent.parent / ".env.local"


class Settings(BaseSettings):
    mongodb_url: str
    mongodb_database: str = "veeragenai"
    jwt_secret: str
    admin_emails: str = ""
    frontend_url: str = "http://localhost:5173"
    frontend_urls: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_workspace_redirect_uri: str = "http://localhost:8000/workspace-agent/google/callback"
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_profile_folder: str = "veeragenai/profile-pictures"
    cloudinary_project_folder: str = "veeragenai/projects"
    huggingface_token: str = ""
    huggingface_bucket: str = "veera20/veeragenaiproject"
    pinecone_api_key: str = ""
    pinecone_index: str = "veeragenai-basic-rag"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    demo_email: str = ""
    demo_password: str = ""
    data_dir: str = ""

    model_config = SettingsConfigDict(env_file=(ENV_FILE, ENV_LOCAL_FILE), extra="ignore")

    @property
    def admin_email_set(self):
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}

    @property
    def frontend_url_set(self):
        return {
            url.strip().rstrip("/")
            for url in f"{self.frontend_url},{self.frontend_urls}".split(",")
            if url.strip()
        }

    @property
    def demo_enabled(self):
        return bool(self.demo_email and self.demo_password)

    def sqlite_path(self, filename: str, default_directory: Path):
        if os.getenv("VERCEL"):
            directory = Path(gettempdir()) / "veeragenai"
        else:
            directory = Path(self.data_dir) if self.data_dir else default_directory
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename

    def role_for_email(self, email: str):
        return "admin" if email.lower() in self.admin_email_set else "user"


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()