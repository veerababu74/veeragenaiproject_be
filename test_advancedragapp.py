import unittest
from unittest.mock import Mock

from advancedragapp.pipeline import run_pipeline


class AdvancedRagPipelineTests(unittest.TestCase):
    def test_pipeline_exposes_queries_retrieval_and_final_context(self):
        chat = Mock(side_effect=[
            '{"rewritten_query":"What powers solar panels?","generated_queries":["How is sunlight converted?","Solar panel energy source"]}',
            "Solar panels convert sunlight into electricity [1].",
        ])
        embed = Mock(return_value=[[0.1], [0.2], [0.3], [0.4]])
        query = Mock(side_effect=lambda _user, _session, vector, _top_k: [{
            "document_id": "doc-1", "filename": "energy.txt", "position": 0,
            "text": "Solar panels convert sunlight into electricity.", "score": 0.91,
        }])

        answer, sources, trace = run_pipeline(
            "What gives solar panels energy?", "user-1", "session-1", "gemini",
            "llm-key", "gemini-test", "embed-key", "gemini-embedding-001", 3,
            [], chat_fn=chat, embed_fn=embed, query_fn=query,
        )

        self.assertIn("sunlight", answer)
        self.assertEqual(trace["rewritten_query"], "What powers solar panels?")
        self.assertEqual(len(trace["generated_queries"]), 2)
        self.assertEqual(len(trace["retrievals"]), 4)
        self.assertEqual(len(sources), 1)
        self.assertEqual(trace["context_quality"]["status"], "strong")
        self.assertIn("energy.txt", trace["final_context"])

    def test_weak_context_generates_fallback_and_reports_recovery(self):
        chat = Mock(side_effect=[
            '{"rewritten_query":"Rewritten","generated_queries":["Generated one","Generated two"]}',
            "Broader fallback query",
            "Recovered answer [1].",
        ])
        embed = Mock(side_effect=[[[0.1], [0.2], [0.3], [0.4]], [[0.5]]])
        weak = {"document_id": "weak", "filename": "notes.txt", "position": 0, "text": "Maybe relevant", "score": 0.1}
        strong = {"document_id": "strong", "filename": "facts.txt", "position": 1, "text": "Direct evidence", "score": 0.88}
        query = Mock(side_effect=[[weak], [weak], [weak], [weak], [strong]])

        _, _, trace = run_pipeline(
            "Question", "user-1", "session-1", "gemini", "llm-key", "model",
            "embed-key", "embedding-model", 3, [], chat_fn=chat, embed_fn=embed, query_fn=query,
        )

        self.assertEqual(trace["fallback_query"], "Broader fallback query")
        self.assertEqual(trace["context_quality"]["status"], "recovered")
        self.assertEqual(trace["retrievals"][-1]["type"], "fallback")


if __name__ == "__main__":
    unittest.main()
