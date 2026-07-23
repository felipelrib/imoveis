import json
import smtplib
from email.message import EmailMessage

from adapters.notify.base import Notifier, PriceDropAlert
from infra.config import get_config
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)


class EmailNotifier(Notifier):
    def __init__(self):
        self.cfg = get_config().alerts
        self.r = get_redis()

    def send(self, alert: PriceDropAlert) -> None:
        if getattr(self.cfg, "digest_mode", False):
            # push to redis list for digest
            self.r.rpush("alerts:email_digest", json.dumps({
                "property_id": alert.property_id,
                "old_price": alert.old_price,
                "new_price": alert.new_price,
                "drop_pct": alert.drop_pct,
                "platform": alert.platform,
                "listing_type": alert.listing_type,
            }))
            logger.info("email_alert_queued_for_digest", property_id=alert.property_id)
        else:
            self.send_batch([alert])

    def send_batch(self, alerts: list) -> None:
        if not alerts:
            return

        msg = EmailMessage()
        msg['Subject'] = f"Price Drop Alerts ({len(alerts)} properties)"
        msg['From'] = getattr(self.cfg, "smtp_user", "") or "noreply@imoveis.local"
        msg['To'] = getattr(self.cfg, "digest_email", "admin@example.com")

        content = "Price Drop Alerts:\n\n"
        for a in alerts:
            if isinstance(a, PriceDropAlert):
                content += f"- Property {a.property_id}: {a.old_price} -> {a.new_price} (-{a.drop_pct}%)\n"
            else:
                content += f"- Property {a.get('property_id')}: {a.get('old_price')} -> {a.get('new_price')} (-{a.get('drop_pct')}%)\n"

        msg.set_content(content)

        try:
            with smtplib.SMTP(getattr(self.cfg, "smtp_host", "localhost"), getattr(self.cfg, "smtp_port", 25)) as server:
                user = getattr(self.cfg, "smtp_user", "")
                password = getattr(self.cfg, "smtp_pass", "")
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
            logger.info("email_alerts_sent", count=len(alerts))
        except Exception as e:
            logger.error("email_alerts_failed", error=str(e))
