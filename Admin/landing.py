from datetime import datetime, timezone
import logging

from pymongo.errors import PyMongoError

from Authentication.database import landing_content, project_catalog

from .models import LandingContent, LandingPortfolioProject, ProjectCatalog


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
            "blog_slug": "how-multi-provider-basic-chat-works",
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
    "blog_slug": "how-document-grounded-basic-rag-works",
}

ADVANCED_RAG_PROJECT = {
    "id": "advanced-rag", "title": "Transparent Advanced RAG",
    "summary": "Inspect query rewriting, multi-query retrieval, context quality checks, and the exact evidence sent to the answering model.",
    "category": "Generative AI", "tags": ["Advanced RAG", "Query Rewrite", "Multi-query", "Pinecone"],
    "image_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected server infrastructure representing a retrieval pipeline", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 3,
    "project_url": "#signin",
    "blog_slug": "how-transparent-advanced-rag-works",
}

GOOGLE_WORKSPACE_AGENT_PROJECT = {
    "id": "google-workspace-agent", "title": "Google Workspace Agent",
    "summary": "Chat with Gmail and Google Calendar to find important mail, inspect meetings, and safely schedule or remove events.",
    "category": "Generative AI", "tags": ["Agent", "Gmail", "Google Calendar", "OAuth"],
    "image_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected productivity dashboard representing email and calendar automation", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 4,
    "project_url": "#signin",
    "blog_slug": "how-google-workspace-agent-works",
}


GRAPH_RAG_PROJECT = {
    "id": "graph-rag", "title": "Real-time Graph RAG",
    "summary": "Watch a knowledge graph build itself in Neo4j, then answer questions by walking entity relationships instead of ranking text alone.",
    "category": "Generative AI", "tags": ["Graph RAG", "Neo4j", "Cypher", "Knowledge Graph"],
    "image_url": "https://images.unsplash.com/photo-1545987796-200677ee1011?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected network nodes representing a knowledge graph", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 5,
    "project_url": "#signin",
    "blog_slug": "how-real-time-graph-rag-works",
}

CHUNKING_LAB_PROJECT = {
    "id": "chunking-lab", "title": "Chunking Strategy Lab",
    "summary": "Upload documents and visually compare 8 chunking strategies side by side with real-time statistics and chunk inspection.",
    "category": "Generative AI", "tags": ["Chunking", "LangChain", "Embeddings", "LLM", "NLP"],
    "image_url": "https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Code and data visualizer interface for document chunking", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 6,
    "project_url": "#signin",
    "blog_slug": "chunking-strategies-visualizer",
}

AGENT_ORCHESTRATION_PROJECT = {
    "id": "agent-orchestration", "title": "Agent Orchestrator",
    "summary": "Design a graph of collaborating AI agents, wire up tools and RAG documents, and chat with any agent to watch it execute.",
    "category": "Generative AI", "tags": ["Agents", "LangGraph", "LangChain", "Tools", "RAG"],
    "image_url": "https://images.unsplash.com/photo-1591453089816-0fbb971b454c?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Connected nodes representing a multi-agent orchestration graph", "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 7,
    "project_url": "#signin",
    "blog_slug": "how-multi-agent-orchestration-works",
}

EMBED_LAB_PROJECT = {
    "id": "embed-lab", "title": "Embedding & Retrieval Lab",
    "summary": "Embed the same corpus with several models and watch them disagree about what a query means — the reason RAG returns the wrong chunk.",
    "category": "RAG", "tags": ["Embeddings", "Retrieval", "Vector Search", "Evaluation"],
    "image_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "A dense network of connected points suggesting vectors in a shared space",
    "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 10,
    "project_url": "#signin",
    "blog_slug": "why-your-rag-returns-the-wrong-chunk",
}

DECODE_LAB_PROJECT = {
    "id": "decode-lab", "title": "Decoding & Sampling Lab",
    "summary": "Drag temperature, top-k and top-p across a real GPT-2 distribution and see exactly what each one removes.",
    "category": "Generative AI", "tags": ["Sampling", "Temperature", "Top-p", "GPT-2", "Education"],
    "image_url": "https://images.unsplash.com/photo-1517420704952-d9f39e95b43e?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Control sliders on a mixing desk",
    "status": "available",
    "featured": True, "show_public": True, "show_workspace": True, "display_order": 11,
    "project_url": "#signin",
    "blog_slug": "what-temperature-actually-does",
}

GUARD_LAB_PROJECT = {
    "id": "guard-lab", "title": "Guardrails & Injection Lab",
    "summary": "See which prompt-injection and PII patterns an input filter catches — and watch a polite rephrase walk straight past it.",
    "category": "Generative AI", "tags": ["Security", "Prompt Injection", "PII", "Guardrails", "OWASP"],
    "image_url": "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "A padlock over a field of code, representing input filtering",
    "status": "available",
    "featured": False, "show_public": True, "show_workspace": True, "display_order": 12,
    "project_url": "#signin",
    "blog_slug": "what-input-filtering-catches",
}

