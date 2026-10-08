from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"


class RepositoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BACKEND_PYTHON.exists():
            raise unittest.SkipTest(
                "backend virtual environment is absent; run make backend-install"
            )
        command = [
            str(BACKEND_PYTHON),
            "-c",
            (
                "import json; from ragops.main import create_app; "
                "print(json.dumps(create_app().openapi()))"
            ),
        ]
        result = subprocess.run(
            command,
            cwd=ROOT / "backend",
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"could not generate OpenAPI schema: {result.stderr}")
        cls.openapi = json.loads(result.stdout)

    def test_required_api_surface_is_published(self) -> None:
        expected = {
            "/health": {"get"},
            "/ready": {"get"},
            "/v1/documents": {"get", "post"},
            "/v1/ingestions/{job_id}": {"get"},
            "/v1/search": {"post"},
            "/v1/query": {"post"},
            "/v1/traces": {"get"},
            "/v1/ops/summary": {"get"},
        }
        paths = self.openapi.get("paths", {})
        for path, methods in expected.items():
            self.assertIn(path, paths)
            self.assertTrue(methods.issubset(paths[path]), f"{path} is missing {methods}")

    def test_search_and_query_require_workspace_scope(self) -> None:
        schemas = self.openapi["components"]["schemas"]
        for path in ("/v1/search", "/v1/query"):
            body = self.openapi["paths"][path]["post"]["requestBody"]
            schema_ref = body["content"]["application/json"]["schema"]["$ref"]
            schema_name = schema_ref.rsplit("/", 1)[-1]
            required = set(schemas[schema_name].get("required", []))
            self.assertIn("workspace_id", required, path)
            self.assertIn("query", required, path)

    def test_ingestion_job_lookup_requires_workspace_scope(self) -> None:
        operation = self.openapi["paths"]["/v1/ingestions/{job_id}"]["get"]
        parameters = {
            (parameter.get("name"), parameter.get("in")): parameter
            for parameter in operation.get("parameters", [])
        }
        workspace = parameters.get(("workspace_id", "query"))
        self.assertIsNotNone(workspace)
        self.assertTrue(workspace.get("required"))


class DocumentationContractTests(unittest.TestCase):
    def test_relative_markdown_links_resolve(self) -> None:
        markdown_files = [
            ROOT / "README.md",
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            *sorted((ROOT / "docs").glob("*.md")),
            ROOT / "evals" / "README.md",
        ]
        link_pattern = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
        missing: list[str] = []
        for markdown in markdown_files:
            for target in link_pattern.findall(markdown.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                relative = target.split("#", 1)[0]
                if relative and not (markdown.parent / relative).resolve().exists():
                    missing.append(f"{markdown.relative_to(ROOT)} -> {target}")
        self.assertEqual(missing, [], "broken documentation links:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
