import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from basichatapp.database import (
    add_exchange,
    cleanup_expired,
    create_session,
    get_messages,
    get_session,
    initialize,
    list_sessions,
    update_session_title,
)
from basichatapp.providers import OPENAI_COMPATIBLE_URLS, ProviderError, _post, chat
from basichatapp.router import chat_user_id


class BasicChatDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "chat.db"
        initialize(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_retains_only_ten_exchanges_and_never_has_api_key_column(self):
        session = create_session("user-1", "openai", "gpt-test", "First", self.database_path)
        for number in range(12):
            add_exchange(session["id"], "user-1", f"user-{number}", f"assistant-{number}", self.database_path)
        messages = get_messages(session["id"], self.database_path)
        self.assertEqual(len(messages), 20)
        self.assertEqual(messages[0]["content"], "user-2")
        with closing(sqlite3.connect(self.database_path)) as connection:
            columns = {
                row[1]
                for table in ("sessions", "messages")
                for row in connection.execute(f"PRAGMA table_info({table})")
            }
        self.assertNotIn("api_key", columns)

    def test_cleanup_removes_sessions_after_24_hours_without_interaction(self):
        with patch("basichatapp.database.time.time", return_value=100):
            session = create_session("user-1", "gemini", "gemini-test", "First", self.database_path)
        with patch("basichatapp.database.time.time", return_value=1000):
            renewed_expiry = add_exchange(session["id"], "user-1", "hello", "hi", self.database_path)

        self.assertEqual(renewed_expiry, 1000 + 24 * 60 * 60)
        cleanup_expired(self.database_path, now=renewed_expiry - 1)
        self.assertEqual(len(get_messages(session["id"], self.database_path)), 2)
        cleanup_expired(self.database_path, now=renewed_expiry)
        self.assertEqual(get_messages(session["id"], self.database_path), [])

    def test_expired_session_cannot_be_opened_directly(self):
        with patch("basichatapp.database.time.time", return_value=100):
            session = create_session("user-1", "gemini", "gemini-test", "First", self.database_path)
        with patch("basichatapp.database.time.time", return_value=100 + 24 * 60 * 60):
            self.assertIsNone(get_session(session["id"], "user-1", self.database_path))

    def test_initialize_migrates_legacy_expiry_from_latest_interaction(self):
        with patch("basichatapp.database.time.time", return_value=100):
            session = create_session("user-1", "openai", "gpt-test", "First", self.database_path)
        with patch("basichatapp.database.time.time", return_value=1000):
            add_exchange(session["id"], "user-1", "hello", "hi", self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = ? WHERE id = ?",
                (session["expires_at"], session["id"]),
            )
            connection.commit()

        initialize(self.database_path)

        with closing(sqlite3.connect(self.database_path)) as connection:
            expires_at = connection.execute(
                "SELECT expires_at FROM sessions WHERE id = ?", (session["id"],)
            ).fetchone()[0]
        self.assertEqual(expires_at, 1000 + 24 * 60 * 60)

    def test_new_sessions_are_listed_newest_first_and_receive_first_message_title(self):
        first = create_session("user-1", "groq", "model", "New chat", self.database_path)
        second = create_session("user-1", "groq", "model", "New chat", self.database_path)

        sessions = list_sessions("user-1", self.database_path)
        self.assertEqual([session["id"] for session in sessions], [second["id"], first["id"]])

        title = update_session_title(second["id"], "user-1", "My first question\ncontinued", self.database_path)
        self.assertEqual(title, "My first question continued")
        self.assertEqual(list_sessions("user-1", self.database_path)[0]["title"], title)


class BasicChatProviderTests(unittest.TestCase):
    @patch("basichatapp.providers._post")
    def test_gemini_uses_key_header_and_maps_assistant_history(self, post):
        post.return_value = {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]}
        answer = chat(
            "gemini",
            "secret-api-key",
            "gemini-test",
            [{"role": "assistant", "content": "previous"}, {"role": "user", "content": "next"}],
        )
        url, headers, payload, _ = post.call_args.args
        self.assertEqual(answer, "answer")
        self.assertNotIn("secret-api-key", url)
        self.assertEqual(headers["x-goog-api-key"], "secret-api-key")
        self.assertEqual(payload["contents"][0]["role"], "model")

    @patch("basichatapp.providers._post")
    def test_gemini_accepts_models_prefix(self, post):
        post.return_value = {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]}
        chat("gemini", "secret-api-key", "models/gemini-flash-latest", [{"role": "user", "content": "hi"}])
        self.assertIn("/models/gemini-flash-latest:generateContent", post.call_args.args[0])

    @patch("basichatapp.providers._post")
    def test_openai_compatible_providers_send_bearer_chat_requests(self, post):
        post.return_value = {"choices": [{"message": {"content": "answer"}}]}
        messages = [{"role": "user", "content": "hello"}]
        models = {
            "openai": "gpt-4o",
            "mistral": "mistral-large-latest",
            "groq": "openai/gpt-oss-120b",
            "openrouter": "openai/gpt-4o",
        }
        for provider, model in models.items():
            with self.subTest(provider=provider):
                chat(provider, "secret-api-key", model, messages)
                url, headers, payload, sent_provider = post.call_args.args
                self.assertEqual(url, OPENAI_COMPATIBLE_URLS[provider])
                self.assertEqual(headers["Authorization"], "Bearer secret-api-key")
                self.assertEqual(payload, {"model": model, "messages": messages})
                self.assertEqual(sent_provider, provider)

    @patch("basichatapp.providers.requests.post")
    def test_provider_errors_are_actionable_without_exposing_response_body(self, post):
        post.return_value.ok = False
        post.return_value.status_code = 401
        post.return_value.text = "secret upstream response"
        with self.assertRaisesRegex(ProviderError, "GroqCloud rejected the API key") as raised:
            _post("https://example.test", {}, {}, "groq")
        self.assertNotIn("secret upstream response", str(raised.exception))


class BasicChatAccessTests(unittest.IsolatedAsyncioTestCase):
    @patch("basichatapp.router.users.find_one", new_callable=AsyncMock)
    async def test_regular_user_has_default_access_unless_project_is_blocked(self, find_one):
        user_id = "507f1f77bcf86cd799439011"
        find_one.return_value = {"role": "user", "blocked_projects": []}
        self.assertEqual(await chat_user_id(user_id), user_id)

        find_one.return_value = {"role": "user", "blocked_projects": ["basic-chat"]}
        with self.assertRaises(HTTPException) as raised:
            await chat_user_id(user_id)
        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()