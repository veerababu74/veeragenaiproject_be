from datetime import datetime, timezone
import logging

from pymongo.errors import PyMongoError

from Authentication.database import landing_content, project_catalog

from .models import LandingContent, ProjectCatalog


logger = logging.getLogger("veera.landing")


DEFAULT_PROJECT_CATALOG = {
    "nav_label": "Projects",
    "eyebrow": "SELECTED PORTFOLIO",
    "title": "Working projects at the intersection of code and engineering",
    "description": "A growing collection of practical AI products, machine-learning experiments, and intelligent systems built to solve real problems.",
    "projects": [
        {
            "id": "basic-chat", "title": "Multi-provider Basic Chat",
            "summary": "A private conversational workspace that connects OpenAI, Gemini, Mistral, GroqCloud, and OpenRouter without storing provider keys.",
            "category": "Generative AI", "tags": ["FastAPI", "React", "LLM", "SQLite"],
            "image_url": "https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&w=1400&q=85",
            "image_alt": "Abstract artificial intelligence interface", "status": "available",
            "featured": True, "show_public": True, "show_workspace": True, "display_order": 1,
            "project_url": "#signin",
        },
        {
            "id": "vision-lab", "title": "Machine Vision Lab",
            "summary": "An inspection workspace for exploring image understanding, component recognition, and visual quality workflows.",
            "category": "Machine Learning", "tags": ["Computer Vision", "Multimodal", "Inspection"],
            "image_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=85",
            "image_alt": "Electronic circuit board used for machine vision experiments", "status": "coming-soon",
            "featured": False, "show_public": True, "show_workspace": True, "display_order": 2,
            "project_url": "#roadmap",
        },
        {
            "id": "intelligent-motion", "title": "Intelligent Motion Study",
            "summary": "A mechatronics concept for connecting sensing, control logic, and AI-assisted decisions around robotic movement.",
            "category": "Mechatronics", "tags": ["Robotics", "Control", "Sensors"],
            "image_url": "https://images.unsplash.com/photo-1561144257-e32e8efc6c4f?auto=format&fit=crop&w=1400&q=85",
            "image_alt": "Robotic arms in an automated engineering facility", "status": "beta",
            "featured": False, "show_public": True, "show_workspace": True, "display_order": 3,
            "project_url": "#roadmap",
        },
    ],
}

BASIC_RAG_PROJECT = {
    "id": "basic-rag", "title": "Document-grounded Basic RAG",
    "summary": "Upload private documents, compare chunking strategies, and ask grounded questions across leading LLM providers.",
    "category": "Generative AI", "tags": ["RAG", "Gemini", "Pinecone", "Hugging Face"],
    "image_url": "https://images.unsplash.com/photo-1456324504439-367cee3b3c32?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Open documents and a laptop on a workspace", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 2,
    "project_url": "#signin",
}

ADVANCED_RAG_PROJECT = {
    "id": "advanced-rag", "title": "Transparent Advanced RAG",
    "summary": "Inspect query rewriting, multi-query retrieval, context quality checks, and the exact evidence sent to the answering model.",
    "category": "Generative AI", "tags": ["Advanced RAG", "Query Rewrite", "Multi-query", "Pinecone"],
    "image_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected server infrastructure representing a retrieval pipeline", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 3,
    "project_url": "#signin",
}

GOOGLE_WORKSPACE_AGENT_PROJECT = {
    "id": "google-workspace-agent", "title": "Google Workspace Agent",
    "summary": "Chat with Gmail and Google Calendar to find important mail, inspect meetings, and safely schedule or remove events.",
    "category": "Generative AI", "tags": ["Agent", "Gmail", "Google Calendar", "OAuth"],
    "image_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected productivity dashboard representing email and calendar automation", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 4,
    "project_url": "#signin",
}


GRAPH_RAG_PROJECT = {
    "id": "graph-rag", "title": "Real-time Graph RAG",
    "summary": "Watch a knowledge graph build itself in Neo4j, then answer questions by walking entity relationships instead of ranking text alone.",
    "category": "Generative AI", "tags": ["Graph RAG", "Neo4j", "Cypher", "Knowledge Graph"],
    "image_url": "https://images.unsplash.com/photo-1545987796-200677ee1011?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected network nodes representing a knowledge graph", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 5,
    "project_url": "#signin",
}


