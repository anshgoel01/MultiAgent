# agent-orchestrator/graph.py
from typing import TypedDict, Annotated, Optional
from langgraph.graph import StateGraph, END
from operator import add
import logging

# Setup logging
logger = logging.getLogger(__name__)

# Define the state schema
class ResearchState(TypedDict):
    query: str
    task_id: str
    subtasks: Annotated[list[str], add]
    retrieved: Annotated[list[str], add]
    web_results: Annotated[list[str], add]
    findings: Annotated[list[str], add]
    critic_retries: int
    report: Optional[str]
    status: str
    error: Optional[str]

def build_research_graph():
    """Build the research agent orchestration graph."""
    from agents.planner import planner_agent
    from agents.retriever import retriever_agent
    from agents.web_search import web_search_agent
    from agents.analyst import analyst_agent
    from agents.critic import critic_agent, route_after_critic
    from agents.writer import writer_agent

    # Create the graph
    graph = StateGraph(ResearchState)

    # Add nodes
    graph.add_node("planner", planner_agent)
    graph.add_node("retriever", retriever_agent)
    graph.add_node("web_search", web_search_agent)
    graph.add_node("analyst", analyst_agent)
    graph.add_node("critic", critic_agent)
    graph.add_node("writer", writer_agent)
    graph.add_node("requery", lambda state: {}) 

    # Add edges for workflow
    # Start -> Planner
    graph.set_entry_point("planner")

    # Planner -> Retriever and WebSearch (parallel)
    graph.add_edge("planner", "retriever")
    graph.add_edge("planner", "web_search")
    
    graph.add_edge("requery", "retriever")          # <-- ADD
    graph.add_edge("requery", "web_search")   

    # Retriever -> Analyst
    graph.add_edge("retriever", "analyst")

    # WebSearch -> Analyst (converge)
    graph.add_edge("web_search", "analyst")

    # Analyst -> Critic -> Writer/Retriever
    graph.add_edge("analyst", "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "requery": "requery",
            "writer": "writer",
        },
    )

    # Writer -> End
    graph.add_edge("writer", END)

    # Compile the graph
    compiled_graph = graph.compile()
    logger.info("Research graph compiled successfully")
    return compiled_graph

# Initialize graph on module load
try:
    research_graph = build_research_graph()
except Exception as e:
    logger.error(f"Failed to build research graph: {e}")
    research_graph = None
