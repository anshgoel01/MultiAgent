# task-service/main.py
import logging
import os
import sys
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db, test_db_connection, engine
from models import Task, Base

# Setup logging
logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
 
app = FastAPI(title='Task Service')
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models
class CreateTaskReq(BaseModel):
    query: str
    previous_report: Optional[str] = None
    history: Optional[list[dict]] = None
    task_type: Optional[str] = 'research'

class UpdateTaskReq(BaseModel):
    status: str
    report: Optional[str] = None
    task_type: Optional[str] = None

class TaskResponse(BaseModel):
    task_id: str
    query: str
    status: str
    report: Optional[str] = None
    task_type: Optional[str] = None

    class Config:
        from_attributes = True

# Initialize database tables and validate startup
@app.on_event("startup")
def startup_event():
    """Initialize database and validate environment on startup."""
    logger.info("=== Task Service Startup ===")
    
    # Validate environment
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)
    
    logger.info("Database URL validated")
    
    import time
    for attempt in range(5):
        try:
            Base.metadata.create_all(bind=engine)
            try:
                with engine.begin() as conn:
                    columns = {column['name'] for column in inspect(conn).get_columns('tasks')}
                    if 'task_type' not in columns:
                        conn.execute(text("ALTER TABLE tasks ADD COLUMN task_type VARCHAR DEFAULT 'research'"))
            except Exception as e:
                logger.warning(f"Task type migration skipped: {e}")
            if test_db_connection():
                logger.info("Database ready")
                break
        except Exception as e:
            logger.warning(f"DB not ready, attempt {attempt+1}/5: {e}")
            time.sleep(4)
    else:
        logger.error("Could not connect to DB")
        sys.exit(1)

# Health check endpoint
@app.get("/health")
def health():
    """Health check endpoint."""
    db_status = test_db_connection()
    return {
        "service": "task-service",
        "status": "ok" if db_status else "degraded",
        "database": "connected" if db_status else "disconnected"
    }

# Create task endpoint
@app.post('/tasks', status_code=201)
def create_task(req: CreateTaskReq, db: Session = Depends(get_db)):
    """Create a new research task."""
    try:
        if not req.query or not req.query.strip():
            raise HTTPException(400, 'Query cannot be empty')

        task = Task(query=req.query, task_type=req.task_type or 'research')
        db.add(task)
        db.commit()
        db.refresh(task)
        logger.info(f"Task created: {task.id}")

        return {
            'task_id': task.id,
            'status': task.status,
            'query': task.query,
            'task_type': task.task_type
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(500, f'Failed to create task: {str(e)}')

# Get task endpoint
@app.get('/tasks/{task_id}')
def get_task(task_id: str, db: Session = Depends(get_db)):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, 'Task not found')
        return {
            'task_id': task.id,
            'query': task.query,
            'status': task.status,
            'report': task.report,
            'task_type': task.task_type
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving task: {str(e)}")
        raise HTTPException(500, f'Failed to retrieve task: {str(e)}')

# Update task endpoint
@app.patch('/tasks/{task_id}')
def update_task(task_id: str, req: UpdateTaskReq, db: Session = Depends(get_db)):
    """Update task status and report."""
    try:
        if not task_id or not task_id.strip():
            raise HTTPException(400, 'Invalid task_id')

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(404, 'Task not found')

        # Validate status
        valid_statuses = ['PENDING', 'RUNNING', 'DONE', 'FAILED']
        if req.status not in valid_statuses:
            raise HTTPException(400, f'Invalid status. Must be one of {valid_statuses}')

        task.status = req.status
        if req.report is not None:
            task.report = req.report
        if req.task_type is not None:
            task.task_type = req.task_type

        db.commit()
        logger.info(f"Task {task_id} updated to {req.status}")

        return {
            'ok': True,
            'task_id': task.id,
            'status': task.status
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating task: {str(e)}")
        raise HTTPException(500, f'Failed to update task: {str(e)}')