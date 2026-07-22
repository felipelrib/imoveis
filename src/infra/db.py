from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infra.config import get_config

# Initialize engine and SessionLocal at import time
_config = get_config()
engine = create_engine(
    _config.database.url,
    pool_pre_ping=_config.database.pool_pre_ping,
    pool_recycle=3600,
    pool_size=_config.database.pool_size,
    max_overflow=_config.database.max_overflow,
    pool_timeout=_config.database.pool_timeout,
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
