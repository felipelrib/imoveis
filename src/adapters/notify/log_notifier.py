"""Log-based notifier — always available, writes alerts to structured log."""

from __future__ import annotations

from adapters.notify.base import Notifier, PriceDropAlert, TopDealsDigest
from infra.logging import get_logger

logger = get_logger(__name__)


class LogNotifier(Notifier):
    """Deliver alerts via structured logging."""

    def send(self, alert: PriceDropAlert) -> None:
        drop_amount = alert.old_price - alert.new_price
        logger.warning(
            "price_drop_alert",
            property_id=alert.property_id,
            old_price=alert.old_price,
            new_price=alert.new_price,
            drop_amount=round(drop_amount, 2),
            drop_pct=round(alert.drop_pct, 2),
            platform=alert.platform,
            listing_type=alert.listing_type,
        )

    def send_digest(self, digest: TopDealsDigest) -> None:
        property_ids = [p.get("id") for p in digest.properties]
        logger.info(
            "top_deals_digest",
            principal_id=digest.principal_id,
            count=len(digest.properties),
            property_ids=property_ids,
            rule=digest.rule,
            generated_at=digest.generated_at.isoformat(),
        )
