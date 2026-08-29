import json

from basichatapp.providers import chat
from basicragapp.embeddings import embed_texts
from basicragapp.vector_store import query


QUALITY_THRESHOLD = 0.35


def _plan_queries(question, provider, api_key, model, chat_fn):
    prompt = (
        "Rewrite the user's question for document retrieval and generate two distinct search queries. "
        "Preserve names and technical terms. Return only JSON with keys rewritten_query and "
        f"generated_queries (an array of two strings). User question: {question}"
    )
    raw = chat_fn(provider, api_key, model, [{"role": "user", "content": prompt}]).strip()
    try:
        plan = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
        rewritten = str(plan["rewritten_query"]).strip()
        generated = [str(item).strip() for item in plan["generated_queries"] if str(item).strip()][:2]
        if not rewritten or not generated:
            raise ValueError
        return rewritten, generated
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return question, [f"Detailed information about {question}", f"Evidence answering {question}"]


def _source_payload(source):
    return {
        "document_id": source.get("document_id"), "filename": source["filename"],
        "position": source["position"], "score": round(float(source["score"]), 4),
        "text": source["text"],
    }


def run_pipeline(
    question, user_id, session_id, provider, api_key, model, embedding_api_key,
    embedding_model, top_k, history, chat_fn=chat, embed_fn=embed_texts, query_fn=query,
):
    rewritten, generated = _plan_queries(question, provider, api_key, model, chat_fn)
    searches = [("original", question), ("rewritten", rewritten)] + [("generated", item) for item in generated]
    unique_searches = []
    seen_queries = set()
    for kind, search in searches:
        normalized = search.casefold()
        if normalized not in seen_queries:
            seen_queries.add(normalized)
            unique_searches.append((kind, search))

    vectors = embed_fn(embedding_api_key, embedding_model, [item[1] for item in unique_searches], "RETRIEVAL_QUERY")
    retrievals = []
    best_sources = {}
    for (kind, search), vector in zip(unique_searches, vectors):
        chunks = [_source_payload(item) for item in query_fn(user_id, session_id, vector, top_k)]
        retrievals.append({"type": kind, "query": search, "chunks": chunks})
        for source in chunks:
            key = (source.get("document_id"), source["position"])
            if key not in best_sources or source["score"] > best_sources[key]["score"]:
                best_sources[key] = source

    ranked = sorted(best_sources.values(), key=lambda item: item["score"], reverse=True)
    best_score = ranked[0]["score"] if ranked else 0.0
    quality = {
        "status": "strong" if best_score >= QUALITY_THRESHOLD else "weak",
        "best_score": best_score,
        "threshold": QUALITY_THRESHOLD,
        "reason": "Relevant chunks were found" if best_score >= QUALITY_THRESHOLD else "No sufficiently relevant chunk was found",
    }
    fallback_query = None
    if quality["status"] == "weak":
        fallback_query = chat_fn(provider, api_key, model, [{
            "role": "user",
            "content": f"Create one broader document search query for this question. Return only the query. Question: {question}",
        }]).strip()
        fallback_vector = embed_fn(embedding_api_key, embedding_model, [fallback_query], "RETRIEVAL_QUERY")[0]
        chunks = [_source_payload(item) for item in query_fn(user_id, session_id, fallback_vector, top_k)]
        retrievals.append({"type": "fallback", "query": fallback_query, "chunks": chunks})
        for source in chunks:
            key = (source.get("document_id"), source["position"])
            if key not in best_sources or source["score"] > best_sources[key]["score"]:
                best_sources[key] = source
        ranked = sorted(best_sources.values(), key=lambda item: item["score"], reverse=True)
        recovered_score = ranked[0]["score"] if ranked else 0.0
        if recovered_score >= QUALITY_THRESHOLD:
            quality.update({
                "status": "recovered", "best_score": recovered_score,
                "reason": "The fallback query found sufficiently relevant chunks",
            })

    sources = [{"number": index, **source} for index, source in enumerate(ranked[:10], 1)]
    final_context = "\n\n".join(
        f"[{source['number']}] {source['filename']} (chunk {source['position'] + 1}, score {source['score']:.4f})\n{source['text']}"
        for source in sources
    )
    messages = [{"role": item["role"], "content": item["content"]} for item in history[-10:]]
    messages.append({
        "role": "user",
        "content": "Answer only from the supplied final context. If it does not contain the answer, say so. "
        f"Cite claims with [1], [2], etc.\n\nFINAL CONTEXT\n{final_context}\n\nQUESTION\n{question}",
    })
    answer = chat_fn(provider, api_key, model, messages)
    trace = {
        "original_query": question, "rewritten_query": rewritten,
        "generated_queries": generated, "retrievals": retrievals,
        "context_quality": quality, "fallback_query": fallback_query,
        "final_context": final_context,
    }
    return answer, sources, trace
