# agent-orchestrator/main.py
import asyncio
import hashlib
import json
import logging
import os
import sys
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import Config
from graph import ResearchState, research_graph

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory query cache: hash -> report string
_report_cache: dict[str, str] = {}


def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


@app.on_event("startup")
def startup_validation():
    logger.info("=== Agent Orchestrator Startup ===")
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

    # Check cache first
    key = _cache_key(req.query)
    if key in _report_cache:
        logger.info(f"Cache hit for task {req.task_id} — returning instantly")
        background_tasks.add_task(_resolve_from_cache, req.task_id, _report_cache[key])
        return {"ok": True, "task_id": req.task_id, "cached": True}

    background_tasks.add_task(execute_graph, req.task_id, req.query)
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


async def _update_task(task_id: str, status: str, report: str = None):
    """Helper to PATCH task-service."""
    task_service_url = os.getenv("TASK_SERVICE_URL")
    payload = {"status": status}
    if report is not None:
        payload["report"] = report
    try:
        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{task_service_url}/tasks/{task_id}",
                json=payload,
                timeout=10.0,
            )
    except Exception as e:
        logger.warning(f"Could not update task {task_id} to {status}: {e}")


async def execute_graph(task_id: str, query: str):
    """Execute the LangGraph pipeline and persist results."""
    await _update_task(task_id, "RUNNING")

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

        final_state = research_graph.invoke(initial_state)
        report = final_state.get("report") or "No report generated"

        # Store in cache for future identical queries
        _report_cache[_cache_key(query)] = report
        logger.info(f"Cached report for query (cache size: {len(_report_cache)})")

        await _update_task(task_id, "DONE", report)
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