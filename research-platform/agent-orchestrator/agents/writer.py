from langchain_groq import ChatGroq
import os
import logging
import re

logger = logging.getLogger(__name__)
try:
    llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile'),
        api_key=os.getenv('GROQ_API_KEY')
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM: {str(e)}")
    llm = None


def get_length_instruction(query: str) -> str:
    query_lower = query.lower()
    
    # Check for numeric word counts (e.g., "100 words", "under 200 words", "in 150 words")
    match = re.search(r'(\d+)\s*words?', query_lower)
    if match:
        return f"Maximum {match.group(1)} words total"
        
    # Check for common phrases
    if "one paragraph" in query_lower or "one-paragraph" in query_lower or "single paragraph" in query_lower:
        return "Maximum 150 words total, written as a single paragraph (ignore standard multi-section format if necessary)"
        
    if "brief" in query_lower or "short" in query_lower:
        return "Maximum 200 words total"
        
    if "detailed" in query_lower or "in-depth" in query_lower or "in depth" in query_lower:
        return "Maximum 1200 words total (provide detailed explanations for each section)"
        
    return "Maximum 600 words total"


def writer_agent(state: dict) -> dict:
    if llm is None:
        logger.error("[Writer] LLM not initialized")
        return {'report': 'Report generation failed: LLM not available', 'status': 'failed'}
        
    findings_text = '\n'.join(state.get('findings', []))
    query = state.get('query', '')
    
    logger.info(f"[Writer] Writing report for: {query[:80]}")
    length_instruction = get_length_instruction(query)

    prompt = f'''You are a senior research analyst writing for a professional audience.

Research Query: {query}

Findings from research:
{findings_text}

Write a structured report using ONLY the findings above. Follow this format exactly:

## Executive Summary
2-3 sentences summarizing the key answer to the query. Be direct and specific.

## Key Findings
Numbered list. Each finding must include:
- The specific claim with data/numbers where available
- Source (if mentioned in findings)
- Confidence: HIGH / MED / LOW

## Analysis
2-3 paragraphs interpreting what the findings mean. Connect ideas across sources. 
Highlight agreements and contradictions between sources.

## Conclusion
1 paragraph. What is the bottom line answer to the query? What should the reader do or know?

Rules:
- No filler phrases like "it is worth noting" or "it is important to mention"
- No claims not supported by the findings above
- {length_instruction}
- Use bold for key terms'''

    try:
        response = llm.invoke(prompt)
        logger.info("[Writer] Report generated successfully")
        return {'report': response.content, 'status': 'done'}
    except Exception as e:
        logger.error(f"[Writer] Error generating report: {str(e)}")
        return {'report': f'Report generation failed: {str(e)}', 'status': 'failed'}