DEFAULT_LANDING_CONTENT = {
    "brand_name": "Veera AI",
    "announcement": "Engineering intelligence for the physical world",
    "capabilities_nav_label": "Capabilities",
    "roadmap_nav_label": "Roadmap",
    "login_label": "Sign in",
    "register_label": "Start building",
    "hero_slides": [
        {
            "eyebrow": "MECHATRONICS × AI",
            "title": "Build machines that sense, reason, and move.",
            "description": "Bring robotics, control systems, and generative AI into one practical workspace for the next generation of intelligent products.",
            "image_url": "https://images.unsplash.com/photo-1561144257-e32e8efc6c4f?auto=format&fit=crop&w=2000&q=88",
            "image_alt": "Industrial robotic arms working in a modern factory",
        },
        {
            "eyebrow": "MACHINE LEARNING",
            "title": "Turn real-world signals into confident decisions.",
            "description": "Prototype perception pipelines, explore models, and move from raw sensor data to production-ready intelligence.",
            "image_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=2000&q=88",
            "image_alt": "Detailed electronic circuit board for machine intelligence",
        },
        {
            "eyebrow": "GENERATIVE AI",
            "title": "A practical launchpad for ambitious AI ideas.",
            "description": "Experiment across leading model providers, organize your work, and turn early concepts into useful engineering tools.",
            "image_url": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=2000&q=88",
            "image_alt": "Humanoid robot representing applied artificial intelligence",
        },
    ],
    "primary_cta_label": "Explore the workspace",
    "secondary_cta_label": "See the roadmap",
    "metrics": [
        {"value": "5", "label": "AI providers in one workspace"},
        {"value": "24h", "label": "Privacy-first chat retention"},
        {"value": "3", "label": "Engineering disciplines connected"},
        {"value": "∞", "label": "Ideas ready to prototype"},
    ],
    "features_eyebrow": "THE BUILDING BLOCKS",
    "features_title": "From mechanical systems to machine intelligence",
    "features_description": "A focused workspace for engineers, builders, and teams exploring where software meets the physical world.",
    "features": [
        {"icon": "robot", "eyebrow": "MECHATRONICS", "title": "Intelligent motion", "description": "Explore robotics, actuation, sensing, and control concepts around machines designed to respond."},
        {"icon": "brain", "eyebrow": "MACHINE LEARNING", "title": "Models that learn", "description": "Turn datasets and signals into prediction, classification, and decision-making workflows."},
        {"icon": "vision", "eyebrow": "COMPUTER VISION", "title": "Perception systems", "description": "Connect cameras and visual models to inspection, navigation, and real-world understanding."},
        {"icon": "cpu", "eyebrow": "GENERATIVE AI", "title": "Multi-model creation", "description": "Work with leading AI providers through a single private, project-oriented experience."},
        {"icon": "chart", "eyebrow": "ANALYTICS", "title": "Engineering insight", "description": "Make system behavior easier to understand with clear experiments, traces, and outcomes."},
        {"icon": "workflow", "eyebrow": "AUTOMATION", "title": "Connected workflows", "description": "Move from an isolated prompt to repeatable tools that support practical engineering work."},
    ],
    "roadmap_eyebrow": "PRODUCT ROADMAP",
    "roadmap_title": "A workspace that grows with every experiment",
    "roadmap_description": "We are building in clear stages, starting with flexible model access and moving toward richer engineering intelligence.",
    "roadmap": [
        {"phase": "NOW", "title": "Multi-provider Basic Chat", "description": "Private conversations across OpenAI, Gemini, Mistral, GroqCloud, and OpenRouter.", "status": "available"},
        {"phase": "NEXT", "title": "Vision Lab", "description": "Image inspection and multimodal experimentation for parts, systems, and environments.", "status": "building"},
        {"phase": "HORIZON", "title": "ML Experiment Studio", "description": "Dataset-aware workflows for evaluating and comparing practical machine-learning ideas.", "status": "planned"},
        {"phase": "FUTURE", "title": "Digital System Copilot", "description": "A connected assistant for engineering context, simulations, decisions, and project knowledge.", "status": "planned"},
    ],
    "cta_title": "Turn your next engineering question into a working idea.",
    "cta_description": "Create your workspace and start exploring AI with tools designed around privacy, clarity, and real projects.",
    "cta_button_label": "Create your account",
    "footer_description": "Applied AI, machine learning, and mechatronics tools for people building what comes next.",
    "footer_links": [
        {"label": "Capabilities", "href": "#capabilities"},
        {"label": "Roadmap", "href": "#roadmap"},
        {"label": "Sign in", "href": "#signin"},
    ],
    "footer_copyright": "© 2026 Veera AI. Built for practical intelligence.",
}


async def get_landing_content():
    try:
        document = await landing_content.find_one({"_id": "default"})
    except PyMongoError:
        logger.exception("MongoDB unavailable; using built-in landing content")
        document = None
    return LandingContent(**({**DEFAULT_LANDING_CONTENT, **document} if document else DEFAULT_LANDING_CONTENT))


async def save_landing_content(content: LandingContent, updated_by):
    document = content.model_dump()
    document.update({"_id": "default", "updated_at": datetime.now(timezone.utc), "updated_by": updated_by})
    await landing_content.replace_one({"_id": "default"}, document, upsert=True)
    return content


