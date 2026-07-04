# agent-orchestrator/agents/retriever.py
import logging
from tools.vector_search import search_documents

logger = logging.getLogger(__name__)


def _deduplicate(chunks: list[str]) -> list[str]:
    """Remove duplicate chunks by fingerprinting first 120 chars."""
    seen = set()
    unique = []
    for chunk in chunks:
        key = chunk[:120].strip()
        if key not in seen:
            seen.add(key)
            unique.append(chunk)
    return unique


def retriever_agent(state: dict) -> dict:
    """Retrieve documents using vector search."""
    try:
        subtasks = state.get('subtasks', [])

        if not subtasks:
            logger.warning("[Retriever] No subtasks provided — skipping vector search")
            return {'retrieved': []}

        all_chunks = []

        # Search all subtasks (not just top 3), more chunks per search
        for subtask in subtasks:
            try:
                logger.info(f"[Retriever] Searching: {subtask[:100]}")
                results = search_documents.invoke({
                    'query': subtask,
                    'top_k': 5  # increased from 3
                })
                if results:
                    all_chunks.extend(results)
                    logger.info(f"[Retriever] +{len(results)} chunks")
            except Exception as e:
                logger.error(f"[Retriever] Error on subtask '{subtask[:60]}': {e}")
                continue

        # Deduplicate before returning
        unique_chunks = _deduplicate(all_chunks)

        logger.info(
            f"[Retriever] Done — {len(all_chunks)} raw chunks → "
            f"{len(unique_chunks)} unique after dedup"
        )
        return {'retrieved': unique_chunks}

    except Exception as e:
        logger.error(f"[Retriever] Unexpected error: {e}", exc_info=True)
        return {'retrieved': [], 'error': str(e)}