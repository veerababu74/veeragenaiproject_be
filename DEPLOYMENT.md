# Production deployment

Deploy this FastAPI repository to Render and the separate frontend repository to Vercel. The backend requires a persistent disk because project sessions use SQLite.

## Render backend

1. In Render, create a Blueprint from this repository. `render.yaml` defines the service and persistent `/var/data` disk.
2. Under the service environment, use **Add from .env** and import the local `.env` file. It is intentionally ignored by Git.
3. Confirm `FRONTEND_URL` is the exact Vercel origin without a trailing slash.
4. Confirm `GOOGLE_WORKSPACE_REDIRECT_URI` is the exact Render URL plus `/workspace-agent/google/callback`.
5. Deploy and verify `https://<render-host>/health` returns `{"status":"ok"}`.

The configured demo account is `demo@veeragenai.com` with password `VeeraDemo@2026`. It is intentionally public and must never be reused for another account.

## Vercel frontend

1. Import `veerababu74/veeragenaiproject_fe` into Vercel.
2. Keep the root directory at the repository root, framework preset **Vite**, build command `npm run build`, and output directory `dist`.
3. Import that repository's local `.env` under **Environment Variables** for Production.
4. Confirm `VITE_API_URL` matches the Render service URL, then deploy.

## Google Cloud

Enable Gmail API and Google Calendar API. Configure an External OAuth consent screen with `openid`, `email`, `profile`, Gmail read-only, and Calendar events scopes.

Authorized JavaScript origins:

```text
http://localhost:5173
https://veera-ai.vercel.app
```

Authorized redirect URIs:

```text
http://localhost:8000/workspace-agent/google/callback
https://veera-ai-api.onrender.com/workspace-agent/google/callback
```

Replace either production URL if the provider assigns a different hostname. Add real Google accounts under **Audience > Test users** while the OAuth application is in Testing. Gmail scopes may require Google verification before public launch.

Rotate all provider credentials that were previously shared or exposed before production deployment.
