"""Abstract base class for price-drop notifiers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PriceDropAlert:
    """Immutable payload for a price-drop notification."""

    property_id: str
    old_price: float
    new_price: float
    drop_pct: float
    platform: Optional[str] = None
    listing_type: Optional[str] = None


class Notifier(ABC):
    """Interface that all notifier backends must implement."""

    @abstractmethod
    def send(self, alert: PriceDropAlert) -> None:
        """Deliver a price-drop alert."""
