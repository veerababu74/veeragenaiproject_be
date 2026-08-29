# Production deployment

The frontend and FastAPI backend are deployed as separate Vercel applications:

- Frontend: `https://veeragenaiproject-fe.vercel.app`
- Backend: `https://veeragenaiproject-be.vercel.app`

## Vercel backend

1. Import `veerababu74/veeragenaiproject_be` as a Python project.
2. Import the local backend `.env` under **Environment Variables**. It is intentionally ignored by Git.
3. Set `FRONTEND_URL=https://veeragenaiproject-fe.vercel.app`.
4. Set `GOOGLE_WORKSPACE_REDIRECT_URI=https://veeragenaiproject-be.vercel.app/workspace-agent/google/callback`.
5. Set `DATA_DIR=/tmp/veeragenai`, deploy, and verify `https://veeragenaiproject-be.vercel.app/health` returns `{"status":"ok"}`.

Vercel only permits runtime writes under `/tmp`. Basic Chat, Basic RAG, Advanced RAG, and Workspace Agent SQLite data may disappear after a cold start or run on different instances. For durable sessions, deploy this same backend to Render with `render.yaml`, or migrate those repositories to MongoDB/Postgres.

The configured demo account is `demo@veeragenai.com` with password `VeeraDemo@2026`. It is intentionally public and must never be reused for another account.

## Vercel frontend

1. Import `veerababu74/veeragenaiproject_fe` into Vercel.
2. Keep the root directory at the repository root, framework preset **Vite**, build command `npm run build`, and output directory `dist`.
3. The tracked `.env.production` sets `VITE_API_URL=/api` and public demo values.
4. `vercel.json` proxies `/api/*` to the separate backend application, keeping authentication cookies first-party.
5. Deploy and verify the login and demo-account flow.

## Google Cloud

Enable Gmail API and Google Calendar API. Configure an External OAuth consent screen with `openid`, `email`, `profile`, Gmail read-only, and Calendar events scopes.

Authorized JavaScript origins:

```text
http://localhost:5173
https://veeragenaiproject-fe.vercel.app
```

Authorized redirect URIs:

```text
http://localhost:8000/workspace-agent/google/callback
https://veeragenaiproject-be.vercel.app/workspace-agent/google/callback
```

Add real Google accounts under **Audience > Test users** while the OAuth application is in Testing. Gmail scopes may require Google verification before public launch.

Rotate all provider credentials that were previously shared or exposed before production deployment.
