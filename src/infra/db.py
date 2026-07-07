from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from infra.config import get_config

# Initialize engine and SessionLocal at import time
_config = get_config()
engine = create_engine(
    _config.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_session():
    """Get a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def close_db():
    """Close all database connections."""
    SessionLocal.close_all()
    engine.dispose()
