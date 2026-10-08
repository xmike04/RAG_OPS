#!/usr/bin/env python3
"""Fetch, validate, and deterministically normalize BEIR SciFact.

Only the Python standard library is required. The official BEIR archive publishes
an MD5 digest but not a SHA-256 digest, so the archive is checked against BEIR's
published byte size and MD5. Every prepared artifact is recorded with SHA-256 in
the generated manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import unicodedata
import urllib.request
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ARCHIVE_URL = (
    "https://public.ukp.informatik.tu-darmstadt.de/"
    "thakur/BEIR/datasets/scifact.zip"
)
ARCHIVE_BYTES = 2_816_079
ARCHIVE_MD5 = "5f7d1de60b170fc8027bb7898e2efca1"
DATASET_VERSION = "beir-scifact-5f7d1de60b170fc8027bb7898e2efca1"
EXPECTED_CORPUS = 5_183
EXPECTED_QUERIES = 1_109
EXPECTED_TEST_QUERIES = 300
EXPECTED_TEST_QRELS = 339
EXPECTED_TRAIN_QUERIES = 809
EXPECTED_TRAIN_QRELS = 919


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_archive(path: Path) -> None:
    size = path.stat().st_size
    if size != ARCHIVE_BYTES:
        raise ValueError(f"archive size mismatch: expected {ARCHIVE_BYTES}, got {size}")
    # MD5 is used only because it is the checksum published in the BEIR catalog.
    digest = file_digest(path, "md5")
    if digest != ARCHIVE_MD5:
        raise ValueError(f"archive MD5 mismatch: expected {ARCHIVE_MD5}, got {digest}")


def download_archive(destination: Path) -> None:
    request = urllib.request.Request(ARCHIVE_URL, headers={"User-Agent": "RAGOps-dataset/1"})
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)
    verify_archive(destination)


def safe_extract(archive: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"unsafe archive member: {member.filename}")
        bundle.extractall(destination)
    candidates = [path for path in destination.rglob("corpus.jsonl")]
    if len(candidates) != 1:
        raise ValueError("archive must contain exactly one corpus.jsonl")
    return candidates[0].parent


def normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json(value[key]) for key in sorted(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdecimal() else (1, value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number}: expected an object")
            records.append(normalize_json(value))
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            )
            output.write("\n")


def normalize_corpus(source: Path, destination: Path) -> set[str]:
    records = read_jsonl(source)
    if len(records) != EXPECTED_CORPUS:
        raise ValueError(f"expected {EXPECTED_CORPUS} corpus records, got {len(records)}")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for record in records:
        doc_id = str(record.get("_id", ""))
        if not doc_id or doc_id in ids:
            raise ValueError(f"invalid or duplicate corpus id: {doc_id!r}")
        if not isinstance(record.get("title"), str) or not isinstance(record.get("text"), str):
            raise TypeError(f"corpus record {doc_id} has an invalid title or text")
        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError(f"corpus record {doc_id} metadata must be an object")
        ids.add(doc_id)
        normalized.append(
            {
                "_id": doc_id,
                "title": record["title"],
                "text": record["text"],
                "metadata": metadata,
            }
        )
    normalized.sort(key=lambda record: id_key(record["_id"]))
    write_jsonl(destination, normalized)
    return ids


def normalize_queries(source: Path, destination: Path) -> set[str]:
    records = read_jsonl(source)
    if len(records) != EXPECTED_QUERIES:
        raise ValueError(f"expected {EXPECTED_QUERIES} query records, got {len(records)}")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for record in records:
        query_id = str(record.get("_id", ""))
        if not query_id or query_id in ids or not isinstance(record.get("text"), str):
            raise ValueError(f"invalid or duplicate query: {query_id!r}")
        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError(f"query {query_id} metadata must be an object")
        ids.add(query_id)
        normalized.append({"_id": query_id, "text": record["text"], "metadata": metadata})
    normalized.sort(key=lambda record: id_key(record["_id"]))
    write_jsonl(destination, normalized)
    return ids


def normalize_qrels(
    source: Path,
    destination: Path,
    corpus_ids: set[str],
    query_ids: set[str],
    *,
    split: str,
    expected_qrels: int,
    expected_queries: int,
) -> tuple[int, set[str]]:
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = [line.rstrip("\r\n").split("\t") for line in stream if line.strip()]
    if not rows or rows[0] != ["query-id", "corpus-id", "score"]:
        raise ValueError("qrels must have the standard BEIR header")
    qrels: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows[1:]:
        if len(row) != 3:
            raise ValueError(f"invalid qrel row: {row!r}")
        query_id, corpus_id, score_text = row
        pair = (query_id, corpus_id)
        if pair in seen:
            raise ValueError(f"duplicate qrel: {pair!r}")
        if query_id not in query_ids or corpus_id not in corpus_ids:
            raise ValueError(f"qrel references an unknown id: {pair!r}")
        score = int(score_text)
        if score <= 0:
            raise ValueError(f"qrel must have positive relevance: {row!r}")
        seen.add(pair)
        qrels.append((query_id, corpus_id, score))
    split_query_count = len({query_id for query_id, _, _ in qrels})
    if len(qrels) != expected_qrels or split_query_count != expected_queries:
        raise ValueError(
            f"expected {expected_qrels} qrels/{expected_queries} {split} queries, "
            f"got {len(qrels)}/{split_query_count}"
        )
    qrels.sort(key=lambda row: (id_key(row[0]), id_key(row[1]), row[2]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write("query-id\tcorpus-id\tscore\n")
        for query_id, corpus_id, score in qrels:
            output.write(f"{query_id}\t{corpus_id}\t{score}\n")
    return len(qrels), {query_id for query_id, _, _ in qrels}


def prepare(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    corpus_ids = normalize_corpus(source / "corpus.jsonl", output / "corpus.jsonl")
    query_ids = normalize_queries(source / "queries.jsonl", output / "queries.jsonl")
    test_qrel_count, test_query_ids = normalize_qrels(
        source / "qrels" / "test.tsv",
        output / "qrels" / "test.tsv",
        corpus_ids,
        query_ids,
        split="test",
        expected_qrels=EXPECTED_TEST_QRELS,
        expected_queries=EXPECTED_TEST_QUERIES,
    )
    train_qrel_count, train_query_ids = normalize_qrels(
        source / "qrels" / "train.tsv",
        output / "qrels" / "train.tsv",
        corpus_ids,
        query_ids,
        split="train",
        expected_qrels=EXPECTED_TRAIN_QRELS,
        expected_queries=EXPECTED_TRAIN_QUERIES,
    )
    if test_query_ids & train_query_ids:
        raise ValueError("train and test qrels contain overlapping query IDs")
    if test_query_ids | train_query_ids != query_ids:
        raise ValueError("train and test qrels do not partition the query set")
    metadata = {
        "dataset": "BEIR SciFact",
        "version": DATASET_VERSION,
        "official_archive": {
            "url": ARCHIVE_URL,
            "bytes": ARCHIVE_BYTES,
            "md5": ARCHIVE_MD5,
        },
        "catalog": {
            "url": "https://github.com/beir-cellar/beir",
            "revision": "ef83d29307061c65d04b035b4f4e7c18bd8374af",
        },
        "upstream_scifact": {
            "url": "https://github.com/allenai/scifact",
            "revision": "68b98a56d93e0f9da0d2aab4e6c3294699a0f72e",
        },
        "licenses": {
            "claims_and_annotations": "CC-BY-4.0",
            "corpus_abstracts": "ODC-By-1.0",
        },
        "records": {
            "corpus": len(corpus_ids),
            "queries_all_splits": len(query_ids),
            "test_queries_with_qrels": len(test_query_ids),
            "test_qrels": test_qrel_count,
            "train_queries_with_qrels": len(train_query_ids),
            "train_qrels": train_qrel_count,
        },
        "normalization": "NFC Unicode; LF; canonical field order; numeric identifier order",
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    artifacts = [
        output / "corpus.jsonl",
        output / "queries.jsonl",
        output / "qrels" / "test.tsv",
        output / "qrels" / "train.tsv",
        output / "metadata.json",
    ]
    with (output / "manifest.sha256").open("w", encoding="ascii", newline="\n") as manifest:
        for artifact in artifacts:
            manifest.write(f"{file_digest(artifact, 'sha256')}  {artifact.relative_to(output)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="already-extracted standard BEIR directory")
    parser.add_argument("--archive", type=Path, help="already-downloaded official archive")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "v1")
    args = parser.parse_args()
    if args.source_dir and args.archive:
        parser.error("choose only one of --source-dir and --archive")

    with tempfile.TemporaryDirectory(prefix="ragops-scifact-") as temporary:
        temporary_path = Path(temporary)
        if args.source_dir:
            source = args.source_dir
        else:
            archive = args.archive or temporary_path / "scifact.zip"
            if args.archive:
                verify_archive(archive)
            else:
                download_archive(archive)
            source = safe_extract(archive, temporary_path / "extracted")
        prepare(source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
