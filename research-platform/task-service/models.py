# task-service/models.py
from sqlalchemy import Column, String, Text, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
import uuid
Base = declarative_base()
class Task(Base):
__tablename__ = 'tasks'
id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
query = Column(Text, nullable=False)
status = Column(String, default='PENDING') # PENDING|RUNNING|DONE|FAILED
report = Column(Text, nullable=True)
created = Column(DateTime(timezone=True), server_default=func.now())
updated = Column(DateTime(timezone=True), onupdate=func.now())