import logging
import os
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

try:
    llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        api_key=os.getenv('GROQ_API_KEY'),
        temperature=0.0,
        max_tokens=256,
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM for critic: {str(e)}")
    llm = None

MAX_CRITIC_RETRIES = 2


def critic_agent(state: dict) -> dict:
    """Judge whether the analyst findings are rich enough for a comprehensive report."""
    try:
        if llm is None:
            logger.error("[Critic] LLM not initialized")
            return {'status': 'insufficient', 'critic_retries': int(state.get('critic_retries', 0)) + 1}

        findings_text = '\n'.join(state.get('findings', []))
        query = state.get('query', '')
        retry_count = int(state.get('critic_retries', 0)) + 1

        logger.info(f"[Critic] Reviewing findings for query: {query[:120]} (attempt {retry_count})")

        prompt = f'''You are a strict research critic. Judge whether the following findings are sufficient to write a comprehensive report on this query:

Query: {query}

Findings:
{findings_text or 'No findings provided'}

Respond with exactly one word: SUFFICIENT or INSUFFICIENT.'''

        response = llm.invoke(prompt)
        content = str(response.content).strip().upper() if response and hasattr(response, 'content') else ''
        verdict = 'SUFFICIENT' if content == 'SUFFICIENT' else 'INSUFFICIENT'
        status = 'sufficient' if verdict == 'SUFFICIENT' else 'insufficient'

        logger.info(f"[Critic] Verdict: {status}")
        return {'status': status, 'critic_retries': retry_count}
    except Exception as e:
        logger.error(f"[Critic] Error during review: {str(e)}", exc_info=True)
        return {'status': 'insufficient', 'critic_retries': int(state.get('critic_retries', 0)) + 1, 'error': str(e)}


def route_after_critic(state: dict) -> str:
    """Route back to retriever when findings are thin, otherwise continue to writer."""
    status = state.get('status', '')
    retries = int(state.get('critic_retries', 0))

    if status == 'insufficient' and retries < MAX_CRITIC_RETRIES:
        logger.info(f"[Critic] Routing back to retriever after attempt {retries}")
        return 'retriever'

    logger.info(f"[Critic] Routing to writer after attempt {retries} with status {status}")
    return 'writer'
