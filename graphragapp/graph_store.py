"""Neo4j graph store for Graph RAG.

Every helper returns the exact Cypher it executed so the interface can show
users what ran against Neo4j in real time.
"""
import logging
import threading

from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError

from Authentication.config import settings


logger = logging.getLogger("veera.graph_rag.store")

_driver = None
_driver_lock = threading.Lock()
_schema_ready = False


class GraphStoreError(Exception):
    pass


SCHEMA_STATEMENTS = (
    "CREATE CONSTRAINT graphrag_entity_key IF NOT EXISTS FOR (e:Entity) REQUIRE e.key IS UNIQUE",
    "CREATE CONSTRAINT graphrag_chunk_id IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
    "CREATE INDEX graphrag_entity_session IF NOT EXISTS FOR (e:Entity) ON (e.session_id)",
    "CREATE INDEX graphrag_chunk_session IF NOT EXISTS FOR (c:Chunk) ON (c.session_id)",
)

UPSERT_ENTITY = """
MERGE (e:Entity {key: $key})
ON CREATE SET e.created_at = timestamp()
SET e.session_id = $session_id, e.user_id = $user_id, e.name = $name,
    e.type = $type, e.description = $description, e.embedding = $embedding
RETURN e.key AS key
"""

UPSERT_RELATIONSHIP = """
MATCH (source:Entity {key: $source_key}), (target:Entity {key: $target_key})
MERGE (source)-[r:RELATES {type: $type}]->(target)
SET r.session_id = $session_id, r.description = $description, r.chunk_id = $chunk_id
RETURN source.name AS source, r.type AS type, target.name AS target
"""

UPSERT_CHUNK = """
MERGE (c:Chunk {id: $id})
SET c.session_id = $session_id, c.user_id = $user_id, c.document_id = $document_id,
    c.filename = $filename, c.position = $position, c.text = $text, c.embedding = $embedding
RETURN c.id AS id
"""

LINK_MENTION = """
MATCH (c:Chunk {id: $chunk_id}), (e:Entity {key: $entity_key})
MERGE (c)-[:MENTIONS]->(e)
"""

SEARCH_CHUNKS = """
MATCH (c:Chunk {session_id: $session_id, user_id: $user_id})
WITH c, vector.similarity.cosine(c.embedding, $vector) AS score
WHERE score IS NOT NULL
RETURN c.id AS id, c.text AS text, c.filename AS filename,
       c.position AS position, c.document_id AS document_id, score
ORDER BY score DESC
LIMIT $top_k
"""

SEARCH_ENTITIES = """
MATCH (e:Entity {session_id: $session_id, user_id: $user_id})
WITH e, vector.similarity.cosine(e.embedding, $vector) AS score
WHERE score IS NOT NULL
RETURN e.key AS key, e.name AS name, e.type AS type, e.description AS description, score
ORDER BY score DESC
LIMIT $top_k
"""

EXPAND_NEIGHBOURHOOD = """
MATCH path = (seed:Entity)-[:RELATES*1..%(hops)d]-(related:Entity)
WHERE seed.key IN $keys AND related.session_id = $session_id AND related.user_id = $user_id
UNWIND relationships(path) AS rel
WITH DISTINCT startNode(rel) AS source, rel, endNode(rel) AS target
RETURN source.name AS source, source.type AS source_type, rel.type AS relationship,
       target.name AS target, target.type AS target_type,
       coalesce(rel.description, '') AS description
LIMIT $limit
"""

SESSION_GRAPH = """
MATCH (e:Entity {session_id: $session_id, user_id: $user_id})
OPTIONAL MATCH (e)-[r:RELATES]->(m:Entity {session_id: $session_id, user_id: $user_id})
RETURN collect(DISTINCT {key: e.key, name: e.name, type: e.type, description: e.description}) AS nodes,
       collect(DISTINCT CASE WHEN r IS NULL THEN NULL ELSE
           {source: e.key, target: m.key, type: r.type, description: coalesce(r.description, '')} END) AS edges
"""

GRAPH_STATS = """
MATCH (e:Entity {session_id: $session_id, user_id: $user_id})
WITH count(e) AS entity_count
MATCH (c:Chunk {session_id: $session_id, user_id: $user_id})
WITH entity_count, count(c) AS chunk_count
OPTIONAL MATCH (:Entity {session_id: $session_id, user_id: $user_id})-[r:RELATES]->(:Entity {session_id: $session_id, user_id: $user_id})
RETURN entity_count, chunk_count, count(r) AS relationship_count
"""

DELETE_SESSION_GRAPH = """
MATCH (n)
WHERE (n:Entity OR n:Chunk) AND n.session_id = $session_id AND n.user_id = $user_id
DETACH DELETE n
"""

DELETE_DOCUMENT_GRAPH = """
MATCH (c:Chunk {session_id: $session_id, user_id: $user_id, document_id: $document_id})
DETACH DELETE c
WITH $session_id AS session_id, $user_id AS user_id
MATCH (e:Entity {session_id: session_id, user_id: user_id})
WHERE NOT (e)<-[:MENTIONS]-(:Chunk)
DETACH DELETE e
"""


