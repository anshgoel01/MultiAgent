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
        max_tokens=512,
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM for follow-up answerer: {str(e)}")
    llm = None


def followup_answerer(query: str, previous_report: Optional[str], history: Optional[list[dict]] = None) -> str:
    """Answer a follow-up query using only the previous report and prior chat history."""
    if llm is None:
        logger.error("[FollowupAnswerer] LLM not initialized")
        return "I couldn't generate a follow-up answer right now."

    previous_report_text = previous_report or ''
    history_text = ''
    if history:
        history_text = '\n'.join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in history
            if item.get('content')
        )

    prompt = f'''You are a helpful follow-up assistant. Answer the new user query using only the previous report and prior chat context.

Previous report:
{previous_report_text or 'No previous report provided.'}

Prior conversation:
{history_text or 'No prior conversation provided.'}

New query:
{query}

Provide a concise direct answer in plain text or markdown. Do not use the full report format.'''

    try:
        logger.info(f"[FollowupAnswerer] Answering follow-up query: {query[:120]}")
        response = llm.invoke(prompt)
        return str(response.content).strip() if response and hasattr(response, 'content') else 'I could not produce a follow-up answer.'
    except Exception as e:
        logger.error(f"[FollowupAnswerer] Error during answer generation: {str(e)}", exc_info=True)
        return "I couldn't generate a follow-up answer right now."
