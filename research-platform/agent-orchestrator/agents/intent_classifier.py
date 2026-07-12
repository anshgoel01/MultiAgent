import logging
import os
from typing import Optional
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

try:
    llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant'),
        api_key=os.getenv('GROQ_API_KEY'),
        temperature=0.0,
        max_tokens=64,
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM for intent classifier: {str(e)}")
    llm = None


def classify_intent(query: str, previous_report: Optional[str]) -> str:
    """Classify whether the query is a fresh research topic or a follow-up."""
    if not previous_report or not str(previous_report).strip():
        logger.info("[IntentClassifier] No previous report provided; defaulting to NEW_TOPIC")
        return 'NEW_TOPIC'

    if llm is None:
        logger.error("[IntentClassifier] LLM not initialized; defaulting to NEW_TOPIC")
        return 'NEW_TOPIC'

    try:
        prompt = f'''You are a strict intent classifier. Determine whether the new user request is a fresh research topic or a follow-up to the previous report.

Previous report:
{previous_report}

New query:
{query}

Respond with exactly one word: NEW_TOPIC or FOLLOWUP.'''

        logger.info(f"[IntentClassifier] Classifying follow-up for query: {query[:120]}")
        response = llm.invoke(prompt)
        raw = str(response.content).strip().upper() if response and hasattr(response, 'content') else ''

        if 'FOLLOWUP' in raw:
            return 'FOLLOWUP'

        logger.info(f"[IntentClassifier] Unparseable response: {raw!r} — defaulting to NEW_TOPIC")
        return 'NEW_TOPIC'
    except Exception as e:
        logger.error(f"[IntentClassifier] Error during classification: {str(e)}", exc_info=True)
        return 'NEW_TOPIC'
