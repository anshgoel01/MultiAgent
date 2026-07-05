# agent-orchestrator/agents/retriever.py
import logging
from tools.vector_search import search_documents

logger = logging.getLogger(__name__)


def _deduplicate(chunks: list[str]) -> list[str]:
    """Remove duplicate chunks by fingerprinting first 120 chars."""
    seen = set()
    unique = []
    for chunk in chunks:
        key = " ".join(
    chunk.lower().split()[:30]
)
        if key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


def _is_valid_chunk(chunk: str) -> bool:
    """Filter out the placeholder strings search_documents returns on failure
    (e.g. 'Error: Database connection failed', 'No documents found') so they
    don't get treated as real retrieved content."""
    return not chunk.startswith("Error:") and chunk != "No documents found"


def retriever_agent(state: dict) -> dict:
    """Retrieve documents using vector search."""
    try:
        subtasks = state.get('subtasks', [])

        if not subtasks:
            logger.warning("[Retriever] No subtasks provided — skipping vector search")
            return {'retrieved': [], 'status': 'skipped'}

        all_chunks = []

        for subtask in subtasks:
            try:
                logger.info(f"[Retriever] Searching: {subtask[:100]}")
                results = search_documents.invoke({
                    'query': subtask,
                    'top_k': 3
                })
                results = [r for r in results if _is_valid_chunk(r)]
                if results:
                    all_chunks.extend(results)
                    logger.info(f"[Retriever] +{len(results)} chunks")
            except Exception as e:
                logger.error(f"[Retriever] Error on subtask '{subtask[:60]}': {e}")
                continue

        unique_chunks = _deduplicate(all_chunks)

        logger.info(
            f"[Retriever] Done — {len(all_chunks)} raw chunks → "
            f"{len(unique_chunks)} unique after dedup"
        )
        return {'retrieved': unique_chunks, 'status': 'retrieved'}

    except Exception as e:
        logger.error(f"[Retriever] Unexpected error: {e}", exc_info=True)
        return {'retrieved': [], 'status': 'error', 'error': str(e)}