from types import SimpleNamespace
import unittest

from benchmarks.service import capture


class RuntimeCaptureTests(unittest.TestCase):
    def test_snapshot_exports_only_explicit_public_runtime_settings(self):
        public = getattr(capture, "public_settings", None)
        self.assertTrue(callable(public), "sanitized runtime capture is not implemented")
        settings = SimpleNamespace(
            environment="test", embedding_provider="local", embedding_model="deterministic-hash-v1",
            embedding_dimensions=384, reranker_provider="local", reranker_model="deterministic-overlap-v1",
            generation_provider="local", generation_model="extractive-local-v1", retrieval_rrf_k=60,
            retrieval_candidate_limit=100, max_document_bytes=2_000_000,
            api_key="private-key", database_url="postgresql://user:secret@database",
            openai_compatible_api_key="private-provider-key", redis_url="redis://:private@host",
        )
        result = public(settings)
        self.assertEqual(result["retrieval_rrf_k"], 60)
        self.assertEqual(result["embedding_dimensions"], 384)
        self.assertNotIn("private", str(result))
        self.assertNotIn("secret", str(result))
        self.assertNotIn("database_url", result)
        self.assertNotIn("api_key", result)


if __name__ == "__main__":
    unittest.main()