INSIDE_LLM_PROJECT = {
    "id": "inside-llm", "title": "Inside an LLM",
    "summary": "Watch a real GPT-2 forward pass component by component — tokenization, embeddings, attention, feed-forward — with every number taken from the actual pretrained weights.",
    "category": "Generative AI", "tags": ["Transformers", "Attention", "Interpretability", "Education", "GPT-2"],
    "image_url": "https://images.unsplash.com/photo-1509228468518-180dd4864904?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "A lattice of connected points suggesting the layers of a neural network",
    "status": "available",
    "featured": True, "show_public": True, "show_workspace": True, "display_order": 9,
    "project_url": "#signin",
    "blog_slug": "how-a-transformer-actually-works",
}

SIMPLE_AGENT_PROJECT = {
    "id": "simple-agent", "title": "SimpleAgent — Tool Calling in the Open",
    "summary": "Build one agent, attach up to ten tools, and watch it decide in real time: what it reasoned, which tool it picked, what came back, and in what order.",
    "category": "Generative AI", "tags": ["Agents", "Tool Calling", "Observability", "LangGraph", "RAG"],
    "image_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=85",
    "image_alt": "Circuit traces representing an agent routing between tools", "status": "available",
    "featured": True, "show_public": True, "show_workspace": True, "display_order": 8,
    "project_url": "#signin",
    "blog_slug": "how-simpleagent-chooses-tools",
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


BUILT_IN_PROJECTS = (
    BASIC_RAG_PROJECT,
    ADVANCED_RAG_PROJECT,
    GOOGLE_WORKSPACE_AGENT_PROJECT,
    GRAPH_RAG_PROJECT,
    CHUNKING_LAB_PROJECT,
    AGENT_ORCHESTRATION_PROJECT,
    SIMPLE_AGENT_PROJECT,
    INSIDE_LLM_PROJECT,
    EMBED_LAB_PROJECT,
    DECODE_LAB_PROJECT,
    GUARD_LAB_PROJECT,
)

PROJECT_DEFAULT_BLOGS = {
    "basic-chat": "how-multi-provider-basic-chat-works",
    "basic-rag": "how-document-grounded-basic-rag-works",
    "advanced-rag": "how-transparent-advanced-rag-works",
    "google-workspace-agent": "how-google-workspace-agent-works",
    "chunking-lab": "chunking-strategies-visualizer",
    "graph-rag": "how-real-time-graph-rag-works",
    "agent-orchestration": "how-multi-agent-orchestration-works",
    "simple-agent": "how-simpleagent-chooses-tools",
    "inside-llm": "how-a-transformer-actually-works",
    "embed-lab": "why-your-rag-returns-the-wrong-chunk",
    "decode-lab": "what-temperature-actually-does",
    "guard-lab": "what-input-filtering-catches",
}


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
    existing_ids = {project.id for project in content.projects}
    missing = [
        LandingPortfolioProject(**project)
        for project in BUILT_IN_PROJECTS
        if project["id"] not in existing_ids
    ]
    if missing:
        content.projects.extend(missing)
        for project in BUILT_IN_PROJECTS:
            if project["id"] not in existing_ids:
                try:
                    await _ensure_built_in_project(project)
                except Exception:
                    pass

    for project in content.projects:
        if not project.blog_slug and project.id in PROJECT_DEFAULT_BLOGS:
            project.blog_slug = PROJECT_DEFAULT_BLOGS[project.id]

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


async def _ensure_built_in_project(project: dict):
    """Idempotently add a built-in project to the catalog exactly once.

    This used to read the document, check whether the id was already present, and
    only then $push — three separate steps with no atomicity between them. Under
    concurrent serverless cold starts (e.g. several instances starting up during a
    Vercel deploy) two of them could both see the project missing and each push a
    copy, corrupting the catalog with duplicate ids (which ProjectCatalog's
    require_unique_project_ids validator then rejects, breaking /portfolio entirely).

    A single filtered update is atomic at the document level: MongoDB only applies
    the $push if no array element already has that id, so a duplicate can't be
    created no matter how many instances race to call this at once.
    """
    result = await project_catalog.update_one(
        {"_id": "default", "projects.id": {"$ne": project["id"]}},
        {"$push": {"projects": project}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0 and not await project_catalog.find_one({"_id": "default"}):
        content = ProjectCatalog(**DEFAULT_PROJECT_CATALOG)
        content.projects.append(LandingPortfolioProject(**project))
        await save_project_catalog(content, "built-in-project")


async def ensure_basic_rag_project():
    await _ensure_built_in_project(BASIC_RAG_PROJECT)


async def ensure_advanced_rag_project():
    await _ensure_built_in_project(ADVANCED_RAG_PROJECT)


async def ensure_google_workspace_agent_project():
    await _ensure_built_in_project(GOOGLE_WORKSPACE_AGENT_PROJECT)


async def ensure_graph_rag_project():
    await _ensure_built_in_project(GRAPH_RAG_PROJECT)


async def ensure_chunking_lab_project():
    await _ensure_built_in_project(CHUNKING_LAB_PROJECT)


async def ensure_agent_orchestration_project():
    await _ensure_built_in_project(AGENT_ORCHESTRATION_PROJECT)


async def ensure_simple_agent_project():
    await _ensure_built_in_project(SIMPLE_AGENT_PROJECT)


async def ensure_inside_llm_project():
    await _ensure_built_in_project(INSIDE_LLM_PROJECT)


async def ensure_lab_projects():
    for project in (EMBED_LAB_PROJECT, DECODE_LAB_PROJECT, GUARD_LAB_PROJECT):
        await _ensure_built_in_project(project)


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