# task-service/main.py (key routes only)
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from .database import get_db
from .models import Task
app = FastAPI(title='Task Service')
class CreateTaskReq(BaseModel):
query: str
class UpdateTaskReq(BaseModel):
status: str
report: str | None = None
@app.post('/tasks', status_code=201)
def create_task(req: CreateTaskReq, db: Session = Depends(get_db)):
task = Task(query=req.query)
db.add(task); db.commit(); db.refresh(task)
return {'task_id': task.id, 'status': task.status}
@app.get('/tasks/{task_id}')
def get_task(task_id: str, db: Session = Depends(get_db)):
task = db.query(Task).filter(Task.id == task_id).first()
if not task: raise HTTPException(404, 'Task not found')
return task
@app.patch('/tasks/{task_id}')
def update_task(task_id: str, req: UpdateTaskReq, db: Session = Depends(get_db)):
task = db.query(Task).filter(Task.id == task_id).first()
if not task: raise HTTPException(404, 'Task not found')
task.status = req.status
if req.report: task.report = req.report
db.commit()
return {'ok': True}