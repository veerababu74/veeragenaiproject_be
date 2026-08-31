"""LLM extraction of entities and relationships from a text chunk."""
import json
import logging
import re

from basichatapp.providers import ProviderError, chat


logger = logging.getLogger("veera.graph_rag.extraction")

SYSTEM_PROMPT = """You build knowledge graphs. Extract entities and the relationships between them from the supplied text.

Rules:
- Return ONLY a JSON object, no commentary and no markdown fences.
- Shape: {"entities": [{"name": "...", "type": "...", "description": "..."}], "relationships": [{"source": "...", "target": "...", "type": "...", "description": "..."}]}
- "type" for an entity is a short label such as Person, Organization, Location, Product, Concept, Event, Technology.
- "type" for a relationship is an UPPER_SNAKE_CASE verb phrase such as WORKS_FOR, LOCATED_IN, FOUNDED, PART_OF, USES.
- Every relationship source and target MUST exactly match an entity name you returned.
- Use the canonical full name of an entity and never a pronoun.
- Extract at most 12 entities and 15 relationships for this text.
- If the text has no meaningful entities return {"entities": [], "relationships": []}."""


def extract_graph(provider: str, api_key: str, model: str, text: str) -> dict:
    """Return {"entities": [...], "relationships": [...]} for one chunk."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Extract the knowledge graph from this text:\n\n{text}"},
    ]
    if provider == "gemini":
        messages = [{"role": "user", "content": f"{SYSTEM_PROMPT}\n\nExtract the knowledge graph from this text:\n\n{text}"}]
    try:
        response = chat(provider, api_key, model, messages)
    except ProviderError:
        raise
    return _normalize(_parse_json(response))


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    for candidate in (text, _fenced(text), _braced(text)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    logger.warning("Graph extraction returned unparsable JSON")
    return {}


def _fenced(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    return match.group(1) if match else ""


def _braced(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else ""


def _normalize(data: dict) -> dict:
    entities, seen = [], set()
    for item in data.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        key = " ".join(name.split()).lower()
        if not name or key in seen:
            continue
        seen.add(key)
        entities.append({
            "name": name[:120],
            "type": (str(item.get("type") or "Concept").strip() or "Concept")[:40],
            "description": str(item.get("description") or "").strip()[:400],
        })

    relationships = []
    for item in data.get("relationships") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        if " ".join(source.split()).lower() not in seen or " ".join(target.split()).lower() not in seen:
            continue
        relationship_type = re.sub(r"[^A-Za-z0-9]+", "_", str(item.get("type") or "RELATED_TO")).strip("_").upper()
        relationships.append({
            "source": source[:120],
            "target": target[:120],
            "type": (relationship_type or "RELATED_TO")[:60],
            "description": str(item.get("description") or "").strip()[:400],
        })
    return {"entities": entities, "relationships": relationships}
