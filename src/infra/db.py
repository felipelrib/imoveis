from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.infra.config import get_config

# Global engine and session factory
_engine = None
_SessionLocal = None

def get_engine():
    """Get database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        _engine = create_engine(
            config.database_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )
    return _engine

def get_session() -> Session:
    """Get a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    return _SessionLocal()

def close_db():
    """Close all database connections."""
    global _engine, _SessionLocal
    if _SessionLocal:
        _SessionLocal.close_all()
    if _engine:
        _engine.dispose()
