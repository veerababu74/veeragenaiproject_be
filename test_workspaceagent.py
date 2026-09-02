import importlib
import sys
import types
import unittest
import weakref
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from oauthlib.oauth2 import InvalidClientError, InvalidGrantError

from workspaceagent.agent import run_agent
from workspaceagent.models import ConfirmRequest
import workspaceagent.providers as providers
from workspaceagent.oauth import (
    GoogleConnectionError,
    authorization_url,
    create_state,
    decrypt_token,
    encrypt_token,
    exchange_code,
    read_state,
    read_state_payload,
    refresh_access_token,
)
from workspaceagent.providers import _provider_error, tool_plan
from workspaceagent.router import confirm_action


class WorkspaceAgentSecurityTests(unittest.TestCase):
    def test_refresh_token_is_encrypted_at_rest(self):
        encrypted = encrypt_token("refresh-secret", "test-jwt-secret")

        self.assertNotIn("refresh-secret", encrypted)
        self.assertEqual(decrypt_token(encrypted, "test-jwt-secret"), "refresh-secret")

    def test_oauth_state_is_user_bound_and_rejects_tampering(self):
        state = create_state("user-1", "test-jwt-secret", "https://veeragenai.netlify.app")

        self.assertEqual(read_state(state, "test-jwt-secret"), "user-1")
        self.assertEqual(
            read_state_payload(state, "test-jwt-secret")["return_url"],
            "https://veeragenai.netlify.app",
        )
        with self.assertRaises(GoogleConnectionError):
            read_state(f"x{state[1:]}", "test-jwt-secret")

    def test_authorization_avoids_unpersisted_pkce_and_historical_scopes(self):
        url = authorization_url("client-id", "client-secret", "http://localhost/callback", "state")
        query = parse_qs(urlparse(url).query)

        self.assertNotIn("code_challenge", query)
        self.assertNotIn("include_granted_scopes", query)

    def test_exchange_reports_rejected_client_credentials(self):
        flow = Mock()
        flow.fetch_token.side_effect = InvalidClientError()
        with patch("workspaceagent.oauth._flow", return_value=flow):
            with self.assertRaisesRegex(GoogleConnectionError, "rejected the OAuth client credentials"):
                exchange_code("code", "client-id", "client-secret", "http://localhost/callback")

    def test_exchange_reports_expired_authorization_code(self):
        flow = Mock()
        flow.fetch_token.side_effect = InvalidGrantError()
        with patch("workspaceagent.oauth._flow", return_value=flow):
            with self.assertRaisesRegex(GoogleConnectionError, "authorization code expired"):
                exchange_code("code", "client-id", "client-secret", "http://localhost/callback")

    def test_exchange_accepts_google_email_scope_alias(self):
        warning = Warning("Scope has changed")
        warning.old_scope = ["openid", "email", "gmail", "calendar"]
        warning.new_scope = [
            "openid", "email", "https://www.googleapis.com/auth/userinfo.email", "gmail", "calendar",
        ]
        warning.token = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": warning.new_scope,
        }
        flow = Mock()
        flow.fetch_token.side_effect = warning
        with patch("workspaceagent.oauth._flow", return_value=flow):
            result = exchange_code("code", "client-id", "client-secret", "http://localhost/callback")

        self.assertEqual(result["refresh_token"], "refresh-token")

    def test_exchange_rejects_a_real_scope_change(self):
        warning = Warning("Scope has changed")
        warning.old_scope = ["openid", "email", "gmail", "calendar"]
        warning.new_scope = ["openid", "email", "gmail"]
        warning.token = {"access_token": "access-token", "refresh_token": "refresh-token"}
        flow = Mock()
        flow.fetch_token.side_effect = warning
        with patch("workspaceagent.oauth._flow", return_value=flow):
            with self.assertRaisesRegex(GoogleConnectionError, "unexpected set of permissions"):
                exchange_code("code", "client-id", "client-secret", "http://localhost/callback")

    @patch("workspaceagent.oauth.Credentials")
    def test_refresh_uses_google_email_scope_alias(self, credentials):
        credentials.return_value.token = "access-token"

        self.assertEqual(refresh_access_token("refresh-token", "client-id", "client-secret"), "access-token")

        scopes = credentials.call_args.kwargs["scopes"]
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", scopes)
        self.assertNotIn("email", scopes)


