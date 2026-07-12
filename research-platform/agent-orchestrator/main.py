# agent-orchestrator/main.py
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from collections import OrderedDict
from typing import Optional

import httpx
# pyrefly: ignore [missing-import]
from fastapi import BackgroundTasks, FastAPI, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
# pyrefly: ignore [missing-import]
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import Config
from graph import ResearchState, research_graph
from langchain_groq import ChatGroq
from agents.intent_classifier import classify_intent
from agents.followup_answerer import followup_answerer

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    gatekeeper_llm = ChatGroq(
        model=os.getenv('GROQ_MODEL', 'llama-3.1-8b-instant'),
        api_key=os.getenv('GROQ_API_KEY'),
        temperature=0.0,
        max_tokens=256,
    )
except Exception as e:
    logger.error(f"Failed to initialize Groq LLM for gatekeeper: {str(e)}")
    gatekeeper_llm = None

app = FastAPI(title="Agent Orchestrator")

app.add_middleware(
    CORSMiddleware,
allow_origins=[
    "http://localhost:5173",
    "http://localhost:5174", 
    "http://localhost:5175",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:5175",
],
allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory query cache: hash -> report string
MAX_CACHE_ENTRIES = 100
_report_cache: OrderedDict[str, str] = OrderedDict()


def _normalize_query(query: str) -> str:
    normalized = re.sub(r"\s+", " ", query.strip().lower())
    return normalized.rstrip(" .!?;:,")


def _cache_key(query: str) -> str:
    normalized_query = _normalize_query(query)
    return hashlib.md5(normalized_query.encode("utf-8")).hexdigest()


def _get_cached_report(query: str) -> Optional[str]:
    key = _cache_key(query)
    if key in _report_cache:
        _report_cache.move_to_end(key)
        return _report_cache[key]
    return None


def _store_cached_report(query: str, report: str) -> None:
    key = _cache_key(query)
    if key in _report_cache:
        _report_cache.move_to_end(key)
    _report_cache[key] = report
    while len(_report_cache) > MAX_CACHE_ENTRIES:
        _report_cache.popitem(last=False)


@app.on_event("startup")
def startup_validation():
    logger.info("=== Agent Orchestrator Startup ===")
    
    import time
    from db_init import init_database
    for attempt in range(5):
        try:
            if init_database():
                logger.info("Database ready")
                break
            else:
                logger.warning(f"DB not ready, attempt {attempt+1}/5")
        except Exception as e:
            logger.warning(f"DB not ready, attempt {attempt+1}/5: {e}")
        time.sleep(4)
    else:
        logger.error("Could not connect to DB")
        sys.exit(1)

    if not Config.validate_on_startup():
        logger.critical("Environment validation failed - cannot start")
        sys.exit(1)
    if not research_graph:
        logger.critical("Research graph initialization failed - cannot start")
        sys.exit(1)
    logger.info("Startup validation passed")


class RunResearchRequest(BaseModel):
    task_id: str
    query: str
    previous_report: Optional[str] = None
    history: Optional[list[dict]] = None


class RunResearchResponse(BaseModel):
    task_id: str
    status: str
    message: str
    error: Optional[str] = None


@app.get("/health")
def health():
    return {"service": "orchestrator", "status": "ok", "cache_size": len(_report_cache)}


@app.post("/run")
async def run_research(req: RunResearchRequest, background_tasks: BackgroundTasks):
    """Start research workflow. Returns cached result immediately if available."""
    if not research_graph:
        raise HTTPException(500, "Graph initialization failed")
    if not req.query or not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")

    query_preview = req.query.strip()[:80]
    has_context = bool(req.previous_report and req.previous_report.strip())
    if not has_context:
        cached_report = _get_cached_report(req.query)
        if cached_report is not None:
            logger.info(f"[Cache] HIT for query: {query_preview}")
            background_tasks.add_task(_resolve_from_cache, req.task_id, cached_report)
            return {"ok": True, "task_id": req.task_id, "cached": True}

    logger.info(f"[Cache] MISS for query: {query_preview} - running pipeline")
    background_tasks.add_task(execute_graph, req.task_id, req.query, req.previous_report, req.history)
    return {"ok": True, "task_id": req.task_id, "cached": False}


async def _resolve_from_cache(task_id: str, report: str):
    """Mark a task DONE immediately using a cached report."""
    task_service_url = os.getenv("TASK_SERVICE_URL")
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{task_service_url}/tasks/{task_id}",
                json={"status": "DONE", "report": report},
                timeout=10.0,
            )
        logger.info(f"Task {task_id} resolved from cache")
    except Exception as e:
        logger.error(f"Failed to resolve cached task {task_id}: {e}")


