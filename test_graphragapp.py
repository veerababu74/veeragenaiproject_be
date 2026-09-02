import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from Authentication.config import settings
from graphragapp import database, graph_store
from graphragapp.router import graph_rag_user_id, router


def vector(seed: float):
    values = [0.0] * 768
    values[0] = seed
    values[1] = 1.0 - seed
    return values


@unittest.skipUnless(settings.neo4j_uri and settings.neo4j_password, "Neo4j is not configured")
class GraphStoreIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.session_id = f"test-{uuid4().hex}"
        self.user_id = "test-user"
        graph_store.ensure_schema()

    def tearDown(self):
        graph_store.delete_session_graph(self.session_id, self.user_id)

    def test_graph_is_built_searched_traversed_and_deleted(self):
        entities = [
            {"name": "Ada Lovelace", "type": "Person", "description": "Mathematician"},
            {"name": "Analytical Engine", "type": "Technology", "description": "Mechanical computer"},
        ]
        graph_store.upsert_chunk(
            self.session_id, self.user_id, "doc-1", "history.txt",
            "doc-1:0", 0, "Ada Lovelace wrote notes on the Analytical Engine.", vector(1.0),
        )
        written, _ = graph_store.upsert_entities(
            self.session_id, self.user_id, entities, [vector(1.0), vector(0.0)]
        )
        graph_store.upsert_relationships(
            self.session_id,
            [{"source": "Ada Lovelace", "target": "Analytical Engine", "type": "WROTE_ABOUT", "description": "Notes"}],
            "doc-1:0",
        )
        graph_store.link_mentions("doc-1:0", [entity["key"] for entity in written])

        chunks, _ = graph_store.search_chunks(self.session_id, self.user_id, vector(1.0), 5)
        self.assertEqual(len(chunks), 1)
        self.assertAlmostEqual(chunks[0]["score"], 1.0, places=5)

        found, _ = graph_store.search_entities(self.session_id, self.user_id, vector(1.0), 5)
        self.assertEqual(found[0]["name"], "Ada Lovelace")

        triples, _ = graph_store.expand_neighbourhood(self.session_id, self.user_id, [written[0]["key"]], hops=2)
        self.assertEqual(
            [(row["source"], row["relationship"], row["target"]) for row in triples],
            [("Ada Lovelace", "WROTE_ABOUT", "Analytical Engine")],
        )

        stats, _ = graph_store.graph_stats(self.session_id, self.user_id)
        self.assertEqual((stats["entity_count"], stats["chunk_count"], stats["relationship_count"]), (2, 1, 1))

        graph, _ = graph_store.session_graph(self.session_id, self.user_id)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["edges"]), 1)

        graph_store.delete_session_graph(self.session_id, self.user_id)
        stats, _ = graph_store.graph_stats(self.session_id, self.user_id)
        self.assertEqual(stats["entity_count"], 0)

    def test_sessions_cannot_read_each_other(self):
        other_session = f"test-{uuid4().hex}"
        graph_store.upsert_entities(
            self.session_id, self.user_id,
            [{"name": "Private Fact", "type": "Concept", "description": "secret"}], [vector(1.0)],
        )
        try:
            rows, _ = graph_store.search_entities(other_session, self.user_id, vector(1.0), 5)
            self.assertEqual(rows, [])
        finally:
            graph_store.delete_session_graph(other_session, self.user_id)

    def test_every_query_template_is_valid_cypher(self):
        from graphragapp.router import QUERY_TEMPLATES

        for template_id, template in QUERY_TEMPLATES.items():
            with self.subTest(template=template_id):
                graph_store._run(template["cypher"], {"session_id": self.session_id, "user_id": self.user_id})


EXTRACTED = {
    "entities": [
        {"name": "Ada Lovelace", "type": "Person", "description": "Mathematician"},
        {"name": "Analytical Engine", "type": "Technology", "description": "Mechanical computer"},
    ],
    "relationships": [
        {"source": "Ada Lovelace", "target": "Analytical Engine", "type": "WROTE_ABOUT", "description": "Notes"},
    ],
}


