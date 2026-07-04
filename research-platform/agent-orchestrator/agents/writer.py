from langchain_groq import ChatGroq
import os
 
llm = ChatGroq(model='llama-3.3-70b-versatile', api_key=os.getenv('GROQ_API_KEY'))

def writer_agent(state: dict) -> dict:
    findings_text = '\n'.join(state['findings'])
    prompt = f'''Write a professional research report for: {state['query']}
Based on these findings:
{findings_text}

Format:
## Executive Summary (2-3 sentences)
## Key Findings (numbered list with confidence levels)
## Analysis (2-3 paragraphs)
## Conclusion

Be specific, cite sources where mentioned in findings.'''
    response = llm.invoke(prompt)
    return {'report': response.content, 'status': 'done'}