async def _update_task(task_id: str, status: str, report: str = None, task_type: Optional[str] = None):
    """Helper to PATCH task-service."""
    task_service_url = os.getenv("TASK_SERVICE_URL")
    payload = {"status": status}
    if report is not None:
        payload["report"] = report
    if task_type is not None:
        payload["task_type"] = task_type
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{task_service_url}/tasks/{task_id}",
                json=payload,
                timeout=10.0,
            )
    except Exception as e:
        logger.warning(f"Could not update task {task_id} to {status}: {e}")


async def execute_graph(task_id: str, query: str, previous_report: Optional[str] = None, history: Optional[list[dict]] = None):
    """Execute the LangGraph pipeline and persist results."""
    query_preview = query.strip()[:80]
    has_context = bool(previous_report and previous_report.strip())
    if not has_context:
        cached_report = _get_cached_report(query)
        if cached_report is not None:
            logger.info(f"[Cache] HIT for query: {query_preview} - skipping pipeline")
            await _update_task(task_id, "DONE", cached_report)
            return

    logger.info(f"[Cache] MISS for query: {query_preview} - running pipeline")
    await _update_task(task_id, "RUNNING")

    if previous_report and str(previous_report).strip():
        intent = classify_intent(query, previous_report)
        logger.info(f"[IntentClassifier] {intent} for task {task_id}")
        if intent == 'FOLLOWUP':
            logger.info(f"[Followup] Short-circuiting graph for task {task_id}")
            answer = followup_answerer(query=query, previous_report=previous_report, history=history)
            await _update_task(task_id, "DONE", answer, task_type="followup")
            return

    # Gatekeeper check
    is_valid = True
    friendly_message = "That doesn't look like a research question — try asking something like 'What are the latest trends in X?' or 'Compare A vs B.'"
    
    if gatekeeper_llm is None:
        logger.error("[Gatekeeper] LLM not initialized, proceeding with pipeline as fallback")
    else:
        try:
            prompt = f"""You are a gatekeeper for a research assistant.
Your job is to classify the user query.
Is the following query a genuine research/informational question, or is it just a greeting, chit-chat, profanity/abuse, or meaningless input?

Query: {query}

Respond with exactly one word: VALID or INVALID."""
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, gatekeeper_llm.invoke, prompt)
            raw = str(response.content).strip().upper() if response and hasattr(response, 'content') else ''
            
            if 'INVALID' in raw:
                is_valid = False
            elif 'VALID' in raw:
                is_valid = True
            else:
                logger.warning(f"[Gatekeeper] Unparseable response: {raw!r} — defaulting to VALID")
                is_valid = True
        except Exception as e:
            logger.error(f"[Gatekeeper] Error during classification: {str(e)} - defaulting to VALID", exc_info=True)
            is_valid = True

    if not is_valid:
        logger.info(f"[Gatekeeper] REJECTED: {query}")
        _store_cached_report(query, friendly_message)
        await _update_task(task_id, "DONE", friendly_message)
        return

    logger.info(f"[Gatekeeper] ACCEPTED: {query}")

    try:
        logger.info(f"Starting research workflow for task {task_id}")
        initial_state: ResearchState = {
            "task_id": task_id,
            "query": query,
            "subtasks": [],
            "retrieved": [],
            "web_results": [],
            "findings": [],
            "critic_retries": 0,
            "report": None,
            "status": "running",
            "error": None,
        }

        loop = asyncio.get_event_loop()
        final_state = await loop.run_in_executor(None, research_graph.invoke, initial_state)
        report = final_state.get("report") or "No report generated"

        _store_cached_report(query, report)
        logger.info(
            f"[Cache] STORED for query: {query_preview} (cache size: {len(_report_cache)})"
        )

        await _update_task(task_id, "DONE", report, task_type="research")
        logger.info(f"Task {task_id} completed successfully")

    except Exception as e:
        logger.error(f"Workflow error for task {task_id}: {e}")
        await _update_task(task_id, "FAILED", str(e))


@app.get("/stream/{task_id}")
async def stream_progress(task_id: str):
    """Stream task status changes to the browser over SSE."""
    task_service_url = os.getenv("TASK_SERVICE_URL")

    async def event_gen():
        prev_status = None
        for _ in range(150):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{task_service_url}/tasks/{task_id}",
                        timeout=10.0,
                    )
                    response.raise_for_status()
                    task_data = response.json()
            except Exception as e:
                logger.warning(f"Unable to fetch task {task_id}: {e}")
                task_data = {"task_id": task_id, "status": "FAILED", "report": str(e)}

            if task_data.get("status") != prev_status:
                yield f"data: {json.dumps(task_data)}\n\n"
                prev_status = task_data.get("status")

            if task_data.get("status") in {"DONE", "FAILED"}:
                break

            await asyncio.sleep(2.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")