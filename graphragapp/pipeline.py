"""Graph RAG pipelines that stream every internal step as it happens."""
from basichatapp.providers import chat
from basicragapp.chunking import chunk_text
from basicragapp.embeddings import embed_texts

from . import graph_store
from .extraction import extract_graph


ANSWER_PROMPT = """You are a Graph RAG assistant. You answer questions strictly using the knowledge graph
facts and source chunks retrieved from Neo4j below. Never use outside knowledge.

Follow this structure in every answer:
1. Start with a direct 1-2 sentence answer to the question in plain language.
2. Add a "**Key connections**" section with short bullet points, each naming the specific
   entities and the relationship between them (e.g. "- **Entity A** → RELATION → **Entity B**")
   drawn only from GRAPH FACTS. Skip this section if GRAPH FACTS is empty.
3. Add supporting detail in 1-3 short sentences or bullets, citing the chunk that backs each
   claim as [1], [2], etc., matching the SOURCE CHUNKS numbering.

Rules:
- Answer only from GRAPH FACTS and SOURCE CHUNKS. If they do not contain the answer, say so
  plainly in one sentence instead of guessing.
- Prefer the graph relationships to explain *how* things connect; use source chunks to explain
  *what* they mean.
- Be concise. Do not repeat the question or restate these instructions.
- Use Markdown (bold, bullet points) so the structure above renders clearly."""


def ingest_document(session_id, user_id, document_id, filename, text, provider, api_key,
                    model, embedding_api_key, embedding_model, chunk_size=900, overlap=120):
    """Yield progress events while building the graph for one document."""
    yield {"step": "schema", "message": "Ensuring Neo4j constraints and indexes"}
    graph_store.ensure_schema()

    chunks = chunk_text("recursive", text, chunk_size, overlap)
    yield {
        "step": "chunked",
        "message": f"Split {len(text):,} characters into {len(chunks)} chunks",
        "chunk_count": len(chunks),
        "character_count": len(text),
    }

    all_nodes, all_edges = {}, []
    for position, chunk in enumerate(chunks):
        yield {
            "step": "chunk-start",
            "message": f"Reading chunk {position + 1} of {len(chunks)}",
            "position": position,
            "total": len(chunks),
            "text": chunk,
        }

        graph = extract_graph(provider, api_key, model, chunk)
        entities, relationships = graph["entities"], graph["relationships"]
        yield {
            "step": "extracted",
            "message": f"Found {len(entities)} entities and {len(relationships)} relationships",
            "position": position,
            "entities": entities,
            "relationships": relationships,
        }

        chunk_id = f"{document_id}:{position}"
        texts = [chunk] + [f"{entity['name']}. {entity['description']}" for entity in entities]
        vectors = embed_texts(embedding_api_key, embedding_model, texts, "RETRIEVAL_DOCUMENT")
        yield {
            "step": "embedded",
            "message": f"Embedded chunk {position + 1} and {len(entities)} entities",
            "position": position,
            "vector_count": len(vectors),
            "dimensions": len(vectors[0]) if vectors else 0,
        }

        chunk_cypher = graph_store.upsert_chunk(
            session_id, user_id, document_id, filename, chunk_id, position, chunk, vectors[0]
        )
        written_entities, entity_cypher = graph_store.upsert_entities(
            session_id, user_id, entities, vectors[1:]
        )
        written_relationships, relationship_cypher = graph_store.upsert_relationships(
            session_id, relationships, chunk_id
        )
        mention_cypher = graph_store.link_mentions(
            chunk_id, [entity["key"] for entity in written_entities]
        )

        for entity in written_entities:
            all_nodes[entity["key"]] = {
                "key": entity["key"], "name": entity["name"],
                "type": entity["type"], "description": entity["description"],
            }
        for relationship in written_relationships:
            all_edges.append({
                "source": graph_store.entity_key(session_id, relationship["source"]),
                "target": graph_store.entity_key(session_id, relationship["target"]),
                "type": relationship["type"],
                "description": relationship["description"],
            })

        yield {
            "step": "graph-write",
            "message": f"Wrote chunk {position + 1} into Neo4j",
            "position": position,
            "cypher": [chunk_cypher.strip(), entity_cypher.strip(), relationship_cypher.strip(), mention_cypher.strip()],
            "nodes": list(all_nodes.values()),
            "edges": all_edges,
        }

    stats, stats_cypher = graph_store.graph_stats(session_id, user_id)
    yield {
        "step": "graph-complete",
        "message": "Knowledge graph updated",
        "cypher": stats_cypher.strip(),
        "stats": stats,
        "nodes": list(all_nodes.values()),
        "edges": all_edges,
        "chunks": chunks,
    }


