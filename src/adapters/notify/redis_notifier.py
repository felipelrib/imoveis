"""Redis notifier — pushes alerts to a list for frontend consumption."""

from __future__ import annotations

import json

from adapters.notify.base import Notifier, PriceDropAlert
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)

ALERTS_KEY = "alerts:price_drops"
MAX_ALERTS = 200  # keep last N alerts


class RedisNotifier(Notifier):
    """Push price-drop alerts to a Redis list for frontend polling."""

    def send(self, alert: PriceDropAlert) -> None:
        try:
            r = get_redis()
            payload = {
                "property_id": alert.property_id,
                "old_price": alert.old_price,
                "new_price": alert.new_price,
                "drop_pct": round(alert.drop_pct, 2),
                "platform": alert.platform,
                "listing_type": alert.listing_type,
            }
            r.lpush(ALERTS_KEY, json.dumps(payload))
            r.ltrim(ALERTS_KEY, 0, MAX_ALERTS - 1)
            r.expire(ALERTS_KEY, 86400 * 7)  # 7 days TTL
            logger.info(
                "price_drop_alert_redis",
                property_id=alert.property_id,
                drop_pct=round(alert.drop_pct, 2),
            )
        except Exception as exc:
            logger.error("redis_notifier_error", error=str(exc))