def entity_key(session_id: str, name: str) -> str:
    normalized = " ".join(name.split()).lower()
    return f"{session_id}:{normalized}"


def get_driver():
    global _driver
    if not settings.neo4j_uri or not settings.neo4j_password:
        raise GraphStoreError("Neo4j is not configured on this server")
    with _driver_lock:
        if _driver is None:
            _driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_username, settings.neo4j_password),
                max_connection_lifetime=280,
            )
    return _driver


def close_driver():
    global _driver, _schema_ready
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None
            _schema_ready = False


def _run(cypher: str, parameters: dict, write: bool = False):
    driver = get_driver()
    try:
        with driver.session(database=settings.neo4j_database) as session:
            runner = session.execute_write if write else session.execute_read
            return runner(lambda transaction: [record.data() for record in transaction.run(cypher, parameters)])
    except Neo4jError as error:
        logger.exception("Neo4j query failed")
        raise GraphStoreError(f"Neo4j rejected the query: {error.message}") from error
    except Exception as error:
        logger.exception("Neo4j connection failed")
        raise GraphStoreError("Could not reach Neo4j") from error


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    for statement in SCHEMA_STATEMENTS:
        _run(statement, {}, write=True)
    _schema_ready = True


def upsert_chunk(session_id, user_id, document_id, filename, chunk_id, position, text, embedding):
    parameters = {
        "id": chunk_id, "session_id": session_id, "user_id": user_id,
        "document_id": document_id, "filename": filename, "position": position,
        "text": text, "embedding": embedding,
    }
    _run(UPSERT_CHUNK, parameters, write=True)
    return UPSERT_CHUNK


def upsert_entities(session_id, user_id, entities, embeddings):
    """entities: [{name, type, description}] aligned with embeddings."""
    written = []
    for entity, embedding in zip(entities, embeddings):
        key = entity_key(session_id, entity["name"])
        _run(
            UPSERT_ENTITY,
            {
                "key": key, "session_id": session_id, "user_id": user_id,
                "name": entity["name"].strip(), "type": entity.get("type", "Concept"),
                "description": entity.get("description", ""), "embedding": embedding,
            },
            write=True,
        )
        written.append({**entity, "key": key})
    return written, UPSERT_ENTITY


def upsert_relationships(session_id, relationships, chunk_id):
    written = []
    for relationship in relationships:
        parameters = {
            "source_key": entity_key(session_id, relationship["source"]),
            "target_key": entity_key(session_id, relationship["target"]),
            "type": relationship.get("type", "RELATED_TO"),
            "description": relationship.get("description", ""),
            "session_id": session_id,
            "chunk_id": chunk_id,
        }
        if _run(UPSERT_RELATIONSHIP, parameters, write=True):
            written.append(relationship)
    return written, UPSERT_RELATIONSHIP


def link_mentions(chunk_id, entity_keys):
    for key in entity_keys:
        _run(LINK_MENTION, {"chunk_id": chunk_id, "entity_key": key}, write=True)
    return LINK_MENTION


def search_chunks(session_id, user_id, vector, top_k):
    return _run(SEARCH_CHUNKS, {"session_id": session_id, "user_id": user_id, "vector": vector, "top_k": top_k}), SEARCH_CHUNKS


def search_entities(session_id, user_id, vector, top_k):
    return _run(SEARCH_ENTITIES, {"session_id": session_id, "user_id": user_id, "vector": vector, "top_k": top_k}), SEARCH_ENTITIES


def expand_neighbourhood(session_id, user_id, keys, hops, limit=60):
    cypher = EXPAND_NEIGHBOURHOOD % {"hops": max(1, min(hops, 3))}
    return _run(cypher, {"session_id": session_id, "user_id": user_id, "keys": keys, "limit": limit}), cypher


def session_graph(session_id, user_id):
    rows = _run(SESSION_GRAPH, {"session_id": session_id, "user_id": user_id})
    if not rows:
        return {"nodes": [], "edges": []}, SESSION_GRAPH
    nodes = rows[0].get("nodes") or []
    edges = [edge for edge in (rows[0].get("edges") or []) if edge]
    return {"nodes": nodes, "edges": edges}, SESSION_GRAPH


def graph_stats(session_id, user_id):
    rows = _run(GRAPH_STATS, {"session_id": session_id, "user_id": user_id})
    stats = rows[0] if rows else {"entity_count": 0, "chunk_count": 0, "relationship_count": 0}
    return stats, GRAPH_STATS


def delete_session_graph(session_id, user_id):
    _run(DELETE_SESSION_GRAPH, {"session_id": session_id, "user_id": user_id}, write=True)


def delete_document_graph(session_id, user_id, document_id):
    _run(DELETE_DOCUMENT_GRAPH, {"session_id": session_id, "user_id": user_id, "document_id": document_id}, write=True)
