import uuid

from celery.beat import PersistentScheduler, ScheduleEntry

from adapters.queue.celery_app import SCRAPE_TASK_NAME
from adapters.queue.scrape_single_flight import QUEUED, ScrapeSingleFlight, scrape_scope
from infra.logging import get_logger
from infra.redis_client import get_redis

logger = get_logger(__name__)


class RedisAwareScheduler(PersistentScheduler):
    """A Celery Beat scheduler that dynamically reads intervals from Redis.

    Before submitting a task, it checks Redis for `scheduler:interval:<platform>`.
    If the interval has changed, it updates the in-memory schedule and reschedules
    the task, avoiding the need to restart the beat process.

    A scheduled scrape is also single-flight per platform and scope (Story
    1.18): while one is queued or running, the tick publishes nothing.
    """

    def apply_entry(self, entry: ScheduleEntry, producer=None):
        r = get_redis()

        # Check if this task is a scraper task with dynamic interval
        if entry.name.startswith("scrape-"):
            platform = entry.name.replace("scrape-", "")
            override = r.get(f"scheduler:interval:{platform}")

            if override is not None:
                try:
                    new_interval = int(override)
                    if new_interval <= 0:
                        # Interval <= 0 means disabled, skip sending
                        logger.info(
                            "redis_scheduler_skipped",
                            task=entry.name,
                            reason="disabled_via_redis",
                        )
                        return

                    # Celery schedule is in seconds
                    new_interval_sec = new_interval * 60

                    if entry.schedule.run_every.total_seconds() != new_interval_sec:
                        logger.info(
                            "redis_scheduler_updated",
                            task=entry.name,
                            old=entry.schedule.run_every.total_seconds(),
                            new=new_interval,
                        )
                        from celery.schedules import schedule

                        entry.schedule = schedule(run_every=new_interval_sec)

                        # Reschedule it
                        self._maybe_sync()
                except ValueError:
                    override_str = (
                        override.decode() if isinstance(override, bytes) else str(override)
                    )
                    logger.warning(
                        "redis_scheduler_invalid_override",
                        task=entry.name,
                        override=override_str,
                    )

        return super().apply_entry(entry, producer=producer)

    def apply_async(self, entry: ScheduleEntry, producer=None, advance=True, **kwargs):
        """Publish a scheduled scrape only when none is queued or running.

        Celery publishes with ``**entry.options`` and ignores ``kwargs``, so the
        reserved task id travels through a temporary copy of the options.
        """
        if entry.task != SCRAPE_TASK_NAME:
            return super().apply_async(entry, producer=producer, advance=advance, **kwargs)

        entry_args = list(entry.args or ())
        entry_kwargs = dict(entry.kwargs or {})
        platform = entry_args[0] if entry_args else entry_kwargs.get("platform_name")
        checkpoint = entry_args[1] if len(entry_args) > 1 else entry_kwargs.get("checkpoint")

        task_id = str(uuid.uuid4())
        flight = ScrapeSingleFlight(
            get_redis(),
            platform=str(platform),
            scope=scrape_scope(checkpoint),
            task_id=task_id,
        )
        status, holder_id = flight.reserve()
        if advance:
            entry = self.reserve(entry)
        if status != QUEUED:
            logger.info(
                "scrape_enqueue_skipped",
                task=entry.name,
                platform=platform,
                scope=flight.scope,
                reason=status.removeprefix("already_"),
                holder_task_id=holder_id,
            )
            return None

        original_options = entry.options
        entry.options = {**(original_options or {}), "task_id": task_id}
        try:
            return super().apply_async(entry, producer=producer, advance=False, **kwargs)
        except Exception:
            flight.cancel_reservation()
            raise
        finally:
            entry.options = original_options
