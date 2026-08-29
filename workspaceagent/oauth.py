import base64
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
import requests
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES = [
    "openid", "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]
EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
REFRESH_SCOPES = [EMAIL_SCOPE if scope == "email" else scope for scope in SCOPES]


class GoogleConnectionError(Exception):
    pass


def _fernet(secret):
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_token(token, secret):
    return _fernet(secret).encrypt(token.encode()).decode()


def decrypt_token(token, secret):
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise GoogleConnectionError("Stored Google credentials could not be decrypted") from error


def create_state(user_id, secret):
    return jwt.encode(
        {"sub": user_id, "purpose": "google-workspace-link", "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
        secret,
        algorithm="HS256",
    )


def read_state(state, secret):
    try:
        payload = jwt.decode(state, secret, algorithms=["HS256"])
        if payload.get("purpose") != "google-workspace-link":
            raise GoogleConnectionError("Invalid Google authorization state")
        return payload["sub"]
    except (jwt.InvalidTokenError, KeyError) as error:
        raise GoogleConnectionError("Google authorization expired or is invalid") from error


def _flow(client_id, client_secret, redirect_uri, state=None):
    flow = Flow.from_client_config(
        {"web": {"client_id": client_id, "client_secret": client_secret, "auth_uri": AUTH_URL, "token_uri": TOKEN_URL}},
        scopes=SCOPES,
        state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    return flow


def authorization_url(client_id, client_secret, redirect_uri, state):
    url, _ = _flow(client_id, client_secret, redirect_uri, state).authorization_url(
        access_type="offline", prompt="consent"
    )
    return url


def _exchange_error_message(error):
    oauth_error = getattr(error, "error", "")
    if oauth_error == "invalid_client":
        return "Google rejected the OAuth client credentials. Verify the client ID and secret belong to the same Web application, then restart the backend."
    if oauth_error == "invalid_grant":
        return "The Google authorization code expired or was already used. Start Connect Gmail + Calendar again."
    if oauth_error == "redirect_uri_mismatch":
        return "Google rejected the callback URL. Add the exact backend redirect URI to the OAuth Web client."
    if oauth_error == "invalid_scope":
        return "Google rejected a required Gmail or Calendar scope. Check the OAuth consent screen data-access scopes."
    return "Google authorization could not be completed. Start the connection again and check the backend log if it fails."


def _scope_warning_token(error):
    normalize = lambda scopes: {EMAIL_SCOPE if scope == "email" else scope for scope in scopes}
    token = getattr(error, "token", None)
    if token and normalize(getattr(error, "old_scope", [])) == normalize(getattr(error, "new_scope", [])):
        return token
    raise GoogleConnectionError("Google returned an unexpected set of permissions. Start the connection again and approve every requested permission.") from error


def exchange_code(code, client_id, client_secret, redirect_uri):
    try:
        flow = _flow(client_id, client_secret, redirect_uri)
        token = flow.fetch_token(code=code)
    except Warning as error:
        token = _scope_warning_token(error)
    except OAuth2Error as error:
        raise GoogleConnectionError(_exchange_error_message(error)) from error
    except Exception as error:
        raise GoogleConnectionError(_exchange_error_message(error)) from error
    if not token.get("refresh_token"):
        raise GoogleConnectionError("Google did not return offline access. Unlink and approve access again.")
    scope = token.get("scope") or SCOPES
    return {
        "access_token": token["access_token"],
        "refresh_token": token["refresh_token"],
        "scope": scope if isinstance(scope, str) else " ".join(scope),
    }


def google_email(access_token):
    response = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=(10, 30))
    if not response.ok:
        raise GoogleConnectionError("Could not read the connected Google account")
    return response.json().get("email")


def refresh_access_token(refresh_token, client_id, client_secret):
    credentials = Credentials(
        token=None, refresh_token=refresh_token, token_uri=TOKEN_URL,
        client_id=client_id, client_secret=client_secret, scopes=REFRESH_SCOPES,
    )
    try:
        credentials.refresh(GoogleRequest())
    except Exception as error:
        raise GoogleConnectionError("Google access expired. Unlink and reconnect your account.") from error
    if not credentials.token:
        raise GoogleConnectionError("Google access expired. Unlink and reconnect your account.")
    return credentials.token


def revoke(refresh_token):
    requests.post(REVOKE_URL, data={"token": refresh_token}, timeout=(10, 30))
