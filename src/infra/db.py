"""Database engine and session factory.

Reads connection URL from centralized config. Provides a session generator
compatible with FastAPI's Depends() pattern.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infra.config import get_config

_cfg = get_config()

engine = create_engine(_cfg.database_url, pool_size=20, max_overflow=40)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session():
    """Yield a DB session; auto-close on exit. Use with FastAPI Depends()."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
