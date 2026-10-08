"""Strict readers for the BEIR JSONL/TSV interchange layout."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Document:
    doc_id: str
    title: str
    text: str

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.title.strip(), self.text.strip()) if part)


@dataclass(frozen=True, slots=True)
class Query:
    query_id: str
    text: str


@dataclass(frozen=True, slots=True)
class Dataset:
    documents: tuple[Document, ...]
    queries: tuple[Query, ...]
    qrels: dict[str, dict[str, int]]
    fingerprint: str


def load_dataset(root: Path) -> Dataset:
    corpus_path = root / "corpus.jsonl"
    queries_path = root / "queries.jsonl"
    qrels_path = root / "qrels" / "test.tsv"
    for path in (corpus_path, queries_path, qrels_path):
        if not path.is_file():
            raise FileNotFoundError(f"required BEIR file is missing: {path}")

    documents = tuple(load_documents(corpus_path))
    all_queries = {query.query_id: query for query in load_queries(queries_path)}
    qrels = load_qrels(qrels_path)
    # BEIR query files can include train/dev queries. Evaluate only IDs with test qrels.
    queries = tuple(all_queries[query_id] for query_id in sorted(qrels))
    missing_queries = sorted(set(qrels).difference(all_queries))
    if missing_queries:
        raise ValueError(f"qrels reference {len(missing_queries)} missing queries")
    corpus_ids = {document.doc_id for document in documents}
    missing_docs = {
        doc_id for rels in qrels.values() for doc_id in rels if doc_id not in corpus_ids
    }
    if missing_docs:
        raise ValueError(f"qrels reference {len(missing_docs)} missing corpus documents")
    if not documents or not queries:
        raise ValueError("benchmark dataset must contain documents and evaluated queries")
    return Dataset(
        documents=documents,
        queries=queries,
        qrels=qrels,
        fingerprint=_dataset_fingerprint(corpus_path, queries_path, qrels_path),
    )


def _jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object in {path}:{line_number}")
            yield line_number, value


def load_documents(path: Path) -> Iterator[Document]:
    seen: set[str] = set()
    for line_number, row in _jsonl(path):
        doc_id = str(row.get("_id", "")).strip()
        text = row.get("text")
        title = row.get("title", "")
        if not doc_id or not isinstance(text, str) or not isinstance(title, str):
            raise ValueError(f"invalid corpus record in {path}:{line_number}")
        if doc_id in seen:
            raise ValueError(f"duplicate corpus ID {doc_id!r}")
        seen.add(doc_id)
        yield Document(doc_id=doc_id, title=title, text=text)


def load_queries(path: Path) -> Iterator[Query]:
    seen: set[str] = set()
    for line_number, row in _jsonl(path):
        query_id = str(row.get("_id", "")).strip()
        text = row.get("text")
        if not query_id or not isinstance(text, str) or not text.strip():
            raise ValueError(f"invalid query record in {path}:{line_number}")
        if query_id in seen:
            raise ValueError(f"duplicate query ID {query_id!r}")
        seen.add(query_id)
        yield Query(query_id=query_id, text=text)


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        required = {"query-id", "corpus-id", "score"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"qrels must have tab-separated columns {sorted(required)}")
        for row in reader:
            query_id = row["query-id"].strip()
            doc_id = row["corpus-id"].strip()
            score = int(row["score"])
            if not query_id or not doc_id or score < 0:
                raise ValueError("qrels contain an invalid ID or negative relevance score")
            if doc_id in qrels.setdefault(query_id, {}):
                raise ValueError(f"duplicate qrel for query={query_id!r}, doc={doc_id!r}")
            qrels[query_id][doc_id] = score
    return {query_id: rels for query_id, rels in qrels.items() if any(rels.values())}


def _dataset_fingerprint(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()
