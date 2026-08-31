import unittest
from unittest.mock import AsyncMock, Mock, patch

from bson import ObjectId

from pydantic import ValidationError

from Blog.models import BlogPost, BlogPostUpdate
from Blog.project_guides import PROJECT_GUIDES
from Blog.router import _public_blog_filter, update_blog


class BlogModelTests(unittest.TestCase):
    def test_built_in_project_guides_are_valid_and_unique(self):
        posts = [BlogPost(**guide) for guide in PROJECT_GUIDES]

        self.assertEqual(
            {post.project_id for post in posts},
            {"basic-chat", "basic-rag", "advanced-rag", "google-workspace-agent", "chunking-lab", "graph-rag"},
        )
        self.assertEqual(len({post.slug for post in posts}), len(PROJECT_GUIDES))
        self.assertTrue(all(post.published for post in posts))
        self.assertTrue(all(any(block.type == "mermaid" for block in post.blocks) for post in posts))

    def test_create_validates_structured_blocks(self):
        with self.assertRaises(ValidationError):
            BlogPost(
                slug="broken-diagram",
                title="Broken diagram",
                description="This payload is missing Mermaid content.",
                blocks=[{"type": "mermaid"}],
            )

    def test_update_applies_image_and_tag_validation(self):
        with self.assertRaises(ValidationError):
            BlogPostUpdate(cover_image_url="http://example.com/image.png")

        update = BlogPostUpdate(tags=[" RAG ", "RAG", "FastAPI"])
        self.assertEqual(update.tags, ["RAG", "FastAPI"])


class BlogRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_public_search_is_case_insensitive_and_escapes_regex(self):
        query = _public_blog_filter("RAG.*")

        self.assertTrue(query["published"])
        self.assertEqual(query["$or"][0]["title"]["$regex"], r"RAG\.\*")
        self.assertEqual(query["$or"][2]["tags"]["$options"], "i")

    async def test_update_can_unlink_project_and_catalog(self):
        existing = {
            "slug": "basic-rag-guide", "title": "Basic RAG", "description": "Guide",
            "cover_image_url": "", "cover_image_alt": "", "tags": [],
            "project_id": "basic-rag", "published": True, "blocks": [],
        }
        collection = Mock()
        collection.find_one = AsyncMock(return_value=existing)
        collection.find_one_and_update = AsyncMock(return_value={**existing, "project_id": None})

        with patch("Blog.router._blogs", return_value=collection), \
             patch("Blog.router._sync_project_link", new_callable=AsyncMock) as sync_link:
            result = await update_blog(
                "basic-rag-guide", BlogPostUpdate(project_id=None), {"_id": ObjectId()}
            )

        changes = collection.find_one_and_update.await_args.args[1]["$set"]
        self.assertIn("project_id", changes)
        self.assertIsNone(changes["project_id"])
        self.assertIsNone(result["project_id"])
        sync_link.assert_awaited_once_with("basic-rag", None, "basic-rag-guide")


if __name__ == "__main__":
    unittest.main()