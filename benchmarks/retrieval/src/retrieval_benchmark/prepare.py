"""Fetch, verify, and prepare the pinned BEIR SciFact test dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .dataset import load_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "dataset_manifest.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("dataset") != "BEIR SciFact":
        raise ValueError(f"invalid dataset manifest: {MANIFEST_PATH}")
    return value


def _download(url: str, destination: Path) -> None:
    """Download atomically, resuming a partial response when the server permits."""

    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "RAGOps-retrieval-benchmark/0.1"}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"dataset download failed with HTTP {exc.code}: {url}") from exc
    status = getattr(response, "status", 200)
    mode = "ab" if existing and status == 206 else "wb"
    with response, partial.open(mode) as stream:
        shutil.copyfileobj(response, stream, length=1024 * 1024)
    partial.replace(destination)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        uncompressed_bytes = sum(member.file_size for member in bundle.infolist())
        if uncompressed_bytes > 100 * 1024 * 1024:
            raise ValueError("dataset archive exceeds the 100 MiB extraction safety limit")
        for member in bundle.infolist():
            relative = PurePosixPath(member.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe path in dataset archive: {member.filename!r}")
            target = destination.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".part")
            with bundle.open(member) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output)
            temporary.replace(target)


def _find_beir_root(extracted: Path) -> Path:
    candidates = [extracted, *[path for path in extracted.iterdir() if path.is_dir()]]
    for candidate in candidates:
        if (
            (candidate / "corpus.jsonl").is_file()
            and (candidate / "queries.jsonl").is_file()
            and (candidate / "qrels" / "test.tsv").is_file()
        ):
            return candidate
    raise ValueError("archive does not contain the expected BEIR SciFact layout")


def _copy_dataset(source: Path, output: Path) -> None:
    for relative in (Path("corpus.jsonl"), Path("queries.jsonl"), Path("qrels/test.tsv")):
        source_file = source / relative
        if not source_file.is_file():
            raise FileNotFoundError(f"source dataset is missing {relative}")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        shutil.copyfile(source_file, temporary)
        temporary.replace(destination)


def _verify_prepared_files(output: Path, manifest: dict[str, Any]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, expected in manifest["prepared_files"].items():
        path = output / name
        digest = sha256_file(path)
        if digest != expected["sha256"]:
            raise ValueError(
                f"prepared file SHA256 mismatch for {name}: "
                f"expected {expected['sha256']}, got {digest}"
            )
        if path.stat().st_size != expected["bytes"]:
            raise ValueError(f"prepared file size mismatch for {name}")
        actual[name] = digest
    return actual


def prepare(
    output_dir: Path,
    *,
    archive: Path | None = None,
    source_dir: Path | None = None,
) -> dict[str, Any]:
    manifest = _load_manifest()
    output_dir.mkdir(parents=True, exist_ok=True)
    repository_dataset = PROJECT_ROOT.parent / "datasets/scifact/v1"
    if source_dir is None and archive is None and repository_dataset.is_dir():
        source_dir = repository_dataset
    if source_dir is not None:
        _copy_dataset(source_dir, output_dir)
        archive_sha256: str | None = None
        source = str(source_dir.resolve())
    else:
        archive_path = archive or (output_dir.parent / manifest["archive"]["filename"])
        if not archive_path.exists():
            _download(str(manifest["archive"]["url"]), archive_path)
        archive_sha256 = sha256_file(archive_path)
        expected = manifest["archive"].get("sha256")
        if expected is not None and archive_sha256 != expected:
            raise ValueError(f"archive SHA256 mismatch: expected {expected}, got {archive_sha256}")
        extracted = output_dir.parent / "scifact-extracted"
        _safe_extract(archive_path, extracted)
        _copy_dataset(_find_beir_root(extracted), output_dir)
        source = str(manifest["archive"]["url"])

    dataset = load_dataset(output_dir)
    files = _verify_prepared_files(output_dir, manifest)
    state: dict[str, Any] = {
        "schema_version": 1,
        "dataset": "BEIR SciFact",
        "split": "test",
        "source": source,
        "archive_sha256": archive_sha256,
        "dataset_fingerprint": dataset.fingerprint,
        "corpus_count": len(dataset.documents),
        "evaluated_query_count": len(dataset.queries),
        "files_sha256": files,
        "manifest_sha256": sha256_file(MANIFEST_PATH),
    }
    state_path = output_dir / "dataset_state.json"
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / ".cache/data/scifact")
    mutually_exclusive = parser.add_mutually_exclusive_group()
    mutually_exclusive.add_argument("--archive", type=Path, help="Use a local pinned archive")
    mutually_exclusive.add_argument(
        "--source-dir", type=Path, help="Copy an already prepared BEIR-layout dataset"
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        state = prepare(args.output_dir, archive=args.archive, source_dir=args.source_dir)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"preparation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(state, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
