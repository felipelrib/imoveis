from adapters.db.extra_models import PlatformCheckpoint
from adapters.db.models import Base
from sqlalchemy.orm import Session

class CheckpointStore:
    """Persist per-platform checkpoints using DB table platform_checkpoints."""
    def __init__(self, session: Session):
        self.session = session

    def get(self, platform_name: str) -> dict:
        row = self.session.query(PlatformCheckpoint).filter_by(platform_name=platform_name).one_or_none()
        return row.data if row else {}

    def set(self, platform_name: str, data: dict) -> None:
        row = self.session.query(PlatformCheckpoint).filter_by(platform_name=platform_name).one_or_none()
        if row:
            row.data = data
        else:
            row = PlatformCheckpoint(platform_name=platform_name, data=data)
            self.session.add(row)
        self.session.commit()
