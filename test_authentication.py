import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pymongo.errors import ServerSelectionTimeoutError

from Admin.landing import (
    DEFAULT_LANDING_CONTENT, DEFAULT_PROJECT_CATALOG, get_landing_content,
    get_project_catalog, get_public_project_catalog, get_workspace_projects, save_landing_content,
)
from Admin.models import AdminUpdateUserRequest, LandingContent, ProjectCatalog
from Authentication.config import settings
from Authentication.models import RegisterRequest, ResetPasswordRequest, UpdateUserRequest, UserResponse
from Authentication.cloudinary_storage import configuration_error, delete_profile_picture, upload_project_image
from Authentication.router import reset_password
from Authentication.security import create_otp, has_project_access, hash_otp, password_hash
from main import app


class AuthenticationValidationTests(unittest.TestCase):
    @patch.object(settings, "admin_emails", "veera99856@gmail.com,pveerababu199966@gmail.com")
    def test_admin_role_comes_from_email_allowlist(self):
        self.assertEqual(settings.role_for_email("VEERA99856@gmail.com"), "admin")
        self.assertEqual(settings.role_for_email("someone@gmail.com"), "user")

    def test_vercel_uses_writable_temporary_sqlite_directory(self):
        with TemporaryDirectory() as temporary_directory:
            with patch.dict("os.environ", {"VERCEL": "1"}), patch(
                "Authentication.config.gettempdir", return_value=temporary_directory
            ):
                database_path = settings.sqlite_path("project.db", Path("/var/data"))
        self.assertEqual(database_path, Path(temporary_directory) / "veeragenai" / "project.db")

    def test_vercel_startup_does_not_wait_for_mongodb_migrations(self):
        with patch.dict("os.environ", {"VERCEL": "1"}), patch(
            "main.initialize_mongodb", new_callable=AsyncMock
        ) as initialize_mongodb, patch("main.close_database", new_callable=AsyncMock):
            with TestClient(app) as client:
                response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        initialize_mongodb.assert_not_awaited()

    def test_supported_and_unsupported_email_domains(self):
        request = RegisterRequest(email="user@gmail.com", password="password123")
        self.assertEqual(request.email, "user@gmail.com")
        with self.assertRaises(ValidationError):
            RegisterRequest(email="user@yahoo.com", password="password123")

    def test_password_reset_requires_valid_otp_and_strong_password(self):
        reset = ResetPasswordRequest(
            email="user@gmail.com", otp="123456", new_password="newpassword123"
        )
        self.assertEqual(reset.otp, "123456")
        with self.assertRaises(ValidationError):
            ResetPasswordRequest(email="user@gmail.com", otp="123", new_password="short")

    def test_otp_is_six_digits_and_hashes_deterministically(self):
        otp = create_otp()
        self.assertRegex(otp, r"^\d{6}$")
        self.assertEqual(hash_otp(otp), hash_otp(otp))
        self.assertNotEqual(hash_otp(otp), otp)

    def test_extended_profile_is_optional_and_validated(self):
        existing_user = UserResponse(
            id="1", name="Veera", email="user@gmail.com", provider="google", is_verified=True
        )
        self.assertIsNone(existing_user.profile_picture_url)
        self.assertEqual(existing_user.role, "user")
        self.assertTrue(existing_user.is_active)
        self.assertEqual(existing_user.blocked_projects, [])
        update = UpdateUserRequest(
            first_name="Veera",
            linkedin_url="https://www.linkedin.com/in/veera",
            phone_number="+91 98765 43210",
        )
        self.assertEqual(update.first_name, "Veera")
        with self.assertRaises(ValidationError):
            UpdateUserRequest(phone_number="123")
        cleared = UpdateUserRequest(linkedin_url="", name="Veera")
        self.assertIsNone(cleared.linkedin_url)
        self.assertIn("linkedin_url", cleared.model_fields_set)

    def test_admin_update_normalizes_projects_and_requires_a_change(self):
        update = AdminUpdateUserRequest(blocked_projects=[" chatbot ", "analytics", "chatbot"])
        self.assertEqual(update.blocked_projects, ["chatbot", "analytics"])
        with self.assertRaises(ValidationError):
            AdminUpdateUserRequest()

    def test_project_access_is_default_on_and_uses_only_explicit_blocks(self):
        user = {"role": "user", "blocked_projects": ["basic-rag"]}
        self.assertTrue(has_project_access(user, "future-project"))
        self.assertFalse(has_project_access(user, "basic-rag"))
        self.assertTrue(has_project_access({"role": "admin", "blocked_projects": ["basic-rag"]}, "basic-rag"))
        self.assertFalse(has_project_access({"role": "demo", "blocked_projects": []}, "future-project"))

    def test_default_landing_content_has_required_public_sections(self):
        content = LandingContent(**DEFAULT_LANDING_CONTENT)
        self.assertGreaterEqual(len(content.hero_slides), 3)
        self.assertGreaterEqual(len(content.features), 3)
        self.assertGreaterEqual(len(content.roadmap), 3)


