from langchain_groq import ChatGroq
import os


def writer_agent(state: dict) -> dict:
    findings_text = '\n'.join(state.get('findings', []))
    query = state.get('query', '')
    
    logger.info(f"[Writer] Writing report for: {query[:80]}")

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
- Maximum 600 words total
- Use bold for key terms'''

    try:
        response = llm.invoke(prompt)
        logger.info("[Writer] Report generated successfully")
        return {'report': response.content, 'status': 'done'}
    except Exception as e:
        logger.error(f"[Writer] Error generating report: {str(e)}")
        return {'report': f'Report generation failed: {str(e)}', 'status': 'failed'}