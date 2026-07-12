# gateway-service/main.py
import json
import httpx
import os
import logging
import sys
# pyrefly: ignore [missing-import]
from fastapi import FastAPI, HTTPException, Header, Depends, Request
# pyrefly: ignore [missing-import]
from fastapi.responses import StreamingResponse
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
# pyrefly: ignore [missing-import]
from slowapi import Limiter
# pyrefly: ignore [missing-import]
from slowapi.util import get_remote_address
# pyrefly: ignore [missing-import]
from slowapi.errors import RateLimitExceeded

# Setup rate limiter
limiter = Limiter(key_func=get_remote_address)

# Setup logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title='Gateway')

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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: HTTPException(
    status_code=429,
    detail="Rate limit exceeded. Maximum 10 requests per minute."
))

TASK_SVC = os.getenv('TASK_SERVICE_URL')
ORCH_SVC = os.getenv('ORCHESTRATOR_URL')
RATE_LIMIT = os.getenv('RATE_LIMIT', '10/minute')

# Validate environment on startup
@app.on_event("startup")
def startup_validation():
    """Validate required environment variables."""
    logger.info("=== Gateway Service Startup ===")
    
    if not TASK_SVC:
        logger.error("TASK_SERVICE_URL not set")
        sys.exit(1)
    if not ORCH_SVC:
        logger.error("ORCHESTRATOR_URL not set")
        sys.exit(1)
    
    logger.info(f"Task Service: {TASK_SVC}")
    logger.info(f"Orchestrator: {ORCH_SVC}")
    logger.info(f"Rate Limit: {RATE_LIMIT}")
    logger.info("Environment validation passed")

class HistoryItem(BaseModel):
    role: str
    content: str


class ResearchReq(BaseModel):
    query: str
    previous_report: Optional[str] = None
    history: Optional[list[HistoryItem]] = None

class ResearchResponse(BaseModel):
    task_id: str
    message: str

# Async token verification
async def verify_token_async(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = None
) -> str:
    """Verify auth token from Authorization header or token query parameter (async-safe)."""
    try:
        resolved_token = None
        if authorization:
            if not authorization.startswith('Bearer '):
                logger.warning("Invalid authorization header format")
                raise HTTPException(401, 'Invalid authorization header format')
            resolved_token = authorization.replace('Bearer ', '')
        elif token:
            resolved_token = token
        else:
            logger.warning("No authorization header or token query parameter provided")
            raise HTTPException(401, 'Missing token')
        
        expected_token = os.getenv("API_AUTH_TOKEN", "demo-token")
        if resolved_token != expected_token:
            logger.warning("Invalid token attempt from user")
            raise HTTPException(401, 'Unauthorized')
        
        return resolved_token
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        raise HTTPException(500, 'Token verification failed')

# Health check
@app.get("/health")
def health():
    return {"service": "gateway", "status": "ok"}

# Research initiation endpoint
@app.post('/research', response_model=ResearchResponse)
@limiter.limit(os.getenv('RESEARCH_RATE_LIMIT', '5/minute'))
async def research(req: ResearchReq, request: Request, token: str = Depends(verify_token_async)):
    """Initiate a new research task."""
    logger.info(f"New research request for query: {req.query[:100]}")
    
    if not req.query or not req.query.strip():
        logger.warning("Empty query received")
        raise HTTPException(400, 'Query cannot be empty')

    try:
        async with httpx.AsyncClient() as client:
            # 1. Create task in task service
            logger.info(f"Creating task for query: {req.query[:100]}")
            t = await client.post(
                f'{TASK_SVC}/tasks',
                json={
                    'query': req.query,
                    'previous_report': req.previous_report,
                    'history': [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in (req.history or [])],
                },
                timeout=10.0
            )
            if t.status_code != 201:
                logger.error(f"Task service error: {t.status_code} - {t.text[:200]}")
                raise HTTPException(500, f'Task service error: {t.status_code}')

            task_data = t.json()
            task_id = task_data['task_id']
            logger.info(f"Task created successfully: {task_id}")

            # 2. Kick off agents (fire-and-forget with timeout)
            try:
                await client.post(
                    f'{ORCH_SVC}/run',
                    json={
                        'task_id': task_id,
                        'query': req.query,
                        'previous_report': req.previous_report,
                        'history': [item.model_dump() if hasattr(item, 'model_dump') else item.dict() for item in (req.history or [])],
                    },
                    timeout=5.0
                )
                logger.info(f"Orchestrator started for task {task_id}")
            except httpx.TimeoutException:
                # Timeout is expected (fire-and-forget)
                logger.info(f"Orchestrator request timed out (expected) for task {task_id}")
            except Exception as e:
                logger.warning(f"Orchestrator request failed: {str(e)}")

            return ResearchResponse(
                task_id=task_id,
                message='Research started'
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating research: {str(e)}", exc_info=True)
        raise HTTPException(500, f'Failed to initiate research')

# Task polling endpoint
@app.get('/tasks/{task_id}')
@limiter.limit(os.getenv('POLL_RATE_LIMIT', '30/minute'))
async def poll_task(task_id: str, request: Request, token: str = Depends(verify_token_async)):
    """Poll task status and results."""
    if not task_id or not task_id.strip():
        raise HTTPException(400, 'Invalid task_id')

    try:
        async with httpx.AsyncClient() as client:
            logger.info(f"Polling task: {task_id}")
            r = await client.get(
                f'{TASK_SVC}/tasks/{task_id}',
                timeout=10.0
            )
            if r.status_code == 404:
                raise HTTPException(404, 'Task not found')
            if r.status_code != 200:
                raise HTTPException(500, f'Task service error: {r.text}')

            task_data = r.json()
            return task_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error polling task: {str(e)}")
        raise HTTPException(500, f'Failed to poll task: {str(e)}')

# SSE stream proxy endpoint
@app.get('/stream/{task_id}')
async def stream_task_progress(
    task_id: str,
    token: str = Depends(verify_token_async)
):
    """Proxy the SSE stream from agent-orchestrator, enforcing auth."""
    internal_token = os.getenv("INTERNAL_AUTH_TOKEN", "some_shared_internal_secret")
    headers = {"X-Internal-Token": internal_token}
    
    async def event_generator():
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "GET",
                    f"{ORCH_SVC}/stream/{task_id}",
                    headers=headers,
                    timeout=None
                ) as response:
                    if response.status_code != 200:
                        logger.error(f"Orchestrator stream returned status {response.status_code}")
                        yield f"data: {json.dumps({'status': 'FAILED', 'report': f'Orchestrator stream error: {response.status_code}'})}\n\n"
                        return
                    
                    async for line in response.aiter_lines():
                        yield line + "\n"
            except Exception as e:
                logger.error(f"Error proxying stream: {e}", exc_info=True)
                yield f"data: {json.dumps({'status': 'FAILED', 'report': f'Stream proxy error: {str(e)}'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )