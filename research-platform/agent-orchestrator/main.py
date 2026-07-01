# agent-orchestrator/main.py
import asyncio
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

# Setup logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Agent Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_validation():
    """Validate environment and dependencies on startup."""
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
    return {"service": "orchestrator", "status": "ok"}


@app.post("/run")
async def run_research(req: RunResearchRequest, background_tasks: BackgroundTasks):
    """Start the research workflow in the background and return immediately."""
    if not research_graph:
        logger.error("Research graph not initialized")
        raise HTTPException(500, "Graph initialization failed")

    if not req.query or not req.query.strip():
        raise HTTPException(400, "Query cannot be empty")

    try:
        background_tasks.add_task(execute_graph, req.task_id, req.query)
        return {"ok": True, "task_id": req.task_id}
    except Exception as e:
        logger.error(f"Failed to start research: {str(e)}")
        raise HTTPException(500, f"Failed to start research: {str(e)}")


async def execute_graph(task_id: str, query: str):
    """Execute the graph and update the task-service state."""
    task_service_url = os.getenv("TASK_SERVICE_URL")

    if not task_service_url:
        logger.error("TASK_SERVICE_URL is not configured")
        return

    async with httpx.AsyncClient() as client:
        try:
            await client.patch(
                f"{task_service_url}/tasks/{task_id}",
                json={"status": "RUNNING"},
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"Could not mark task {task_id} as RUNNING: {str(e)}")

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

        async with httpx.AsyncClient() as client:
            await client.patch(
                f"{task_service_url}/tasks/{task_id}",
                json={"status": "DONE", "report": report},
                timeout=10.0,
            )
        logger.info(f"Task {task_id} completed successfully")
    except Exception as e:
        logger.error(f"Workflow error for task {task_id}: {str(e)}")
        try:
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{task_service_url}/tasks/{task_id}",
                    json={"status": "FAILED", "report": str(e)},
                    timeout=10.0,
                )
        except Exception as update_error:
            logger.error(f"Failed to update task status: {str(update_error)}")


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
                logger.warning(f"Unable to fetch task {task_id}: {str(e)}")
                task_data = {"task_id": task_id, "status": "FAILED", "report": str(e)}

            if task_data.get("status") != prev_status:
                yield f"data: {json.dumps(task_data)}\n\n"
                prev_status = task_data.get("status")

            if task_data.get("status") in {"DONE", "FAILED"}:
                break

            await asyncio.sleep(2.0)

    return StreamingResponse(event_gen(), media_type="text/event-stream")