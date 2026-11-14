"""
Debug RAG retrieval for a single question.

Prints the question as received, the embedding model in use, the top-N chunks
with their raw vector / keyword scores, the configured floor and *where* the
"isn't in the uploaded material" decision is taken.

Usage (from the repo root):

    python backend/scripts/debug_retrieval.py "What is photosynthesis?"
    python backend/scripts/debug_retrieval.py "प्रकाश संश्लेषण क्या है?" --chapter 3
    python backend/scripts/debug_retrieval.py "..." --no-rewrite --top 20

Run the same command with an English and a non-English question against the same
chapter to compare the scores.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.ask import (  # noqa: E402
    NOT_IN_MATERIAL_MARKER,
    looks_non_english,
    retrieve_scored,
    select_context_chunks,
)
from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.services.embedding_service import embedding_service  # noqa: E402
from app.services.llm_service import get_llm_service  # noqa: E402


def build_queries(question: str, allow_rewrite: bool) -> list[str]:
    """Return the query phrasings used for retrieval (original, plus translation)."""
    queries = [question]
    if not allow_rewrite or not looks_non_english(question):
        return queries
    try:
        rewritten = (get_llm_service().rewrite_query(question) or "").strip()
    except Exception as exc:  # translation is best-effort
        print(f"  (query rewrite failed: {exc})")
        return queries
    if rewritten and rewritten.lower() != question.strip().lower():
        queries.append(rewritten)
        print(f"  Rewritten query (for retrieval): {rewritten}")
    else:
        print("  (rewrite produced no change — the active LLM provider may be 'mock')")
    return queries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Debug RAG retrieval for a question.")
    parser.add_argument("question", help="The student question to retrieve for.")
    parser.add_argument("--chapter", type=int, default=None, help="Restrict to a chapter id.")
    parser.add_argument("--page", type=int, default=None, help="Current reader page (page boost).")
    parser.add_argument("--top", type=int, default=10, help="How many chunks to print.")
    parser.add_argument("--no-rewrite", action="store_true", help="Skip translating the question.")
    args = parser.parse_args(argv)

    print("=" * 78)
    print(f"Question (as received) : {args.question}")
    print(f"Embedding model in use : {embedding_service.active_model_name} "
          f"(real: {embedding_service.is_real_model}, dimension {embedding_service.dimension})")
    print(f"Similarity floor       : {settings.SIMILARITY_THRESHOLD}")
    print(f"Chapter / page filter  : chapter={args.chapter} page={args.page}")

    queries = build_queries(args.question, allow_rewrite=not args.no_rewrite)

    db = SessionLocal()
    try:
        scored, meta = retrieve_scored(db, queries, args.chapter, args.page)
    finally:
        db.close()

    print(f"Candidate chunks       : {meta['candidate_count']} "
          f"(dimension-mismatched/stale: {meta['dimension_mismatch_chunks']})")
    print("-" * 78)
    print(f"{'rank':>4} {'chunk':>6} {'vector':>9} {'keyword':>9} {'score':>9}  preview")
    for rank, item in enumerate(scored[: args.top], start=1):
        preview = (item["chunk"].content or "").replace("\n", " ")[:44]
        print(
            f"{rank:>4} {item['chunk'].id:>6} {item['v_sim']:>9.4f} {item['l_sim']:>9.4f} "
            f"{item['relevance']:>9.4f}  {preview!r}"
        )
    if not scored:
        print("  (no chunks retrieved)")
    print("-" * 78)

    matched, below_threshold = select_context_chunks(scored)
    if not scored:
        print("Decision point: NO MATERIAL — returns \"isn't in the uploaded material\" "
              "(nothing to retrieve).")
    elif below_threshold:
        print(f"Decision point: every chunk is below the floor ({settings.SIMILARITY_THRESHOLD}); "
              f"best chunk #{matched[0]['chunk'].id} is still passed to the LLM "
              f"(rank-based fallback — the score never decides alone).")
    else:
        ids = [item["chunk"].id for item in matched]
        print(f"Decision point: {len(matched)} chunk(s) at/above the floor passed to the LLM: {ids}")

    print(f"Final grounding: set to false ONLY when the LLM replies with {NOT_IN_MATERIAL_MARKER!r}.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
