"""Ingest CLI:argparse + load manifest.yaml + IngestPipeline + tqdm progress."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from tqdm.auto import tqdm

from app.kb.ingest.cache import ChunkEmbedCache, default_cache_path
from app.kb.ingest.pipeline import DocSpec, IngestPipeline
from app.kb.ingest.state import IngestState, default_state_path
from app.services.embedding_factory import build_embedding_service_from_env
from app.services.milvus_client import (
    COLLECTION_FINANCIAL,
    COLLECTION_POLICY,
    COLLECTION_RESEARCH,
    MilvusKbClient,
)
from app.services.pdf_parser_factory import build_pdf_parser_from_env


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="v0.7 KB ingest CLI")
    p.add_argument(
        "--collection", choices=["research", "financial", "policy"], help="collection short name"
    )
    p.add_argument("--pdf-dir", type=Path, help="root dir of PDFs to ingest")
    p.add_argument("--doc-id", help="specific doc to (re-)ingest")
    p.add_argument("--all", action="store_true", help="ingest all 3 collections")
    p.add_argument("--force", action="store_true", help="force re-ingest, skip incremental check")
    p.add_argument(
        "--dry-run", action="store_true", help="parse + chunk only, skip embedding + Milvus"
    )
    p.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/sample_corpus/manifest.yaml"),
        help="manifest yaml relative to backend/",
    )
    return p.parse_args(argv)


def _collection_full(short: str) -> str:
    return {
        "research": COLLECTION_RESEARCH,
        "financial": COLLECTION_FINANCIAL,
        "policy": COLLECTION_POLICY,
    }[short]


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return list(data.get("docs", []))


async def _run_ingest(args: argparse.Namespace) -> int:
    docs_meta = _load_manifest(args.manifest)

    # Filter docs based on args
    if args.all:
        target_docs = docs_meta
    elif args.collection and args.doc_id:
        target_docs = [
            d
            for d in docs_meta
            if d.get("source_type") == args.collection and d.get("doc_id") == args.doc_id
        ]
    elif args.collection:
        target_docs = [d for d in docs_meta if d.get("source_type") == args.collection]
    else:
        print("Must specify --all or --collection (with optional --doc-id)", file=sys.stderr)
        return 1

    if not target_docs:
        print("No docs match filter", file=sys.stderr)
        return 1

    # Build specs
    specs: list[DocSpec] = []
    for d in target_docs:
        specs.append(
            DocSpec(
                doc_id=d["doc_id"],
                pdf_path=Path(d["pdf_path"]),
                collection=_collection_full(d["source_type"]),
                source_type=d["source_type"],
                metadata=d.get("metadata", {}),
            )
        )

    if args.dry_run:
        # Dry-run path:只 parse + chunk,不调 embedding / Milvus
        from app.kb.chunkers.router import chunker_for

        parser = build_pdf_parser_from_env()
        embedding_for_router = build_embedding_service_from_env()  # 仅给 chunker_for 占位
        for spec in tqdm(specs, desc="dry-run"):
            doc = await parser.parse(spec.pdf_path)
            chunks = await chunker_for(
                spec.source_type, embedding_service=embedding_for_router
            ).chunk(doc)
            print(
                f"[dry-run] {spec.doc_id}: {len(chunks)} chunks,"
                f" {sum(c.tokens for c in chunks)} total tokens"
            )
        return 0

    # Real ingest path
    pdf_parser = build_pdf_parser_from_env()
    embedding = build_embedding_service_from_env()
    milvus = MilvusKbClient(
        host=os.environ.get("MILVUS_HOST", "127.0.0.1"),
        port=int(os.environ.get("MILVUS_PORT", "19530")),
    )
    await milvus.ensure_collections()

    state = IngestState(db_path=default_state_path())
    await state.init()
    cache = ChunkEmbedCache(db_path=default_cache_path())
    await cache.init()

    pipeline = IngestPipeline(
        pdf_parser=pdf_parser,
        embedding_service=embedding,
        milvus=milvus,
        state=state,
        cache=cache,
    )

    bar = tqdm(specs, desc="ingest")
    successes = 0
    skips = 0
    failures = 0
    for spec in bar:
        report = await pipeline.ingest_doc(spec, force=args.force)
        if report.skipped:
            skips += 1
        elif report.success:
            successes += 1
        else:
            failures += 1
        bar.set_postfix(ok=successes, skip=skips, fail=failures, hits=cache.stats["hits"])

    print(f"\n[done] success={successes} skip={skips} fail={failures}")
    print(f"cache hits={cache.stats['hits']} misses={cache.stats['misses']}")
    return 0 if failures == 0 else 2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    return asyncio.run(_run_ingest(args))


if __name__ == "__main__":
    sys.exit(main())
