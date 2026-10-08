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


@dataclass(frozen=True)
class SavedSearchNewMatches:
    """Immutable payload: the new matches of one saved search (Story 1.9, FR-32).

    The text is rendered by ``core.saved_search_alerts.render_new_match_email``;
    a channel delivers ``subject`` / ``body`` as they are.
    """

    principal_id: str
    search_id: str
    search_name: str
    subject: str
    body: str
    property_ids: List[str] = field(default_factory=list)
    generated_at: Optional[datetime] = None


class Notifier(ABC):
    """Interface that all notifier backends must implement."""

    @abstractmethod
    def send(self, alert: PriceDropAlert) -> None:
        """Deliver a price-drop alert."""

    @abstractmethod
    def send_digest(self, digest: TopDealsDigest) -> None:
        """Deliver a top-deals digest (AD-9 registry)."""

    def send_new_matches(self, batch: SavedSearchNewMatches) -> None:
        """Deliver one saved search's new matches; raise when it was not delivered.

        Not abstract: a channel that does not carry this message says so.
        """
        raise NotImplementedError(
            type(self).__name__ + " does not deliver saved-search new matches"
        )
