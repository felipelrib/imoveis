
from sqlalchemy.orm import Session

from adapters.db.models import PlatformCheckpoint
from infra.logging import get_logger

logger = get_logger(__name__)


class CheckpointStore:
    """Persist per-platform checkpoints using DB table platform_checkpoints."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, platform_name: str) -> dict:
        """Get checkpoint for a platform."""
        checkpoint = self.session.query(PlatformCheckpoint).filter_by(platform_name=platform_name).first()
        if checkpoint:
            return checkpoint.data
        return {}

    def set(self, platform_name: str, data: dict) -> None:
        """Set checkpoint for a platform."""
        try:
            checkpoint = self.session.query(PlatformCheckpoint).filter_by(platform_name=platform_name).first()
            if checkpoint:
                checkpoint.data = data
            else:
                checkpoint = PlatformCheckpoint(platform_name=platform_name, data=data)
                self.session.add(checkpoint)
            self.session.commit()
        except Exception as e:
            # Log error and re-raise to ensure we don't silently lose checkpoints
            logger.warning("checkpoint_save_error", platform=platform_name, error=str(e))
            self.session.rollback()
            raise