def answer_question(session_id, user_id, question, provider, api_key, model,
                    embedding_api_key, embedding_model, top_k, hops, history):
    """Yield progress events while answering one question from the graph."""
    trace = {"question": question, "steps": []}

    query_vector = embed_texts(embedding_api_key, embedding_model, [question], "RETRIEVAL_QUERY")[0]
    yield {"step": "embed-question", "message": "Embedded the question", "dimensions": len(query_vector)}

    chunk_rows, chunk_cypher = graph_store.search_chunks(session_id, user_id, query_vector, top_k)
    trace["steps"].append({"name": "Vector search over chunks", "cypher": chunk_cypher.strip(), "rows": chunk_rows})
    yield {
        "step": "chunk-search",
        "message": f"Matched {len(chunk_rows)} source chunks by similarity",
        "cypher": chunk_cypher.strip(),
        "rows": chunk_rows,
    }

    entity_rows, entity_cypher = graph_store.search_entities(session_id, user_id, query_vector, top_k)
    trace["steps"].append({"name": "Vector search over entities", "cypher": entity_cypher.strip(), "rows": entity_rows})
    yield {
        "step": "entity-search",
        "message": f"Matched {len(entity_rows)} entry-point entities",
        "cypher": entity_cypher.strip(),
        "rows": entity_rows,
    }

    keys = [row["key"] for row in entity_rows]
    triples, expand_cypher = graph_store.expand_neighbourhood(session_id, user_id, keys, hops) if keys else ([], "")
    trace["steps"].append({"name": f"Graph traversal ({hops} hops)", "cypher": expand_cypher.strip(), "rows": triples})
    yield {
        "step": "traversal",
        "message": f"Walked {hops} hop(s) and collected {len(triples)} relationships",
        "cypher": expand_cypher.strip(),
        "rows": triples,
        "nodes": _triple_nodes(session_id, entity_rows, triples),
        "edges": _triple_edges(session_id, triples),
    }

    facts = "\n".join(
        f"({row['source']}:{row['source_type']}) -[{row['relationship']}]-> ({row['target']}:{row['target_type']})"
        + (f"  // {row['description']}" if row.get("description") else "")
        for row in triples
    ) or "No graph relationships were found."
    sources = "\n\n".join(
        f"[{index}] {row['filename']} (chunk {row['position'] + 1})\n{row['text']}"
        for index, row in enumerate(chunk_rows, 1)
    ) or "No source chunks were found."
    context = f"GRAPH FACTS\n{facts}\n\nSOURCE CHUNKS\n{sources}"
    trace["final_context"] = context
    yield {"step": "context", "message": "Built the grounded context", "context": context}

    messages = [{"role": item["role"], "content": item["content"]} for item in history[-6:]]
    prompt = f"{ANSWER_PROMPT}\n\n{context}\n\nQUESTION\n{question}"
    if provider == "gemini":
        messages.append({"role": "user", "content": prompt})
    else:
        messages = [{"role": "system", "content": ANSWER_PROMPT}] + messages
        messages.append({"role": "user", "content": f"{context}\n\nQUESTION\n{question}"})

    answer = chat(provider, api_key, model, messages)
    citations = [
        {
            "number": index, "filename": row["filename"], "position": row["position"],
            "score": row["score"], "text": row["text"],
        }
        for index, row in enumerate(chunk_rows, 1)
    ]
    yield {
        "step": "answer",
        "message": "Answer generated",
        "answer": answer,
        "citations": citations,
        "trace": trace,
    }


def _triple_nodes(session_id, entity_rows, triples):
    nodes = {row["key"]: {"key": row["key"], "name": row["name"], "type": row["type"], "seed": True} for row in entity_rows}
    for row in triples:
        for name, node_type in ((row["source"], row["source_type"]), (row["target"], row["target_type"])):
            key = graph_store.entity_key(session_id, name)
            nodes.setdefault(key, {"key": key, "name": name, "type": node_type, "seed": False})
    return list(nodes.values())


def _triple_edges(session_id, triples):
    return [
        {
            "source": graph_store.entity_key(session_id, row["source"]),
            "target": graph_store.entity_key(session_id, row["target"]),
            "type": row["relationship"],
            "description": row.get("description", ""),
        }
        for row in triples
    ]
