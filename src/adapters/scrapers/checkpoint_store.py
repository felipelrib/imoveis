
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from adapters.db.models import PlatformCheckpoint
from infra.logging import get_logger

logger = get_logger(__name__)


class OLXCheckpoint(BaseModel):
    page: int = 1
    url_index: int = 0
    processed_ids: list[str] = []


class QuintoAndarCheckpoint(BaseModel):
    min_price: float = 0.0
    max_price: float = 999999.0
    processed_ids: list[str] = []


CHECKPOINT_MODELS = {
    "olx": OLXCheckpoint,
    "quintoandar": QuintoAndarCheckpoint,
}


class CheckpointStore:
    """Persist per-platform checkpoints using DB table platform_checkpoints."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, platform_name: str) -> dict:
        """Get checkpoint for a platform."""
        row = self.session.query(PlatformCheckpoint).filter_by(platform_name=platform_name).first()
        if not row:
            return {}

        raw = row.data or {}
        try:
            model_cls = CHECKPOINT_MODELS.get(platform_name)
            if model_cls:
                return model_cls.model_validate(raw).model_dump()
        except ValidationError as exc:
            logger.warning("checkpoint_validation_failed", platform=platform_name, error=str(exc))
            return {}  # Fall back to fresh start rather than corrupt state
        return raw

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