class LandingContentTests(unittest.IsolatedAsyncioTestCase):
    @patch("Admin.landing.landing_content.find_one", new_callable=AsyncMock)
    async def test_public_landing_uses_defaults_before_first_admin_save(self, find_one):
        find_one.return_value = None
        content = await get_landing_content()
        self.assertEqual(content.brand_name, "Veera AI")

    @patch("Admin.landing.landing_content.find_one", new_callable=AsyncMock)
    async def test_public_landing_uses_defaults_when_mongodb_is_unavailable(self, find_one):
        find_one.side_effect = ServerSelectionTimeoutError("unavailable")
        content = await get_landing_content()
        self.assertEqual(content.brand_name, "Veera AI")

    @patch("Admin.landing.project_catalog.find_one", new_callable=AsyncMock)
    async def test_project_catalog_uses_built_ins_when_mongodb_is_unavailable(self, find_one):
        find_one.side_effect = ServerSelectionTimeoutError("unavailable")
        content = await get_project_catalog()
        project_ids = {project.id for project in content.projects}
        self.assertTrue({"basic-chat", "basic-rag", "advanced-rag", "google-workspace-agent"} <= project_ids)

    @patch("Admin.landing.project_catalog.find_one", new_callable=AsyncMock)
    async def test_public_projects_hide_drafts_and_follow_display_order(self, find_one):
        document = deepcopy(DEFAULT_PROJECT_CATALOG)
        document["projects"][0]["show_public"] = False
        document["projects"][1]["display_order"] = 20
        document["projects"][2]["display_order"] = 10
        find_one.return_value = document

        content = await get_public_project_catalog()

        self.assertNotIn("basic-chat", [project.id for project in content.projects])
        self.assertEqual(
            [project.id for project in content.projects],
            ["intelligent-motion", "vision-lab"],
        )

    @patch("Admin.landing.project_catalog.find_one", new_callable=AsyncMock)
    async def test_featured_public_projects_are_shown_first(self, find_one):
        document = deepcopy(DEFAULT_PROJECT_CATALOG)
        document["projects"][0]["display_order"] = 99
        find_one.return_value = document

        content = await get_public_project_catalog()

        self.assertEqual(content.projects[0].id, "basic-chat")

    @patch("Admin.landing.project_catalog.find_one", new_callable=AsyncMock)
    async def test_workspace_catalog_has_independent_visibility(self, find_one):
        document = deepcopy(DEFAULT_PROJECT_CATALOG)
        document["projects"][0]["show_public"] = False
        document["projects"][1]["show_workspace"] = False
        find_one.return_value = document

        projects = await get_workspace_projects()

        self.assertIn("basic-chat", [project.id for project in projects])
        self.assertNotIn("vision-lab", [project.id for project in projects])

    @patch("Admin.landing.landing_content.find_one", new_callable=AsyncMock)
    @patch("Admin.landing.project_catalog.find_one", new_callable=AsyncMock)
    async def test_legacy_landing_projects_are_migrated(self, catalog_find, landing_find):
        catalog_find.return_value = None
        landing_find.return_value = {
            "portfolio_nav_label": "Work",
            "portfolio_projects": deepcopy(DEFAULT_PROJECT_CATALOG["projects"]),
        }
        content = await get_project_catalog()
        self.assertEqual(content.nav_label, "Work")
        self.assertTrue(content.projects)

    def test_portfolio_project_ids_must_be_unique(self):
        document = deepcopy(DEFAULT_PROJECT_CATALOG)
        document["projects"].append(deepcopy(document["projects"][0]))
        with self.assertRaises(ValidationError):
            ProjectCatalog(**document)

    @patch("Admin.landing.landing_content.replace_one", new_callable=AsyncMock)
    async def test_admin_save_uses_singleton_upsert(self, replace_one):
        content = LandingContent(**DEFAULT_LANDING_CONTENT)
        await save_landing_content(content, "admin-id")
        query, document = replace_one.await_args.args
        self.assertEqual(query, {"_id": "default"})
        self.assertEqual(document["updated_by"], "admin-id")
        self.assertTrue(replace_one.await_args.kwargs["upsert"])


class CloudinaryStorageTests(unittest.IsolatedAsyncioTestCase):
    @patch("Authentication.cloudinary_storage.settings.cloudinary_api_key", "")
    def test_missing_configuration_names_the_api_key(self):
        self.assertEqual(configuration_error(), "Cloudinary is missing: CLOUDINARY_API_KEY")

    @patch(
        "Authentication.cloudinary_storage.cloudinary.uploader.destroy",
        return_value={"result": "ok"},
    )
    async def test_previous_profile_picture_is_deleted(self, destroy):
        await delete_profile_picture("veeragenai/profile-pictures/old-picture")
        destroy.assert_called_once_with(
            "veeragenai/profile-pictures/old-picture", resource_type="image", invalidate=True
        )

    @patch("Authentication.cloudinary_storage.is_configured", return_value=True)
    @patch(
        "Authentication.cloudinary_storage._upload",
        return_value={"secure_url": "https://res.cloudinary.com/demo/project.webp"},
    )
    async def test_project_image_uses_project_folder(self, upload, _):
        result = await upload_project_image(b"image", "basic-chat")
        self.assertEqual(result["image_url"], "https://res.cloudinary.com/demo/project.webp")
        self.assertEqual(upload.call_args.args[2], settings.cloudinary_project_folder)


class PasswordResetTests(unittest.IsolatedAsyncioTestCase):
    @patch("Authentication.router.users.update_one", new_callable=AsyncMock)
    @patch("Authentication.router.users.find_one", new_callable=AsyncMock)
    async def test_reset_replaces_password_and_consumes_otp(self, find_one, update_one):
        find_one.return_value = {
            "_id": "user-id",
            "password_reset_otp": hash_otp("123456"),
            "password_reset_expires": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        await reset_password(
            ResetPasswordRequest(
                email="user@gmail.com", otp="123456", new_password="newpassword123"
            )
        )
        changes = update_one.await_args.args[1]
        self.assertTrue(password_hash.verify("newpassword123", changes["$set"]["password_hash"]))
        self.assertEqual(
            changes["$unset"], {"password_reset_otp": "", "password_reset_expires": ""}
        )


if __name__ == "__main__":
    unittest.main()