class WorkspaceAgentPlanningTests(unittest.TestCase):
    def test_provider_module_import_does_not_require_mistral_client(self):
        with patch.dict(sys.modules, {"mistralai": types.ModuleType("mistralai")}):
            importlib.reload(providers)

    def test_gemini_sdk_error_code_is_actionable(self):
        error = Exception("provider details")
        error.code = 404

        result = _provider_error("gemini", error)

        self.assertEqual(str(result), "Google Gemini could not find that model. Check the model ID.")

        error.code = 400
        error.message = "API key not valid"
        result = _provider_error("gemini", error)
        self.assertEqual(str(result), "Google Gemini rejected the API key. Check the key and its permissions.")

    def test_gemini_client_stays_alive_during_request(self):
        class Models:
            def __init__(self, client):
                self.client = weakref.ref(client)

            def generate_content(self, **_):
                if self.client() is None:
                    raise RuntimeError("client closed")
                return Mock(function_calls=[], text="Ready")

        class Client:
            def __init__(self, **_):
                self.models = Models(self)

        with patch("workspaceagent.providers.genai.Client", side_effect=Client):
            result = tool_plan("gemini", "api-key", "gemini-test", "system", "Hello")

        self.assertEqual(result, {"action": "answer", "arguments": {"response": "Ready"}})

    def test_calendar_create_requires_confirmation_before_google_call(self):
        llm = Mock(return_value='''{
            "action":"calendar_create",
            "arguments":{"summary":"Design review","start":"2026-09-01T10:00:00+05:30","end":"2026-09-01T10:30:00+05:30"},
            "explanation":"Block 30 minutes for the design review."
        }''')
        google = Mock()

        result = run_agent("Book a design review", [], "gemini", "api-key", "model", google, llm)

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["pending_action"]["action"], "calendar_create")
        google.create_event.assert_not_called()

    def test_calendar_delete_resolves_event_before_confirmation(self):
        llm = Mock(return_value='''{
            "action":"calendar_delete",
            "arguments":{"query":"Design review"},
            "explanation":"Remove the design review."
        }''')
        google = Mock()
        google.list_events.return_value = [{"id": "event-1", "summary": "Design review", "start": "2026-09-01T10:00:00+05:30"}]

        result = run_agent("Remove my design review", [], "gemini", "api-key", "model", google, llm)

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["pending_action"]["arguments"]["event_id"], "event-1")
        google.delete_event.assert_not_called()

    @patch("workspaceagent.providers._openai_client")
    def test_openai_native_tool_call_is_normalized(self, client):
        function = Mock(name="function")
        function.name = "gmail_search"
        function.arguments = '{"query":"from:billing","max_results":5}'
        message = Mock(tool_calls=[Mock(function=function)], content=None)
        client.return_value.chat.completions.create.return_value = Mock(choices=[Mock(message=message)])

        plan = tool_plan("openai", "api-key", "gpt-test", "system", "Find billing mail")

        self.assertEqual(plan, {"action": "gmail_search", "arguments": {"query": "from:billing", "max_results": 5}})
        request = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request["tool_choice"], "auto")
        self.assertEqual(request["tools"][0]["type"], "function")

    @patch("workspaceagent.providers.genai.Client")
    def test_gemini_native_tool_call_is_normalized(self, client):
        function_call = Mock(args={"query": "planning"})
        function_call.name = "calendar_list"
        client.return_value.models.generate_content.return_value = Mock(
            function_calls=[function_call]
        )

        plan = tool_plan("gemini", "api-key", "models/gemini-test", "system", "Find planning events")

        self.assertEqual(plan, {"action": "calendar_list", "arguments": {"query": "planning"}})
        self.assertEqual(client.return_value.models.generate_content.call_args.kwargs["model"], "gemini-test")

    @patch("workspaceagent.providers._mistral_client")
    @patch("workspaceagent.providers.Groq")
    def test_mistral_and_groq_native_tool_calls_are_normalized(self, groq, mistral):
        function = Mock(name="function")
        function.name = "gmail_important"
        function.arguments = {"query": "is:important"}
        response = Mock(choices=[Mock(message=Mock(tool_calls=[Mock(function=function)], content=None))])
        mistral.return_value.chat.complete.return_value = response
        groq.return_value.chat.completions.create.return_value = response

        for provider in ("mistral", "groq"):
            with self.subTest(provider=provider):
                self.assertEqual(
                    tool_plan(provider, "api-key", "model", "system", "Important mail"),
                    {"action": "gmail_important", "arguments": {"query": "is:important"}},
                )


class WorkspaceAgentConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_releases_claimed_action(self):
        claim = {"session_id": "session-1", "action": {"action": "calendar_delete", "arguments": {"event_id": "event-1"}}}
        with patch("workspaceagent.router.database.claim_action", return_value=claim), \
             patch("workspaceagent.router.database.release_action") as release_action, \
             patch("workspaceagent.router._workspace", new=AsyncMock(side_effect=HTTPException(status_code=409, detail="Connect first"))):
            with self.assertRaises(HTTPException):
                await confirm_action(ConfirmRequest(message_id=1), user_id="user-1")

            release_action.assert_called_once_with(1, "user-1")


if __name__ == "__main__":
    unittest.main()
