from datetime import datetime, timezone

from Authentication.database import blogs, project_catalog

from .models import BlogPost


def heading(content, level=2):
    return {"type": f"heading{level}", "content": content}


def paragraph(content):
    return {"type": "paragraph", "content": content}


def bullets(*items):
    return {"type": "bullet-list", "items": list(items)}


def steps(*items):
    return {"type": "numbered-list", "items": list(items)}


def diagram(content):
    return {"type": "mermaid", "content": content}


def table(headers, rows):
    return {
        "type": "table",
        "headers": headers,
        "rows": [{"cells": row} for row in rows],
    }


PROJECT_GUIDES = [
    {
        "slug": "how-multi-provider-basic-chat-works",
        "title": "Inside Multi-provider Basic Chat",
        "description": "A practical walkthrough of the React, FastAPI, provider-adapter, and short-lived SQLite flow behind Basic Chat.",
        "tags": ["Basic Chat", "FastAPI", "React", "LLM", "SQLite"],
        "project_id": "basic-chat",
        "published": True,
        "blocks": [
            heading("What this project does", 1),
            paragraph("Basic Chat is a private bring-your-own-key chat workspace. A user chooses OpenAI, Gemini, Mistral, GroqCloud, or OpenRouter, supplies a model ID and API key, and chats through one consistent interface. The application stores the conversation briefly, but it never writes the provider API key to its database."),
            heading("How to use it"),
            steps(
                "Open **Basic Chat** from the Projects workspace.",
                "Choose a provider and confirm the provider-specific model ID.",
                "Enter an API key. It is sent only with the current request and is not saved.",
                "Send a message, continue the conversation, or start a separate chat session.",
                "Delete a chat when it is no longer needed; inactive chats expire automatically after 24 hours.",
            ),
            heading("System architecture"),
            diagram("""flowchart LR
  U[User] --> R[React BasicChat]
  R -->|Cookie plus message and key| F[FastAPI basic-chat router]
  F --> A[Access check]
  A --> S[(SQLite sessions and messages)]
  F --> P{Provider adapter}
  P --> O[OpenAI compatible APIs]
  P --> G[Gemini API]
  O --> F
  G --> F
  F --> R
  K[API key] -. request only .-> P"""),
            heading("What happens when a message is sent"),
            steps(
                "The React form validates that a message and API key exist and that an API key was not accidentally pasted into the model field.",
                "FastAPI authenticates the session cookie and checks that the user still has access to the `basic-chat` project.",
                "If a session ID is present, the backend verifies ownership and prevents changing provider or model inside that session.",
                "The backend loads recent messages, converts them to provider roles, and appends the new user message.",
                "The provider adapter sends either an OpenAI-compatible chat request or a Gemini `generateContent` request.",
                "The user message and assistant answer are saved together, the session expiry is renewed, and the complete response is returned to React.",
            ),
            heading("Provider normalization"),
            table(
                ["Provider", "Transport", "Important adaptation"],
                [
                    ["OpenAI", "OpenAI-compatible chat completions", "Bearer token and model/messages payload"],
                    ["Mistral", "OpenAI-compatible chat completions", "Provider endpoint with the same normalized messages"],
                    ["GroqCloud", "OpenAI-compatible chat completions", "Groq endpoint and actionable upstream errors"],
                    ["OpenRouter", "OpenAI-compatible chat completions", "OpenRouter endpoint with bearer authentication"],
                    ["Gemini", "Google generateContent", "Assistant roles become model roles; key uses a header"],
                ],
            ),
            heading("Storage, privacy, and failure behavior"),
            bullets(
                "SQLite stores session metadata and user/assistant messages, scoped by user ID.",
                "Only the latest ten exchanges are retained for each chat.",
                "A session expires 24 hours after its latest interaction.",
                "Provider keys exist only in browser state and the active request; database tables have no API-key column.",
                "Provider failures are converted into useful messages without exposing raw upstream response bodies.",
            ),
            heading("Why the design is intentionally simple"),
            paragraph("Basic Chat is the foundation used by the RAG projects. Its provider adapter gives the rest of the application one `chat` function while keeping session ownership, expiry, and key handling in a small auditable path. It does not pretend to be an agent or retrieval system: every answer comes from the selected model and the conversation history."),
        ],
    },
    {
        "slug": "how-document-grounded-basic-rag-works",
        "title": "Inside Document-grounded Basic RAG",
        "description": "How documents become chunks, embeddings, Pinecone matches, cited context, and grounded answers in the Basic RAG project.",
        "tags": ["Basic RAG", "Embeddings", "Pinecone", "Hugging Face", "FastAPI"],
        "project_id": "basic-rag",
        "published": True,
        "blocks": [
            heading("What RAG adds to a normal chat", 1),
            paragraph("Retrieval-augmented generation, or RAG, gives the language model selected evidence before it answers. Instead of asking the model to rely on general training knowledge, Basic RAG extracts text from the user's documents, retrieves the chunks closest to the question, and instructs the model to answer only from those sources with numbered citations."),
            heading("How to use it"),
            steps(
                "Choose an LLM provider, model, and request-only provider API key.",
                "Enter a Gemini embedding key and keep the embedding model fixed for the session.",
                "Choose PDF, DOCX, or TXT, then select fixed, recursive, content-aware, or semantic chunking.",
                "Inspect the live chunk preview and overlap before adding the document to the knowledge base.",
                "Ask a question, inspect cited source chunks, and delete documents or the whole session when finished.",
            ),
            heading("Ingestion architecture"),
            diagram("""flowchart TD
  U[Document upload] --> X[Text extraction]
  X --> C[Chunk strategy]
  C --> E[Gemini embeddings]
  E --> V[(Pinecone vectors)]
  U --> H[(Hugging Face original file)]
  C --> S[(SQLite metadata and chunk text)]
  V --> Q[Ready for retrieval]
  H --> Q
  S --> Q"""),
            heading("The ingestion pipeline"),
            steps(
                "FastAPI reads no more than the configured file-size limit and reduces the supplied name to a safe base name.",
                "A SHA-256 hash rejects duplicate content for the same user, even across different sessions.",
                "Text extraction accepts only PDF, DOCX, and TXT and normalizes their content.",
                "The selected strategy splits text with a configurable chunk size and overlap. Semantic mode first embeds sentences to detect topic changes.",
                "Gemini creates 768-dimensional retrieval-document vectors for every final chunk.",
                "The original file goes to a private user/session path in the Hugging Face dataset repository; vectors go to Pinecone; metadata and chunk text go to SQLite.",
                "If vector or metadata persistence fails after upload, the backend attempts to remove both vectors and the original file.",
            ),
            heading("Question-answer architecture"),
            diagram("""sequenceDiagram
  participant UI as React UI
  participant API as FastAPI
  participant EMB as Gemini Embeddings
  participant VS as Pinecone
  participant LLM as Selected LLM
  UI->>API: Question plus session and request-only keys
  API->>EMB: Embed question as RETRIEVAL_QUERY
  EMB-->>API: Query vector
  API->>VS: Search user namespace and session filter
  VS-->>API: Top matching chunks and scores
  API->>LLM: Recent history plus numbered sources
  LLM-->>API: Grounded answer with citations
  API-->>UI: Answer, citations, documents, session"""),
            heading("Chunking choices"),
            table(
                ["Strategy", "Behavior", "Best starting point"],
                [
                    ["Fixed", "Cuts by character window with overlap", "Uniform or machine-generated text"],
                    ["Recursive", "Prefers paragraph and sentence boundaries", "General documents"],
                    ["Content-aware", "Uses document structure while respecting limits", "Headings and sections"],
                    ["Semantic", "Groups nearby sentences until meaning changes", "Mixed-topic narrative text"],
                ],
            ),
            heading("Isolation and limits"),
            bullets(
                "Every session and document lookup includes the authenticated user ID.",
                "Pinecone uses a per-user namespace and a session filter, preventing retrieval from another session.",
                "Each user receives a 5 MB original-document allowance and duplicate bytes are rejected.",
                "RAG sessions and their local metadata expire after 24 hours of inactivity.",
                "Changing the LLM, model, or embedding model requires a new session so stored vectors remain compatible.",
            ),
            heading("What grounding does and does not guarantee"),
            paragraph("The final prompt says to answer only from supplied sources and to cite claims, which sharply reduces unsupported answers. It is still an LLM response, not a formal proof. The source drawer and chunk inspector exist so a reader can verify whether the retrieved text actually supports the answer."),
        ],
    },
    {
        "slug": "how-transparent-advanced-rag-works",
        "title": "Inside Transparent Advanced RAG",
        "description": "A complete explanation of query rewriting, multi-query retrieval, deduplication, quality checks, fallback search, and visible traces.",
        "tags": ["Advanced RAG", "Multi-query", "Retrieval", "Pinecone", "Observability"],
        "project_id": "advanced-rag",
        "published": True,
        "blocks": [
            heading("Why Advanced RAG exists", 1),
            paragraph("Basic RAG performs one vector search. Advanced RAG keeps the same document ingestion and privacy foundations but makes retrieval broader and inspectable. It rewrites the question, generates alternative searches, merges their evidence, checks retrieval quality, optionally retries with a broader query, and exposes the entire trace in the interface."),
            heading("How to use it"),
            steps(
                "Upload and preview documents exactly as in Basic RAG.",
                "Ask a question that may use different wording from the source document.",
                "Open the Trace view to compare the original, rewritten, and generated searches.",
                "Inspect each search's chunks and similarity scores, the quality decision, and the exact final context.",
                "Use the citations to verify the final answer against the selected source text.",
            ),
            heading("Advanced retrieval architecture"),
            diagram("""flowchart TD
  Q[User question] --> P[LLM query planner]
  P --> O[Original query]
  P --> R[Rewritten query]
  P --> G1[Generated query one]
  P --> G2[Generated query two]
  O --> E[Batch query embeddings]
  R --> E
  G1 --> E
  G2 --> E
  E --> V[(Pinecone searches)]
  V --> D[Deduplicate and rank chunks]
  D --> C{Best score at least 0.35}
  C -->|Yes| F[Build final context]
  C -->|No| B[Generate broader fallback query]
  B --> V
  F --> A[Grounded answer plus trace]"""),
            heading("Pipeline logic, step by step"),
            steps(
                "The selected LLM is asked for strict JSON containing one rewritten query and two distinct generated queries.",
                "If that JSON is invalid, deterministic fallback searches are created from the original wording so the request can continue.",
                "Duplicate query text is removed case-insensitively before one batch embedding call.",
                "Each query searches the user's Pinecone namespace with the active session filter and requested `top_k`.",
                "Chunks are deduplicated by document ID and position. If multiple searches find the same chunk, only its highest score is retained.",
                "The best score is compared with the 0.35 quality threshold. Weak evidence triggers one LLM-generated broader search and another retrieval.",
                "Up to ten globally ranked chunks become numbered sources and the exact final context sent to the answer model.",
                "The answer, citations, and structured trace are saved together and returned to the UI.",
            ),
            heading("What the trace contains"),
            table(
                ["Trace field", "What it explains"],
                [
                    ["original_query", "The user's unmodified question"],
                    ["rewritten_query", "A retrieval-focused restatement"],
                    ["generated_queries", "Two alternative vocabulary or intent paths"],
                    ["retrievals", "Every search, matched chunk, and similarity score"],
                    ["context_quality", "Threshold, best score, status, and reason"],
                    ["fallback_query", "The broader retry, when weak context requires it"],
                    ["final_context", "The exact numbered evidence supplied to the final LLM"],
                ],
            ),
            heading("Shared foundation with Basic RAG"),
            bullets(
                "The same extraction, four chunking strategies, Gemini embeddings, Hugging Face file storage, and Pinecone vector store are reused.",
                "A separate SQLite database keeps Advanced RAG sessions and traces independent from Basic RAG sessions.",
                "The same ownership checks, 5 MB quota, duplicate detection, cleanup, and rollback behavior apply.",
                "The React project reuses the Basic RAG interface with an advanced endpoint, progress sequence, and Trace tab.",
            ),
            heading("Tradeoffs"),
            paragraph("Multiple searches improve recall when a question and document use different vocabulary, but they cost more embedding and vector-search work than Basic RAG. The score threshold is a practical heuristic rather than a universal measure of truth. The visible trace makes that tradeoff reviewable instead of hiding it behind a single answer."),
        ],
    },
    {
        "slug": "how-google-workspace-agent-works",
        "title": "Inside the Google Workspace Agent",
        "description": "How OAuth, LLM tool planning, Gmail and Calendar adapters, approval gates, encrypted tokens, and audit traces work together.",
        "tags": ["AI Agent", "Google OAuth", "Gmail", "Calendar", "Tool Calling"],
        "project_id": "google-workspace-agent",
        "published": True,
        "blocks": [
            heading("What makes this an agent", 1),
            paragraph("The Google Workspace Agent does more than generate text. It lets an LLM choose from a controlled set of Gmail and Calendar tools, validates the proposed arguments, executes read operations, and pauses before any calendar mutation. The application, not the model, owns authentication, permissions, validation, and final execution."),
            heading("How to use it"),
            steps(
                "Open **Google Workspace Agent** and connect Gmail plus Google Calendar through Google's consent screen.",
                "Choose an LLM provider and model, then enter a request-only provider API key.",
                "Ask to find mail, show important messages, inspect meetings, or prepare a calendar event.",
                "Review the activity trace and structured Gmail or Calendar results.",
                "For calendar creation or deletion, inspect the proposed action and explicitly approve it before execution.",
                "Unlink Google to revoke authorization and remove the encrypted refresh token from the user record.",
            ),
            heading("System architecture"),
            diagram("""flowchart LR
  U[User] --> UI[React Workspace Agent]
  UI --> API[FastAPI workspace-agent router]
  API --> AUTH[Google OAuth and token refresh]
  API --> PLAN[LLM tool planner]
  PLAN --> VALID[Allowlist and argument validation]
  VALID --> READ[Gmail or Calendar reads]
  VALID --> GATE{Mutation requested}
  GATE -->|No| RESULT[Structured result and explanation]
  GATE -->|Yes| WAIT[(Pending action in SQLite)]
  WAIT --> APPROVE[User approval]
  APPROVE --> WRITE[Google Calendar mutation]
  READ --> RESULT
  WRITE --> RESULT
  RESULT --> UI"""),
            heading("OAuth and token handling"),
            steps(
                "The backend creates a signed, user-bound OAuth state value and returns Google's authorization URL.",
                "The callback verifies state, exchanges the short-lived code, reads the Google account email, and receives a refresh token.",
                "The refresh token is encrypted with the application's secret before MongoDB stores it on the user document.",
                "For each agent request, the backend decrypts the refresh token and exchanges it for a temporary access token.",
                "Unlinking attempts Google revocation and then removes the saved Workspace connection.",
            ),
            heading("Agent request lifecycle"),
            diagram("""sequenceDiagram
  participant U as User
  participant A as FastAPI Agent
  participant L as Selected LLM
  participant G as Google Workspace
  participant D as SQLite
  U->>A: Natural-language request
  A->>L: Tool definitions plus recent history
  L-->>A: Normalized action and arguments
  alt Read operation
    A->>G: Gmail or Calendar read
    G-->>A: Structured data
    A->>D: Save answer and trace
  else Calendar mutation
    A->>D: Save pending action
    A-->>U: Ask for confirmation
    U->>A: Approve message ID
    A->>D: Atomically claim pending action
    A->>G: Create or delete event
    A->>D: Mark complete and append result
  end
  A-->>U: Updated conversation"""),
            heading("Safety boundaries"),
            bullets(
                "Only declared Gmail and Calendar tools can be selected; arbitrary model-generated code is never executed.",
                "Calendar create and delete operations are represented as pending actions and cannot call Google before confirmation.",
                "Pending actions are atomically claimed so repeated confirmation clicks cannot execute the same mutation twice.",
                "If Google authentication or execution fails, the claim is released so the user can retry safely.",
                "Every session and pending action is joined back to the authenticated user before it can be read or executed.",
                "Provider API keys are request-only; Google refresh tokens are encrypted at rest.",
            ),
            heading("Persistence map"),
            table(
                ["Data", "Store", "Reason"],
                [
                    ["Google refresh token and email", "MongoDB user document", "Durable account connection with encrypted secret"],
                    ["Agent sessions and messages", "SQLite", "Simple user-scoped conversation history"],
                    ["Tool traces and structured results", "SQLite message fields", "Inspectable execution history"],
                    ["Pending and completed actions", "SQLite message fields", "Approval state and idempotent claiming"],
                    ["LLM provider API key", "Not persisted", "Used only for the current request"],
                    ["Google access token", "Not persisted", "Refreshed temporarily when a tool runs"],
                ],
            ),
            heading("The key design principle"),
            paragraph("The model proposes; the application decides. Read tools can run after validation, while write tools cross an explicit human approval boundary. That separation keeps natural-language interaction useful without granting an LLM silent authority over a user's calendar."),
        ],
    },
]


async def ensure_project_guides():
    now = datetime.now(timezone.utc)
    for guide in PROJECT_GUIDES:
        post = BlogPost(**guide).model_dump()
        post.update({"created_at": now, "updated_at": now, "created_by": "built-in-project-guide"})
        await blogs.update_one({"slug": guide["slug"]}, {"$setOnInsert": post}, upsert=True)
        await project_catalog.update_one(
            {
                "_id": "default",
                "projects": {"$elemMatch": {
                    "id": guide["project_id"],
                    "$or": [
                        {"blog_slug": {"$exists": False}},
                        {"blog_slug": None},
                    ],
                }},
            },
            {"$set": {"projects.$.blog_slug": guide["slug"]}},
        )