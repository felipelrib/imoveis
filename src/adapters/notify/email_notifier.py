import json
import smtplib
from email.message import EmailMessage

from adapters.notify.base import (
    Notifier,
    PriceDropAlert,
    SavedSearchNewMatches,
    SavedSearchPriceDrops,
    TopDealsDigest,
)
from infra.config import get_config
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)

NEW_MATCH_SMTP_TIMEOUT_SECONDS = 30


class EmailNotifier(Notifier):
    def __init__(self):
        self.cfg = get_config().alerts
        self.r = get_redis()

    def send(self, alert: PriceDropAlert) -> None:
        if getattr(self.cfg, "digest_mode", False):
            # push to redis list for price-drop digest (not top-deals)
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
                content += f"- Property {a.get('property_id')}: {a.get('old_price')} -> {a.get('new_price')} (-{a.get('drop_pct')}%)\n"  # noqa: E501

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

    def send_digest(self, digest: TopDealsDigest) -> None:
        """Send top-deals digest immediately via SMTP (never queues into alerts:email_digest)."""
        if not digest.properties:
            return

        msg = EmailMessage()
        msg["Subject"] = f"Top new deals ({len(digest.properties)} properties)"
        msg["From"] = getattr(self.cfg, "smtp_user", "") or "noreply@imoveis.local"
        msg["To"] = getattr(self.cfg, "digest_email", "admin@example.com") or "admin@example.com"

        lines = [
            f"Top new deals for principal {digest.principal_id}",
            f"Generated: {digest.generated_at.isoformat()}",
            f"Rule: {digest.rule}",
            "",
        ]
        for prop in digest.properties:
            title = prop.get("title") or prop.get("id")
            score = prop.get("combined_score")
            price = prop.get("price")
            neighbourhood = prop.get("neighborhood_name") or "-"
            lines.append(
                f"- {title}: price={price}, score={score}, neighbourhood={neighbourhood}"
            )
        msg.set_content("\n".join(lines))

        try:
            with smtplib.SMTP(
                getattr(self.cfg, "smtp_host", "localhost"),
                getattr(self.cfg, "smtp_port", 25),
            ) as server:
                user = getattr(self.cfg, "smtp_user", "")
                password = getattr(self.cfg, "smtp_pass", "")
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
            logger.info(
                "top_deals_digest_email_sent",
                principal_id=digest.principal_id,
                count=len(digest.properties),
            )
        except Exception as e:
            logger.error("top_deals_digest_email_failed", error=str(e))

    def send_new_matches(self, batch: SavedSearchNewMatches) -> None:
        """Send one saved search's new matches (Story 1.9, FR-32).

        Unlike the two methods above this one raises when the message was not
        handed to the mail server: the caller keeps the matches pending and
        tries again at its next run. No recipient is a failure too.
        """
        self._send_saved_search_email(batch, kind="new-match", event="saved_search_new_matches")

    def send_price_drops(self, batch: SavedSearchPriceDrops) -> None:
        """Send one saved search's price drops (Story 1.10, FR-32).

        Raises like ``send_new_matches``: the caller records an alert only for
        a message the mail server took, and gives the day back otherwise.
        """
        self._send_saved_search_email(batch, kind="price-drop", event="saved_search_price_drops")

    def _send_saved_search_email(self, batch, *, kind: str, event: str) -> None:
        """Hand one rendered saved-search message to the mail server, or raise.

        ``batch`` carries ``subject`` / ``body`` as they are sent. Logs
        ``<event>_email_sent`` or ``<event>_email_failed``.
        """
        recipient = (getattr(self.cfg, "digest_email", "") or "").strip()
        if not recipient:
            raise ValueError(
                "alerts.digest_email is empty: no recipient for " + kind + " alerts"
            )

        msg = EmailMessage()
        msg["Subject"] = batch.subject
        msg["From"] = getattr(self.cfg, "smtp_user", "") or "noreply@imoveis.local"
        msg["To"] = recipient
        msg.set_content(batch.body)

        try:
            # A server that accepts and never answers must not hold the task
            # (and its database session) past the next hourly run.
            with smtplib.SMTP(
                getattr(self.cfg, "smtp_host", "localhost"),
                getattr(self.cfg, "smtp_port", 25),
                timeout=NEW_MATCH_SMTP_TIMEOUT_SECONDS,
            ) as server:
                user = getattr(self.cfg, "smtp_user", "")
                password = getattr(self.cfg, "smtp_pass", "")
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        except Exception as e:
            logger.error(
                event + "_email_failed",
                principal_id=batch.principal_id,
                search_id=batch.search_id,
                error=str(e),
            )
            raise
        logger.info(
            event + "_email_sent",
            principal_id=batch.principal_id,
            search_id=batch.search_id,
            count=len(batch.property_ids),
        )
