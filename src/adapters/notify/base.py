"""Abstract base class for notification adapters (AD-9)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PriceDropAlert:
    """Immutable payload for a price-drop notification."""

    property_id: str
    old_price: float
    new_price: float
    drop_pct: float
    platform: Optional[str] = None
    listing_type: Optional[str] = None


@dataclass(frozen=True)
class TopDealsDigest:
    """Immutable payload for a scheduled top-new-deals digest (BIN-52)."""

    principal_id: str
    generated_at: datetime
    properties: List[Dict[str, Any]] = field(default_factory=list)
    rule: str = ""


class Notifier(ABC):
    """Interface that all notifier backends must implement."""

    @abstractmethod
    def send(self, alert: PriceDropAlert) -> None:
        """Deliver a price-drop alert."""

    @abstractmethod
    def send_digest(self, digest: TopDealsDigest) -> None:
        """Deliver a top-deals digest (AD-9 registry)."""