@unittest.skipUnless(settings.neo4j_uri and settings.neo4j_password, "Neo4j is not configured")
class GraphRagStreamingTest(unittest.TestCase):
    """Drives the real streaming endpoints with mocked LLM and embedding calls."""

    def setUp(self):
        self.user_id = "stream-user"
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch.object(database, "DATABASE_PATH", Path(self.directory.name) / "graph_rag.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        database.initialize()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[graph_rag_user_id] = lambda: self.user_id
        self.client = TestClient(app)
        self.session_id = None

    def tearDown(self):
        if self.session_id:
            graph_store.delete_session_graph(self.session_id, self.user_id)

    def _events(self, response):
        self.assertEqual(response.status_code, 200)
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    def test_upload_streams_graph_construction_then_question_is_answered(self):
        created = self.client.post(
            "/graph-rag/sessions",
            json={"provider": "gemini", "model": "gemini-flash-lite-latest", "embedding_model": "gemini-embedding-001"},
        )
        self.assertEqual(created.status_code, 201)
        self.session_id = created.json()["id"]

        embeddings = lambda _key, _model, texts, _task: [vector(1.0) for _ in texts]
        with patch("graphragapp.pipeline.extract_graph", return_value=EXTRACTED), \
             patch("graphragapp.pipeline.embed_texts", side_effect=embeddings), \
             patch("graphragapp.router.bucket_storage.upload"):
            response = self.client.post(
                f"/graph-rag/sessions/{self.session_id}/documents",
                files={"file": ("history.txt", b"Ada Lovelace wrote notes on the Analytical Engine.", "text/plain")},
                data={
                    "provider": "gemini", "api_key": "test-key-value", "model": "gemini-flash-lite-latest",
                    "embedding_api_key": "test-key-value", "embedding_model": "gemini-embedding-001",
                },
            )
            events = self._events(response)

        steps = [event["step"] for event in events]
        self.assertNotIn("error", steps, msg=str(events))
        self.assertEqual(steps[0], "start")
        for expected in ("chunked", "extracted", "embedded", "graph-write", "graph-complete"):
            self.assertIn(expected, steps)

        final = events[-1]
        self.assertEqual(final["stats"]["entity_count"], 2)
        self.assertEqual(final["stats"]["relationship_count"], 1)
        self.assertEqual(final["document"]["filename"], "history.txt")
        write_event = next(event for event in events if event["step"] == "graph-write")
        self.assertTrue(any("MERGE" in statement for statement in write_event["cypher"]))

        with patch("graphragapp.pipeline.embed_texts", side_effect=embeddings), \
             patch("graphragapp.pipeline.chat", return_value="Ada Lovelace wrote about the Analytical Engine [1]."):
            response = self.client.post("/graph-rag/messages", json={
                "session_id": self.session_id, "provider": "gemini", "api_key": "test-key-value",
                "model": "gemini-flash-lite-latest", "embedding_api_key": "test-key-value",
                "embedding_model": "gemini-embedding-001", "message": "How are Ada and the engine related?",
                "top_k": 5, "hops": 2,
            })
            events = self._events(response)

        steps = [event["step"] for event in events]
        self.assertNotIn("error", steps, msg=str(events))
        self.assertEqual(
            steps,
            ["embed-question", "chunk-search", "entity-search", "traversal", "context", "answer"],
        )
        answer = events[-1]
        self.assertIn("Analytical Engine", answer["answer"])
        self.assertEqual(answer["citations"][0]["filename"], "history.txt")
        self.assertTrue(any(row["relationship"] == "WROTE_ABOUT" for row in events[3]["rows"]))

        stored = self.client.get(f"/graph-rag/sessions/{self.session_id}").json()
        self.assertEqual([message["role"] for message in stored["messages"]], ["user", "assistant"])

    def test_upload_rejects_documents_over_three_megabytes(self):
        created = self.client.post(
            "/graph-rag/sessions",
            json={"provider": "gemini", "model": "gemini-flash-lite-latest", "embedding_model": "gemini-embedding-001"},
        )
        self.session_id = created.json()["id"]
        response = self.client.post(
            f"/graph-rag/sessions/{self.session_id}/documents",
            files={"file": ("big.txt", b"x" * (3 * 1024 * 1024 + 10), "text/plain")},
            data={
                "provider": "gemini", "api_key": "test-key-value", "model": "gemini-flash-lite-latest",
                "embedding_api_key": "test-key-value", "embedding_model": "gemini-embedding-001",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("3 MB", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
