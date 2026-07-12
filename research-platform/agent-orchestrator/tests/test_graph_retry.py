import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph import build_research_graph


def test_retry_reruns_both_sources():
    calls = {"retriever": 0, "web_search": 0}

    def fake_retriever(state):
        calls["retriever"] += 1
        return {"retrieved": [f"chunk-{calls['retriever']}"]}

    def fake_web_search(state):
        calls["web_search"] += 1
        return {"web_results": [f"web-{calls['web_search']}"]}

    analyst_calls = 0
    def fake_analyst(state):
        nonlocal analyst_calls
        analyst_calls += 1
        return {"findings": [f"f{analyst_calls}"], "status": "analyzed"}

    verdicts = iter(["insufficient", "sufficient"])
    def fake_critic(state):
        v = next(verdicts)
        retries = state.get("critic_retries", 0) + 1
        return {"status": v, "critic_retries": retries}

    def fake_route(state):
        if state["status"] == "insufficient" and state["critic_retries"] <= 1:
            return "requery"
        return "writer"

    def fake_writer(state):
        return {"report": "done", "status": "done"}

    with patch("agents.retriever.retriever_agent", fake_retriever), \
         patch("agents.web_search.web_search_agent", fake_web_search), \
         patch("agents.analyst.analyst_agent", fake_analyst), \
         patch("agents.critic.critic_agent", fake_critic), \
         patch("agents.critic.route_after_critic", fake_route), \
         patch("agents.writer.writer_agent", fake_writer):
        graph = build_research_graph()
        final = graph.invoke({
            "query": "test", "task_id": "t1", "subtasks": ["s1"],
            "retrieved": [], "web_results": [], "findings": [],
            "critic_retries": 0, "report": None, "status": "running", "error": None
        })

    assert calls["retriever"] == 2
    assert calls["web_search"] == 2
    assert final["findings"] == ["f2"]
    assert final["report"] == "done"