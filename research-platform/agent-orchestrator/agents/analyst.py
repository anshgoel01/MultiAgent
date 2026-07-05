# agent-orchestrator/agents/analyst.py
import logging
import os
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

try:
    llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        api_key=os.getenv('GROQ_API_KEY'),
        temperature=0.2,
        max_tokens=800
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM: {str(e)}")
    llm = None


def _trim_and_deduplicate(sources: list[str], max_chars: int = 4000) -> str:
    """Remove duplicate chunks and cap total context size."""
    seen = set()
    unique = []
    for chunk in sources:
        key = chunk[:120].strip()
        if key not in seen:
            seen.add(key)
            unique.append(chunk)

    context = '\n---\n'.join(unique)
    if len(context) > max_chars:
        context = context[:max_chars] + "\n[Context trimmed for length]"
    return context, len(unique)


def analyst_agent(state: dict) -> dict:
    """Analyze research material and extract key findings."""
    try:
        if llm is None:
            logger.error("[Analyst] LLM not initialized")
            return {'findings': [], 'error': 'LLM not available'}

        retrieved = state.get('retrieved', [])
        web_results = state.get('web_results', [])
        query = state.get('query', '')

        all_sources = retrieved + web_results
        if not all_sources:
            logger.warning("[Analyst] No sources to analyze")
            return {'findings': [], 'status': 'analyzed', 'error': 'No sources found'}

        context, source_count = _trim_and_deduplicate(all_sources)
        logger.info(f"[Analyst] Analyzing {source_count} unique sources for: {query[:100]}")

        prompt = f'''You are a rigorous research analyst. Analyze the sources below for this query:

Query: {query}

Sources:
{context}

Extract 6-8 key findings. For each finding you MUST include:
- A specific, concrete claim (include numbers/data where available)
- The source URL or name (write "Source: ..." at the end)
- Confidence level: HIGH (multiple sources agree), MED (single source), LOW (inferred)

Format each finding exactly like this:
1. [Finding text with specific data]. Source: [url or name]. Confidence: HIGH/MED/LOW

Rules:
- Only include findings directly supported by the sources
- Do not repeat the same point twice
- Prefer findings with specific numbers, dates, or named entities
- If sources contradict each other, note it as a finding
-Avoid generating findings that communicate the same idea.
-Merge similar evidence into one stronger finding.'''

        response = llm.invoke(prompt)

        if not response or not hasattr(response, 'content'):
            logger.warning("[Analyst] Empty response from LLM")
            return {'findings': [], 'status': 'analyzed', 'error': 'Empty LLM response'}

        # Filter to only numbered findings, skip blank lines and headers
        findings = [
            line.strip()
            for line in response.content.split('\n')
            if line.strip() and line.strip()[0].isdigit()
        ]

        if not findings:
            # Fallback — take all non-empty lines if numbered parsing fails
            findings = [line.strip() for line in response.content.split('\n') if line.strip()]

        logger.info(f"[Analyst] Extracted {len(findings)} findings")
        return {'findings': findings, 'status': 'analyzed'}

    except Exception as e:
        logger.error(f"[Analyst] Error during analysis: {str(e)}", exc_info=True)
        return {'findings': [], 'error': str(e)}