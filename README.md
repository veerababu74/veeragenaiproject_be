# Veera Generative AI API

FastAPI backend for Veera AI authentication, project catalog, Basic Chat, Basic RAG, and Google Workspace Agent.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Copy `.env.example` to `.env` and configure the provider credentials before starting. See [DEPLOYMENT.md](DEPLOYMENT.md) for Render, Vercel, demo-account, and Google OAuth setup.
