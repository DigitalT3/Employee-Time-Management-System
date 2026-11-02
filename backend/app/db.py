"""SQLAlchemy engine and session factory. Schema is owned by Alembic (no create_all)."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()
database_url = (
    settings.TEST_DATABASE_URL
    if settings.APP_ENV == "test" and settings.TEST_DATABASE_URL
    else settings.DATABASE_URL
)
engine = create_engine(database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# PUBLIC_INTERFACE
def get_db() -> Iterator[Session]:
    """Yield a session per request; roll back on error and always close."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
