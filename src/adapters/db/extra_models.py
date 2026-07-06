from sqlalchemy import Column, String, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from .models import Base
import sqlalchemy as sa

class PlatformCheckpoint(Base):
    __tablename__ = 'platform_checkpoints'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    platform_name = Column(String, unique=True, nullable=False)
    data = Column(JSON)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class GPUControl(Base):
    __tablename__ = 'gpu_control'
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()'))
    name = Column(String, unique=True, nullable=False)
    value = Column(JSON)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
