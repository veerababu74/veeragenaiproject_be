from contextlib import asynccontextmanager
import logging
import os
from time import perf_counter

from bson import ObjectId
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from Authentication.config import settings
from Authentication.database import close_database, users
from Authentication.router import router as authentication_router
from Authentication.security import decode_access_token, password_hash
from Admin.router import public_router as landing_router, router as admin_router
from Admin.landing import ensure_advanced_rag_project, ensure_basic_rag_project, ensure_google_workspace_agent_project, migrate_project_catalog
from advancedragapp import database as advanced_rag_database
from advancedragapp.router import router as advanced_rag_router
from basichatapp import database as basic_chat_database
from basichatapp.router import router as basic_chat_router
from basicragapp import database as basic_rag_database
from basicragapp.router import router as basic_rag_router
from workspaceagent import database as workspace_agent_database
from workspaceagent.router import router as workspace_agent_router


logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("veera.api")


async def initialize_mongodb():
	logger.info("Connecting to MongoDB | running startup migrations")
	await users.create_index("email", unique=True)
	await users.update_many({"role": {"$exists": False}}, {"$set": {"role": "user"}})
	await users.update_many({"is_active": {"$exists": False}}, {"$set": {"is_active": True}})
	await users.update_many({"blocked_projects": {"$exists": False}}, {"$set": {"blocked_projects": []}})
	await users.update_many({"project_access": {"$exists": True}}, {"$unset": {"project_access": ""}})
	if settings.demo_enabled:
		demo_email = settings.demo_email.strip().lower()
		demo = await users.find_one({"email": demo_email})
		if demo and demo.get("role") != "demo":
			logger.warning("Demo account not provisioned: DEMO_EMAIL belongs to a regular user")
		else:
			password_changed = not demo
			if demo:
				try:
					password_changed = not password_hash.verify(settings.demo_password, demo.get("password_hash", ""))
				except Exception:
					password_changed = True
			changes = {
				"name": "Veera AI Demo",
				"email": demo_email,
				"provider": "email",
				"is_verified": True,
				"role": "demo",
				"is_active": True,
				"blocked_projects": [],
			}
			if password_changed:
				changes["password_hash"] = password_hash.hash(settings.demo_password)
			await users.update_one({"email": demo_email}, {"$set": changes}, upsert=True)
	await migrate_project_catalog()
	await ensure_basic_rag_project()
	await ensure_advanced_rag_project()
	await ensure_google_workspace_agent_project()
	if settings.admin_email_set:
		await users.update_many(
			{"role": "admin", "email": {"$nin": list(settings.admin_email_set)}},
			{"$set": {"role": "user"}},
		)
		await users.update_many(
			{"email": {"$in": list(settings.admin_email_set)}, "role": {"$ne": "demo"}},
			{"$set": {"role": "admin"}},
		)
	logger.info("MongoDB startup migrations complete")


@asynccontextmanager
async def lifespan(_: FastAPI):
	logger.info(
		"Starting API | frontend=%s | huggingface=%s | pinecone=%s",
		settings.frontend_url,
		"configured" if settings.huggingface_token else "missing",
		"configured" if settings.pinecone_api_key else "missing",
	)
	basic_chat_database.initialize()
	basic_chat_database.cleanup_expired()
	basic_rag_database.initialize()
	advanced_rag_database.initialize()
	workspace_agent_database.initialize()
	logger.info("SQLite startup complete")
	if os.getenv("VERCEL"):
		logger.info("Skipping MongoDB migrations during Vercel cold start")
	else:
		await initialize_mongodb()
	logger.info("API startup complete")
	yield
	logger.info("Shutting down API")
	await close_database()


app = FastAPI(title="Veera Generative AI API", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, error: RequestValidationError):
	issues = ", ".join(f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}" for issue in error.errors())
	logger.warning("%s %s validation failed | %s", request.method, request.url.path, issues)
	return await request_validation_exception_handler(request, error)


@app.exception_handler(PyMongoError)
async def mongodb_unavailable(request: Request, error: PyMongoError):
	logger.error("%s %s database unavailable | %s", request.method, request.url.path, error)
	return JSONResponse(status_code=503, content={"detail": "Database is temporarily unavailable"})


@app.middleware("http")
async def log_request(request: Request, call_next):
	started = perf_counter()
	if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path not in {
		"/auth/login", "/auth/register", "/auth/google", "/auth/logout"
	}:
		user_id = decode_access_token(request.cookies.get("access_token"))
		if user_id and ObjectId.is_valid(user_id):
			user = await users.find_one({"_id": ObjectId(user_id)}, {"role": 1})
			if user and user.get("role") == "demo":
				return JSONResponse(
					status_code=403,
					content={"detail": "Create an account or sign in with Google to interact with projects"},
				)
	try:
		response = await call_next(request)
	except Exception:
		logger.exception("%s %s failed", request.method, request.url.path)
		raise
	logger.info(
		"%s %s -> %s | %.1f ms",
		request.method,
		request.url.path,
		response.status_code,
		(perf_counter() - started) * 1000,
	)
	return response


allowed_origins = {settings.frontend_url}
if "localhost" in settings.frontend_url:
	allowed_origins.add(settings.frontend_url.replace("localhost", "127.0.0.1"))
app.add_middleware(
	CORSMiddleware,
	allow_origins=list(allowed_origins),
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)
app.include_router(authentication_router)
app.include_router(landing_router)
app.include_router(admin_router)
app.include_router(basic_chat_router)
app.include_router(basic_rag_router)
app.include_router(advanced_rag_router)
app.include_router(workspace_agent_router)


@app.get("/health")
async def health():
	return {"status": "ok"}



if __name__ =="__main__":
	import uvicorn
	uvicorn.run("main:app", reload=True)