async def get_project_catalog():
    try:
        document = await project_catalog.find_one({"_id": "default"})
        if not document:
            legacy = await landing_content.find_one({"_id": "default"}) or {}
            if legacy.get("portfolio_projects"):
                document = {
                    "nav_label": legacy.get("portfolio_nav_label", DEFAULT_PROJECT_CATALOG["nav_label"]),
                    "eyebrow": legacy.get("portfolio_eyebrow", DEFAULT_PROJECT_CATALOG["eyebrow"]),
                    "title": legacy.get("portfolio_title", DEFAULT_PROJECT_CATALOG["title"]),
                    "description": legacy.get("portfolio_description", DEFAULT_PROJECT_CATALOG["description"]),
                    "projects": legacy["portfolio_projects"],
                }
    except PyMongoError:
        logger.exception("MongoDB unavailable; using built-in project catalog")
        document = None
    content = ProjectCatalog(**(document or DEFAULT_PROJECT_CATALOG))
    if not document:
        project_type = type(content.projects[0])
        existing_ids = {project.id for project in content.projects}
        content.projects.extend(
            project_type(**project) for project in (
                BASIC_RAG_PROJECT, ADVANCED_RAG_PROJECT, GOOGLE_WORKSPACE_AGENT_PROJECT, GRAPH_RAG_PROJECT
            ) if project["id"] not in existing_ids
        )
    return content


async def migrate_project_catalog():
    if await project_catalog.find_one({"_id": "default"}):
        return
    legacy = await landing_content.find_one({"_id": "default"}) or {}
    if not legacy.get("portfolio_projects"):
        return
    content = ProjectCatalog(
        nav_label=legacy.get("portfolio_nav_label", DEFAULT_PROJECT_CATALOG["nav_label"]),
        eyebrow=legacy.get("portfolio_eyebrow", DEFAULT_PROJECT_CATALOG["eyebrow"]),
        title=legacy.get("portfolio_title", DEFAULT_PROJECT_CATALOG["title"]),
        description=legacy.get("portfolio_description", DEFAULT_PROJECT_CATALOG["description"]),
        projects=legacy["portfolio_projects"],
    )
    await save_project_catalog(content, "migration")


async def ensure_basic_rag_project():
    document = await project_catalog.find_one({"_id": "default"})
    if not document:
        content = ProjectCatalog(**DEFAULT_PROJECT_CATALOG)
        content.projects.append(type(content.projects[0])(**BASIC_RAG_PROJECT))
        await save_project_catalog(content, "built-in-project")
    elif not any(project.get("id") == BASIC_RAG_PROJECT["id"] for project in document.get("projects", [])):
        await project_catalog.update_one(
            {"_id": "default"},
            {"$push": {"projects": BASIC_RAG_PROJECT}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )


async def ensure_advanced_rag_project():
    document = await project_catalog.find_one({"_id": "default"})
    if not document:
        content = ProjectCatalog(**DEFAULT_PROJECT_CATALOG)
        content.projects.extend(type(content.projects[0])(**project) for project in (BASIC_RAG_PROJECT, ADVANCED_RAG_PROJECT))
        await save_project_catalog(content, "built-in-project")
    elif not any(project.get("id") == ADVANCED_RAG_PROJECT["id"] for project in document.get("projects", [])):
        await project_catalog.update_one(
            {"_id": "default"},
            {"$push": {"projects": ADVANCED_RAG_PROJECT}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )


async def ensure_google_workspace_agent_project():
    document = await project_catalog.find_one({"_id": "default"})
    if not document:
        content = ProjectCatalog(**DEFAULT_PROJECT_CATALOG)
        content.projects.extend(type(content.projects[0])(**project) for project in (BASIC_RAG_PROJECT, ADVANCED_RAG_PROJECT, GOOGLE_WORKSPACE_AGENT_PROJECT))
        await save_project_catalog(content, "built-in-project")
    elif not any(project.get("id") == GOOGLE_WORKSPACE_AGENT_PROJECT["id"] for project in document.get("projects", [])):
        await project_catalog.update_one(
            {"_id": "default"},
            {"$push": {"projects": GOOGLE_WORKSPACE_AGENT_PROJECT}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )


async def ensure_graph_rag_project():
    document = await project_catalog.find_one({"_id": "default"})
    if not document:
        content = ProjectCatalog(**DEFAULT_PROJECT_CATALOG)
        content.projects.extend(type(content.projects[0])(**project) for project in (
            BASIC_RAG_PROJECT, ADVANCED_RAG_PROJECT, GOOGLE_WORKSPACE_AGENT_PROJECT, GRAPH_RAG_PROJECT
        ))
        await save_project_catalog(content, "built-in-project")
    elif not any(project.get("id") == GRAPH_RAG_PROJECT["id"] for project in document.get("projects", [])):
        await project_catalog.update_one(
            {"_id": "default"},
            {"$push": {"projects": GRAPH_RAG_PROJECT}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )


async def save_project_catalog(content: ProjectCatalog, updated_by):
    document = content.model_dump()
    document.update({"_id": "default", "updated_at": datetime.now(timezone.utc), "updated_by": updated_by})
    await project_catalog.replace_one({"_id": "default"}, document, upsert=True)
    return content


async def get_public_project_catalog():
    content = await get_project_catalog()
    projects = sorted(
        (project for project in content.projects if project.show_public),
        key=lambda project: (not project.featured, project.display_order, project.title.lower()),
    )
    return content.model_copy(update={"projects": projects})


async def get_workspace_projects():
    content = await get_project_catalog()
    return sorted(
        (project for project in content.projects if project.show_workspace),
        key=lambda project: (not project.featured, project.display_order, project.title.lower()),
    )