# gateway-service/main.py
import httpx
import os
import logging
import sys
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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

class ResearchReq(BaseModel):
    query: str

class ResearchResponse(BaseModel):
    task_id: str
    message: str

# Async token verification
async def verify_token_async(authorization: str = Header(...)) -> str:
    """Verify JWT token from Authorization header (async-safe)."""
    try:
        if not authorization.startswith('Bearer '):
            logger.warning("Invalid authorization header format")
            raise HTTPException(401, 'Invalid authorization header format')
        
        token = authorization.replace('Bearer ', '')
        if token != 'demo-token':
            logger.warning(f"Invalid token attempt from user")
            raise HTTPException(401, 'Unauthorized')
        
        return token
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
async def research(req: ResearchReq, request: Request):
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
                json={'query': req.query},
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
                    json={'task_id': task_id, 'query': req.query},
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
async def poll_task(task_id: str, request: Request):
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