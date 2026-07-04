# agent-orchestrator/agents/planner.py
import logging
import os
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

try:
    llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant'),
        api_key=os.getenv('GROQ_API_KEY'),
        temperature=0.3,
        max_tokens=1024
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM: {str(e)}")
    llm = None

def planner_agent(state: dict) -> dict:
    """Break down the research query into concrete subtasks."""
    try:
        if llm is None:
            logger.error("LLM not initialized")
            return {'subtasks': [], 'error': 'LLM not available'}
        
        query = state.get('query', '')
        
        if not query or not query.strip():
            logger.warning("Empty query provided to planner")
            return {'subtasks': [], 'error': 'Empty query'}
        
        logger.info(f"[Planner] Planning for query: {query[:100]}")
        
        prompt = f'''You are a research planner.
Break this query into 3-5 concrete subtasks:
Query: {query}
Return ONLY a numbered list of subtasks, nothing else.'''
        
        response = llm.invoke(prompt)
        
        if response and hasattr(response, 'content'):
            # Parse numbered list
            lines = response.content.split('\n')
            subtasks = [line.strip() for line in lines if line.strip() and (line.strip()[0].isdigit() or line.strip().startswith('-'))]
            
            logger.info(f"[Planner] Generated {len(subtasks)} subtasks")
            return {'subtasks': subtasks, 'status': 'planned'}
        else:
            logger.warning("[Planner] Empty response from LLM")
            return {'subtasks': [], 'error': 'Empty LLM response'}
            
    except Exception as e:
        logger.error(f"[Planner] Error during planning: {str(e)}", exc_info=True)
        return {'subtasks': [], 'error': str(e)}